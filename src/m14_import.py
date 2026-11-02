"""Offline Kalshi SDK 3.2.0 response adapter and private transactional store.

Only GET response data is consumed. No API credentials or order endpoints.
"""
import argparse
from datetime import datetime, timezone
from decimal import localcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from m14_position_ledger import money, summarize, timestamp

SCHEMA = "kalshi-sdk-3.2.0"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def read_json(path):
    # Monetary fields for this adapter are strings or integer cents, never floats.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def private_path(path):
    """Reject persistent personal state anywhere inside a Git checkout."""
    resolved = Path(path).expanduser().resolve()
    checkout = Path(__file__).resolve().parents[1]
    if resolved == checkout or checkout in resolved.parents:
        raise ValueError("Personal state must be outside the public checkout")
    if any((parent / ".git").is_file() or (parent / ".git" / "HEAD").is_file()
           for parent in resolved.parents):
        raise ValueError("Personal state must be outside Git checkouts")
    return resolved


def connect(path):
    path = private_path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    os.chmod(path, 0o600)
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources (source_id TEXT PRIMARY KEY, record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            record TEXT NOT NULL, FOREIGN KEY(source_id) REFERENCES sources(source_id));
        CREATE TABLE IF NOT EXISTS outbox (report_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','delivered','uncertain')));
    """)
    return db


def integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Invalid integer count or cents")
    return value


def text(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("Missing or invalid source identity")
    return value


def pages(bundle, name):
    wrappers = bundle.get(name + "_pages")
    if not isinstance(wrappers, list) or not wrappers:
        raise ValueError("Complete response pages required, including empty histories")
    expected = ""
    used = set()
    records = []
    for index, wrapper in enumerate(wrappers):
        if not isinstance(wrapper, dict) or wrapper.get("request_cursor") != expected or expected in used:
            raise ValueError("Incomplete or repeated pagination")
        used.add(expected)
        response = wrapper.get("response")
        if not isinstance(response, dict) or not isinstance(response.get(name), list):
            raise ValueError("Invalid response page")
        cursor = response.get("cursor", "" if name == "settlements" else None)
        if cursor is None and name == "settlements":
            cursor = ""
        if not isinstance(cursor, str) or (not cursor and index != len(wrappers) - 1):
            raise ValueError("Invalid pagination cursor")
        records.extend(response[name])
        expected = cursor
    if expected:
        raise ValueError("More pages required")
    return records


def normalize_snapshot(bundle):
    with localcontext() as context:
        context.prec = 60
        return _normalize_snapshot(bundle)


def _normalize_snapshot(bundle):
    """Normalize one complete from-inception snapshot; fail atomically on doubt.

    Fee evidence and bundle/page wrappers are StatRally input contracts, NOT
    invented Kalshi API fields. See docs/m14_performance.md for schema sources.
    """
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise ValueError("Unsupported input schema")
    kind = bundle.get("data_kind")
    if kind not in ("synthetic", "live"):
        raise ValueError("Explicit synthetic/live data label required")
    if bundle.get("history_from_inception") is not True:
        raise ValueError("Full history from inception required")
    evidence = bundle.get("fill_fees")
    if not isinstance(evidence, list):
        raise ValueError("Explicit fill fee evidence required")
    sources = {}

    def source(key, record):
        serialized = canonical(record)
        if key in sources and sources[key] != serialized:
            raise ValueError("Conflicting duplicate source")
        sources[key] = serialized

    fee_map = {}
    for item in evidence:
        if not isinstance(item, dict):
            raise ValueError("Invalid fee evidence")
        fid = text(item.get("fill_id"))
        fee = money(item.get("fee_usd"))
        if fee < 0:
            raise ValueError("Negative fee")
        source("fee:" + fid, item)
        fee_map[fid] = fee

    timeline = {}
    fill_ids = set()
    for record in pages(bundle, "fills"):
        if not isinstance(record, dict):
            raise ValueError("Invalid fill")
        fid = text(record.get("fill_id"))
        ticker = text(record.get("ticker"))
        if record.get("trade_id", fid) != fid or record.get("market_ticker", ticker) != ticker:
            raise ValueError("Conflicting legacy identity")
        source("fill:" + fid, record)
        fill_ids.add(fid)
        if fid not in fee_map:
            raise ValueError("Missing fill fee evidence; do not assume zero")
        side, action = record.get("side"), record.get("action")
        if side not in ("yes", "no") or action not in ("buy", "sell"):
            raise ValueError("Unsupported fill side/action; orders are not fills")
        count = integer(record.get("count"), 1)
        prices = {}
        for name in ("yes", "no"):
            fixed = record.get(name + "_price_fixed")
            if not isinstance(fixed, str):
                raise ValueError("SDK 3.2.0 fixed-dollar prices required")
            prices[name] = money(fixed)
            if not 0 <= prices[name] <= 1:
                raise ValueError("Invalid fixed-dollar price")
            cents = record.get(name + "_price")
            if cents is not None and money(integer(cents)) / 100 != prices[name]:
                raise ValueError("Conflicting cent and fixed-dollar prices")
        if sum(prices.values()) != 1:
            raise ValueError("YES/NO prices must be complementary")
        if record.get("created_time") is not None:
            when = timestamp(record["created_time"])
            if record.get("ts") is not None and integer(record["ts"]) != int(when.timestamp()):
                raise ValueError("Conflicting fill timestamps")
        else:
            when = datetime.fromtimestamp(integer(record.get("ts")), timezone.utc)
        event = {"event_id": "kalshi:fill:" + fid, "source_id": "fill:" + fid,
                 "market_ticker": ticker, "side": side.upper(), "action": action.upper(),
                 "quantity": count, "price": str(prices[side]), "fee_usd": str(fee_map[fid]),
                 "timestamp": when.isoformat()}
        timeline[event["event_id"]] = (when, "fill", event)
    if set(fee_map) != fill_ids:
        raise ValueError("Fee evidence has no matching fill")

    settled_markets = {}
    for record in pages(bundle, "settlements"):
        if not isinstance(record, dict):
            raise ValueError("Invalid settlement")
        ticker = text(record.get("ticker"))
        when = timestamp(record.get("settled_time"))
        sid = "settlement:" + ticker + ":" + when.isoformat()
        source(sid, record)
        if ticker in settled_markets and settled_markets[ticker] != sid:
            raise ValueError("Multiple settlement revisions require review")
        settled_markets[ticker] = sid
        if record.get("market_result") not in ("yes", "no"):
            raise ValueError("Scalar/void settlements require a separate reviewed adapter")
        timeline[sid] = (when, "settlement", (sid, record))

    ordered = sorted(timeline.values(), key=lambda item: (item[0], str(item[2])))
    # Never infer an economic order for simultaneous trades/settlement in a market.
    times = set()
    inventory_counts = {}
    events = []
    for when, item_kind, item in ordered:
        ticker = item["market_ticker"] if item_kind == "fill" else item[1]["ticker"]
        if (when, ticker) in times:
            raise ValueError("Ambiguous same-market event ordering; review source precision")
        times.add((when, ticker))
        if item_kind == "fill":
            key = (ticker, item["side"])
            opposite = (ticker, "NO" if item["side"] == "YES" else "YES")
            if item["action"] == "BUY" and inventory_counts.get(opposite, 0):
                raise ValueError("Opposite-side netting needs an independently verified adapter")
            inventory_counts[key] = inventory_counts.get(key, 0) + (item["quantity"] if item["action"] == "BUY" else -item["quantity"])
            if inventory_counts[key] < 0:
                raise ValueError("Sell without sufficient prior fills")
            events.append(item)
            continue
        sid, record = item
        before = summarize(events)
        positions = {(p["market_ticker"], p["side"]): p for p in before["positions"]}
        expected_revenue = 0
        market_fees = sum((money(p["fees_usd"]) for p in before["positions"] if p["market_ticker"] == ticker), money("0"))
        if money(record.get("fee_cost")) != market_fees:
            raise ValueError("Settlement fee total does not reconcile to fill fee evidence")
        for side in ("yes", "no"):
            quantity = integer(record.get(side + "_count"))
            reported_cost = money(integer(record.get(side + "_total_cost"))) / 100
            position = positions.get((ticker, side.upper()), {})
            if quantity != position.get("open_contracts", 0):
                raise ValueError("Settlement quantity does not reconcile; missing fills")
            if reported_cost != money(position.get("open_cost_basis_usd", "0")):
                raise ValueError("Settlement cost basis does not reconcile")
            payout = int(side == record["market_result"])
            expected_revenue += quantity * payout * 100
            if quantity:
                events.append({"event_id": "kalshi:" + sid + ":" + side, "source_id": sid,
                               "market_ticker": ticker, "side": side.upper(), "action": "SETTLE",
                               "quantity": quantity, "price": str(payout), "fee_usd": "0",
                               "timestamp": when.isoformat()})
            inventory_counts[(ticker, side.upper())] = 0
        if integer(record.get("revenue")) != expected_revenue:
            raise ValueError("Settlement revenue does not reconcile")
        if record.get("value") is not None and integer(record["value"]) != (100 if record["market_result"] == "yes" else 0):
            raise ValueError("Settlement value contradicts result")
    # Also rejects oversells, incomplete histories, and trading after settlement.
    summarize(events)
    for event in events:
        if event["action"] != "SETTLE" and event["market_ticker"] in settled_markets:
            settled_at = timestamp(json.loads(sources[settled_markets[event["market_ticker"]]])["settled_time"])
            if timestamp(event["timestamp"]) >= settled_at:
                raise ValueError("Trading after reported settlement")
    return {"events": events, "sources": sources, "data_kind": kind}


def import_snapshot(db, bundle):
    normalized = normalize_snapshot(bundle)
    with db:
        db.execute("BEGIN IMMEDIATE")
        previous = dict(db.execute("SELECT source_id,record FROM sources"))
        sources = normalized["sources"]
        if not set(previous).issubset(sources):
            raise ValueError("Snapshot drops previously imported records")
        if any(sources[key] != value for key, value in previous.items()):
            raise ValueError("Previously imported source changed; reconciliation required")
        label = db.execute("SELECT value FROM metadata WHERE key='data_kind'").fetchone()
        if label and label[0] != normalized["data_kind"]:
            raise ValueError("Synthetic and live data require separate stores")
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('data_kind',?)", (normalized["data_kind"],))
        for key, record in sources.items():
            db.execute("INSERT OR IGNORE INTO sources VALUES (?,?)", (key, record))
        existing_events = dict(db.execute("SELECT event_id,record FROM events"))
        for event in normalized["events"]:
            serialized = canonical(event)
            if event["event_id"] in existing_events and existing_events[event["event_id"]] != serialized:
                raise ValueError("Normalized event changed")
            db.execute("INSERT OR IGNORE INTO events VALUES (?,?,?)", (event["event_id"], event["source_id"], serialized))
    return {"status": "imported", "new_source_records": len(sources) - len(previous),
            "event_count": len(normalized["events"]), "data_kind": normalized["data_kind"]}


def load_history(db):
    label = db.execute("SELECT value FROM metadata WHERE key='data_kind'").fetchone()
    if not label:
        raise ValueError("Import a complete snapshot first")
    events = [json.loads(row[0]) for row in db.execute("SELECT record FROM events")]
    events.sort(key=lambda event: (timestamp(event["timestamp"]), event["event_id"]))
    return events, label[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, help="Private local full-response bundle")
    parser.add_argument("--database", required=True, help="Durable private SQLite path outside Git")
    args = parser.parse_args()
    try:
        with connect(args.database) as db:
            result = import_snapshot(db, read_json(args.snapshot))
        print(canonical(result))
    except (ValueError, OSError, sqlite3.Error, TypeError, OverflowError, KeyError) as error:
        # Never echo raw records, paths or source identifiers in public logs.
        parser.exit(2, f"M14 import rejected ({type(error).__name__}); inspect private inputs and documentation.\n")


if __name__ == "__main__":
    main()
