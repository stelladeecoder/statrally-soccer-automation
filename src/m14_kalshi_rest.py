"""Current Kalshi REST/OpenAPI 3.35.0 offline adapter. No account HTTP calls.

Schema evidence: Kalshi's kalshi-typescript@3.35.0 generated models/docs.
Collection wrappers, scope and retained-settlement evidence are StatRally
metadata, not provider fields or invented archived-settlement endpoints.
"""
from datetime import datetime, timedelta, timezone
from decimal import Context, Decimal, localcontext
import re

from m14_import import CURRENT_SCHEMA, canonical, integer, text
from m14_position_ledger import contract_value, contracts, money, summarize, timestamp

ZERO = Decimal("0")
FILL_FIELDS = frozenset(("fill_id", "exchange_index", "trade_id", "order_id", "ticker", "market_ticker",
                        "side", "action", "outcome_side", "book_side", "count_fp", "yes_price_dollars",
                        "no_price_dollars", "is_taker", "created_time", "fee_cost", "subaccount_number", "ts"))
SETTLEMENT_FIELDS = frozenset(("ticker", "exchange_index", "event_ticker", "market_result", "yes_count_fp",
                              "yes_total_cost_dollars", "no_count_fp", "no_total_cost_dollars", "revenue",
                              "settled_time", "fee_cost", "value"))
POSITION_FIELDS = frozenset(("ticker", "exchange_index", "total_traded_dollars", "position_fp",
                            "market_exposure_dollars", "realized_pnl_dollars", "fees_paid_dollars", "last_updated_ts"))
CUTOFF_FIELDS = frozenset(("market_settled_ts", "trades_created_ts", "orders_updated_ts", "market_positions_last_updated_ts"))
COLLECTIONS = {"portfolio_fills": ("/portfolio/fills", "fills"),
               "historical_fills": ("/historical/fills", "fills"),
               "portfolio_settlements": ("/portfolio/settlements", "settlements"),
               "portfolio_positions": ("/portfolio/positions", "market_positions"),
               "historical_positions": ("/historical/positions", "market_positions")}


def dollars(value, *, signed=False):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?", value):
        raise ValueError("REST dollar amounts require fixed-point strings with at most six places")
    amount = money(value)
    if (not signed and amount < 0) or amount.copy_abs() >= Decimal("1e18"):
        raise ValueError("Dollar amount out of range")
    return amount


def count(value, *, zero=False, signed=False):
    if not isinstance(value, str):
        raise ValueError("REST count_fp must be a two-place string")
    return contracts(value, zero=zero, signed=signed)


def record_fields(record, allowed):
    if not isinstance(record, dict) or set(record) - allowed:
        raise ValueError("Unrecognized REST source fields require schema review")


def collection_records(bundle, name, scope):
    endpoint, array = COLLECTIONS[name]
    collection = bundle.get("collections", {}).get(name)
    if not isinstance(collection, dict) or collection.get("endpoint") != endpoint:
        raise ValueError("All live and historical collections with correct endpoints are required")
    query = collection.get("query")
    required = {"subaccount": scope["subaccount_number"]}
    if name in ("portfolio_fills", "portfolio_positions"):
        required["exchange_index"] = scope["exchange_index"]
    if name == "portfolio_positions":
        required["settlement_status"] = "all"
    if not isinstance(query, dict) or set(query) - set(required) - {"limit"}:
        raise ValueError("Time, ticker, order and count filters cannot establish full history")
    for key, value in required.items():
        if type(query.get(key)) is not type(value) or query[key] != value:
            raise ValueError("Collection query does not match the selected account scope")
    if "limit" in query:
        integer(query["limit"], 1)
    pages = collection.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("Response pages required even for an empty collection")
    cursor, used, records = "", set(), []
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or page.get("request_cursor") != cursor or cursor in used:
            raise ValueError("Missing, repeated or crossed pagination cursors")
        used.add(cursor)
        response = page.get("response")
        allowed = {array, "cursor"} | ({"event_positions"} if array == "market_positions" else set())
        if not isinstance(response, dict) or set(response) - allowed or not isinstance(response.get(array), list):
            raise ValueError("Invalid REST response page")
        if "event_positions" in response and not isinstance(response["event_positions"], list):
            raise ValueError("Invalid event-position aggregates")
        cursor = response.get("cursor", "" if array != "fills" else None)
        if not isinstance(cursor, str) or (not cursor and index != len(pages) - 1):
            raise ValueError("Invalid terminal cursor")
        records.extend(response[array])
    if cursor:
        raise ValueError("Additional response pages required")
    return records


def fill_time(record):
    if record.get("created_time") is not None:
        when = timestamp(record["created_time"])
        elapsed = when - datetime(1970, 1, 1, tzinfo=timezone.utc)
        seconds = elapsed.days * 86400 + elapsed.seconds
        if record.get("ts") is not None and integer(record["ts"]) != seconds:
            raise ValueError("Conflicting fill timestamps")
        return when
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=integer(record.get("ts")))


def normalize_current(bundle):
    with localcontext(Context(prec=60)):
        if not isinstance(bundle, dict):
            raise ValueError("REST snapshot must be an object")
        return _normalize_current(bundle)


def _normalize_current(bundle):
    if bundle.get("schema") != CURRENT_SCHEMA or bundle.get("data_kind") not in ("synthetic", "live"):
        raise ValueError("Versioned REST schema and explicit data label required")
    if bundle.get("history_from_inception") is not True:
        raise ValueError("Complete history from inception must be explicitly established")
    if set(bundle) != {"schema", "data_kind", "history_from_inception", "scope", "captured_at",
                      "historical_cutoff", "collections", "retained_settlements"}:
        raise ValueError("Unrecognized or missing REST snapshot metadata")
    scope = bundle.get("scope")
    if not isinstance(scope, dict) or set(scope) != {"account_ref", "subaccount_number", "exchange_index", "netting_mode"}:
        raise ValueError("One explicit private account/subaccount/shard scope required")
    text(scope.get("account_ref"))
    if not 0 <= integer(scope.get("subaccount_number")) <= 63 or scope.get("netting_mode") != "net":
        raise ValueError("Only explicitly verified net-position accounts are supported")
    shard = integer(scope.get("exchange_index"))
    captured = timestamp(bundle.get("captured_at"))
    cutoff = bundle.get("historical_cutoff")
    record_fields(cutoff, CUTOFF_FIELDS)
    for field in ("market_settled_ts", "trades_created_ts", "orders_updated_ts"):
        if timestamp(cutoff.get(field)) > captured:
            raise ValueError("Historical cutoff is newer than the snapshot")
    if "market_positions_last_updated_ts" in cutoff and timestamp(cutoff["market_positions_last_updated_ts"]) > captured:
        raise ValueError("Position backfill horizon is newer than snapshot")
    if not isinstance(bundle.get("collections"), dict) or set(bundle["collections"]) != set(COLLECTIONS):
        raise ValueError("Both live and historical fills AND positions must be collected")
    records = {name: collection_records(bundle, name, scope) for name in COLLECTIONS}
    sources, fills, historical_ids = {}, {}, set()

    def source(key, record):
        serialized = canonical(record)
        if key in sources and sources[key] != serialized:
            raise ValueError("Conflicting duplicate REST source")
        sources[key] = serialized

    for name in ("historical_fills", "portfolio_fills"):
        for record in records[name]:
            record_fields(record, FILL_FIELDS)
            fid, ticker = text(record.get("fill_id")), text(record.get("ticker"))
            if integer(record.get("exchange_index")) != shard:
                raise ValueError("Mixed exchange shards require separate scoped imports")
            if type(record.get("subaccount_number")) is not int or record["subaccount_number"] != scope["subaccount_number"]:
                raise ValueError("Missing or mixed direct-user subaccount evidence")
            if record.get("trade_id", fid) != fid or record.get("market_ticker", ticker) != ticker:
                raise ValueError("Conflicting legacy identities")
            text(record.get("order_id"))
            if type(record.get("is_taker")) is not bool:
                raise ValueError("Fill liquidity flag required")
            direction, book = record.get("outcome_side"), record.get("book_side")
            if direction not in ("yes", "no") or book != ("bid" if direction == "yes" else "ask"):
                raise ValueError("Inconsistent canonical fill direction")
            if "side" in record and record["side"] not in ("yes", "no"):
                raise ValueError("Invalid deprecated side")
            if "action" in record and record["action"] not in ("buy", "sell"):
                raise ValueError("Invalid deprecated action")
            if "side" in record and "action" in record:
                side, action = record["side"], record["action"]
                legacy_direction = side if action == "buy" else "no" if side == "yes" else "yes"
                if legacy_direction != direction:
                    raise ValueError("Legacy and canonical fill directions conflict")
            quantity = count(record.get("count_fp"))
            prices = {side: dollars(record.get(side + "_price_dollars")) for side in ("yes", "no")}
            if any(value > 1 for value in prices.values()) or sum(prices.values()) != 1:
                raise ValueError("Invalid complementary fill prices")
            fee, when = dollars(record.get("fee_cost")), fill_time(record)
            if when > captured:
                raise ValueError("Fill is newer than the snapshot")
            sid = "rest-fill:" + str(shard) + ":" + fid
            source(sid, record)
            fills[sid] = {"sid": sid, "ticker": ticker, "direction": direction.upper(), "quantity": quantity,
                          "prices": {key.upper(): value for key, value in prices.items()}, "fee": fee, "when": when}
            if name == "historical_fills":
                historical_ids.add(sid)
    if any(item["when"] < timestamp(cutoff["trades_created_ts"]) and sid not in historical_ids for sid, item in fills.items()):
        raise ValueError("Older fills require historical endpoint coverage")

    settlements = {}
    retained = bundle.get("retained_settlements")
    if not isinstance(retained, list):
        raise ValueError("Explicit retained-settlement evidence list required, even when empty")
    settlement_records = list(records["portfolio_settlements"])
    for item in retained:
        if not isinstance(item, dict) or set(item) != {"record", "reviewed", "evidence_reference"} or item.get("reviewed") is not True:
            raise ValueError("Archived closure evidence must be independently reviewed")
        text(item.get("evidence_reference"))
        settlement_records.append(item.get("record"))
    for record in settlement_records:
        record_fields(record, SETTLEMENT_FIELDS)
        ticker = text(record.get("ticker"))
        text(record.get("event_ticker"))
        if integer(record.get("exchange_index")) != shard or record.get("market_result") not in ("yes", "no"):
            raise ValueError("Unsupported shard or non-binary settlement")
        when = timestamp(record.get("settled_time"))
        if when > captured:
            raise ValueError("Settlement is newer than snapshot")
        sid = "rest-settlement:" + str(shard) + ":" + ticker + ":" + when.isoformat()
        source(sid, record)
        if ticker in settlements and settlements[ticker][0] != sid:
            raise ValueError("Settlement revisions require manual reconciliation")
        settlements[ticker] = (sid, record, when)

    timeline = [(item["when"], "fill", sid, item) for sid, item in fills.items()]
    timeline.extend((when, "settlement", sid, record) for sid, record, when in settlements.values())
    timeline.sort(key=lambda item: (item[0], item[2]))
    events, inventory, times, settled = [], {}, set(), set()
    for when, kind, sid, item in timeline:
        ticker = item["ticker"]
        if (when, ticker) in times:
            raise ValueError("Ambiguous same-market event ordering")
        times.add((when, ticker))
        if ticker in settled:
            raise ValueError("Event after final settlement")
        if kind == "fill":
            direction, quantity, fee = item["direction"], item["quantity"], item["fee"]
            opposite = "NO" if direction == "YES" else "YES"
            close = min(quantity, inventory.get((ticker, opposite), ZERO))
            close_fee = fee if close == quantity else (fee * close / quantity).quantize(Decimal("1e-18"))
            for suffix, action, side, size, allocated_fee in (("close", "SELL", opposite, close, close_fee),
                                                             ("open", "BUY", direction, quantity - close, fee - close_fee)):
                if size:
                    events.append({"event_id": sid + ":" + suffix, "source_id": sid, "market_ticker": ticker,
                                   "side": side, "action": action, "quantity": contract_value(size),
                                   "price": str(item["prices"][side]), "fee_usd": str(allocated_fee), "timestamp": when.isoformat()})
                    inventory[(ticker, side)] = inventory.get((ticker, side), ZERO) + (size if action == "BUY" else -size)
            continue
        ledger = summarize(events)
        positions = {(p["market_ticker"], p["side"]): p for p in ledger["positions"]}
        market_fees = sum((money(p["fees_usd"]) for p in ledger["positions"] if p["market_ticker"] == ticker), ZERO)
        # Conservative gate: fee_cost must reconcile to cumulative source fill
        # fees. Provider semantics still require real-account acceptance evidence.
        if dollars(item.get("fee_cost")) != market_fees:
            raise ValueError("Settlement fee total does not reconcile to source fill fees")
        revenue = ZERO
        for side in ("yes", "no"):
            size = count(item.get(side + "_count_fp"), zero=True)
            position = positions.get((ticker, side.upper()), {})
            if size != contracts(position.get("open_contracts", 0), zero=True):
                raise ValueError("Settlement quantity mismatch; incomplete fill history")
            if dollars(item.get(side + "_total_cost_dollars")) != money(position.get("open_cost_basis_usd", "0")):
                raise ValueError("Settlement cost does not reconcile to gross FIFO basis")
            payout = int(side == item["market_result"])
            revenue += size * payout * 100
            if size:
                events.append({"event_id": sid + ":" + side, "source_id": sid, "market_ticker": ticker,
                               "side": side.upper(), "action": "SETTLE", "quantity": contract_value(size),
                               "price": str(payout), "fee_usd": "0", "timestamp": when.isoformat()})
            inventory[(ticker, side.upper())] = ZERO
        if Decimal(integer(item.get("revenue"))) != revenue:
            raise ValueError("Settlement cent revenue mismatch")
        if item.get("value") is not None and integer(item["value"]) != (100 if item["market_result"] == "yes" else 0):
            raise ValueError("Settlement value contradicts result")
        settled.add(ticker)

    ledger = summarize(events)
    last_events = {}
    for event in events:
        when = timestamp(event["timestamp"])
        last_events[event["market_ticker"]] = max(last_events.get(event["market_ticker"], when), when)
    provider_positions, archived = {}, set()
    for name in ("portfolio_positions", "historical_positions"):
        for record in records[name]:
            record_fields(record, POSITION_FIELDS)
            ticker = text(record.get("ticker"))
            if integer(record.get("exchange_index")) != shard:
                raise ValueError("Position scope mismatch")
            count(record.get("position_fp"), zero=True, signed=True)
            for field in ("total_traded_dollars", "market_exposure_dollars", "fees_paid_dollars"):
                dollars(record.get(field))
            dollars(record.get("realized_pnl_dollars"), signed=True)
            if timestamp(record.get("last_updated_ts")) > captured:
                raise ValueError("Position is newer than capture")
            if ticker in last_events and timestamp(record["last_updated_ts"]) < last_events[ticker]:
                raise ValueError("Position snapshot predates its latest imported event")
            if ticker in provider_positions and canonical(provider_positions[ticker]) != canonical(record):
                raise ValueError("Conflicting live/historical position snapshots")
            provider_positions[ticker] = record
            if name == "historical_positions":
                archived.add(ticker)
    known_markets = {item["ticker"] for item in fills.values()} | set(settlements)
    if not known_markets.issubset(provider_positions):
        raise ValueError("Missing live/archived position coverage for imported markets")
    for ticker, position in provider_positions.items():
        if ticker not in known_markets and (dollars(position["total_traded_dollars"]) or count(position["position_fp"], zero=True, signed=True)):
            raise ValueError("Position has activity but its fill history is missing")
        yes, no = inventory.get((ticker, "YES"), ZERO), inventory.get((ticker, "NO"), ZERO)
        if ticker in archived and (yes or no):
            raise ValueError("Archived holdings need retained reviewed closure records; aggregates cannot supply payout dates")
        if yes - no != count(position["position_fp"], zero=True, signed=True):
            raise ValueError("Provider net inventory mismatch; incomplete history or missing settlement")
        paid = sum((money(p["fees_usd"]) for p in ledger["positions"] if p["market_ticker"] == ticker), ZERO)
        if paid != dollars(position["fees_paid_dollars"]):
            raise ValueError("Provider fee total mismatch; incomplete fill fee evidence")
    return {"events": events, "sources": sources, "data_kind": bundle["data_kind"],
            "input_schema": CURRENT_SCHEMA, "scope": scope, "captured_at": captured.isoformat()}
