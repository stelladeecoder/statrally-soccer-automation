"""M14 FIFO accounting for supplied events. No authentication or trading."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Context, Decimal, InvalidOperation, localcontext
from pathlib import Path
import argparse
import json

def money(value):
    if isinstance(value, (bool, float)) or value is None:
        raise ValueError("Missing monetary value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid monetary value") from None
    if not result.is_finite():
        raise ValueError("Nonfinite money")
    return result

def timestamp(value):
    """Require an aware ISO timestamp and normalize to UTC."""
    if not isinstance(value, str):
        raise ValueError("Timezone-aware timestamp required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)

def summarize(events):
    # Ample headroom for bounded inputs and 18-place fee allocation.
    with localcontext(Context(prec=60)):
        return _summarize(events)


def _summarize(events):
    """FIFO basis; BUY, SELL, SETTLE events in chronological input order.

    All amounts USD per contract; SETTLE.price must equal 0 or 1.
    Entry fees stay in open basis until the associated FIFO contracts close.
    Timestamps are optional for legacy manual inputs; either all events have
    them (in nondecreasing order) or none do. Untimed histories cannot produce
    calendar reports. A position cycle ends only when its quantity reaches zero.
    """
    if not isinstance(events, list):
        raise ValueError("Events must be a list")
    seen = set()
    positions = defaultdict(list)
    realized = defaultdict(lambda: Decimal("0"))
    fees = defaultdict(lambda: Decimal("0"))
    proceeds = defaultdict(lambda: Decimal("0"))
    cost = defaultdict(lambda: Decimal("0"))
    settlement_results = {}
    cycles = {}
    cycle_counts = defaultdict(int)
    completed = []
    closures = []
    previous_time = None
    timed = ["timestamp" in e for e in events if isinstance(e, dict)]
    if any(timed) and not all(timed):
        raise ValueError("Mixed timed and untimed events")
    total_fills = 0
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Invalid event")
        eid = event.get("event_id")
        ticker = event.get("market_ticker")
        side = event.get("side")
        action = event.get("action")
        if not isinstance(eid, str) or not eid.strip() or eid in seen:
            raise ValueError("Missing or duplicate event id")
        seen.add(eid)
        if not isinstance(ticker, str) or not ticker.strip() or side not in ("YES", "NO"):
            raise ValueError("Invalid market or side")
        if action not in ("BUY", "SELL", "SETTLE"):
            raise ValueError("Unsupported action")
        when = timestamp(event["timestamp"]) if "timestamp" in event else None
        if when is not None and previous_time is not None and when < previous_time:
            raise ValueError("Events must be chronological")
        previous_time = when
        quantity = event.get("quantity")
        if type(quantity) is not int or not 0 < quantity <= 2**63 - 1:
            raise ValueError("Quantity must be a positive integer")
        price = money(event.get("price"))
        fee = money(event.get("fee_usd"))
        if any(value.as_tuple().exponent < -18 for value in (price, fee)) or fee >= Decimal("1e18"):
            raise ValueError("Monetary precision/range exceeds supported limits")
        if not Decimal("0") <= price <= Decimal("1") or fee < 0:
            raise ValueError("Invalid price or fee")
        if action == "SETTLE" and price not in (Decimal("0"), Decimal("1")):
            raise ValueError("Settlement payout must be zero or one")
        if action == "SETTLE":
            yes_payout = price if side == "YES" else 1 - price
            if ticker in settlement_results and settlement_results[ticker] != yes_payout:
                raise ValueError("Contradictory settlement payouts")
            settlement_results[ticker] = yes_payout
        elif ticker in settlement_results:
            raise ValueError("Trading after settlement")
        key = (ticker, side)
        fees[key] += fee
        if action == "BUY":
            if not positions[key]:
                cycle_counts[key] += 1
                cycles[key] = {"market_ticker": ticker, "side": side,
                               "cycle": cycle_counts[key], "entry_cost_usd": Decimal("0"),
                               "realized_pnl_usd": Decimal("0"), "early_exit_contracts": 0,
                               "opened_at": when.isoformat() if when else None}
            positions[key].append([quantity, price, fee])
            cost[key] += quantity * price
            cycles[key]["entry_cost_usd"] += quantity * price + fee
        else:
            remaining = quantity
            basis = Decimal("0")
            matched_entry_fees = Decimal("0")
            while remaining:
                if not positions[key]:
                    raise ValueError("Cannot sell/settle more contracts than owned")
                lot = positions[key][0]
                take = min(remaining, lot[0])
                basis += take * lot[1]
                allocated = lot[2] if take == lot[0] else (lot[2] * take / lot[0]).quantize(Decimal("1e-18"))
                matched_entry_fees += allocated
                lot[2] -= allocated
                lot[0] -= take
                remaining -= take
                if lot[0] == 0:
                    positions[key].pop(0)
            pnl = quantity * price - basis - matched_entry_fees - fee
            realized[key] += pnl
            proceeds[key] += quantity * price
            cycles[key]["realized_pnl_usd"] += pnl
            if action == "SELL":
                cycles[key]["early_exit_contracts"] += quantity
            closures.append({"event_id": eid, "market_ticker": ticker, "side": side,
                             "cycle": cycle_counts[key], "action": action, "quantity": quantity,
                             "timestamp": when.isoformat() if when else None,
                             "entry_cost_usd": str(basis + matched_entry_fees),
                             "exit_fee_usd": str(fee), "entry_fee_usd": str(matched_entry_fees),
                             "proceeds_usd": str(quantity * price), "realized_pnl_usd": str(pnl)})
            if not positions[key]:
                cycle = cycles.pop(key)
                cycle["closed_at"] = when.isoformat() if when else None
                completed.append({k: str(v) if isinstance(v, Decimal) else v for k, v in cycle.items()})
        total_fills += 1
    result = []
    for key in sorted(set(positions) | set(realized)):
        remaining = sum(lot[0] for lot in positions[key])
        open_fees = sum((lot[2] for lot in positions[key]), Decimal("0"))
        open_basis = sum((lot[0] * lot[1] for lot in positions[key]), Decimal("0"))
        result.append({"market_ticker": key[0], "side": key[1],
                       "open_contracts": remaining,
                       "open_cost_basis_usd": str(open_basis),
                       "open_entry_fees_usd": str(open_fees),
                       "open_total_basis_usd": str(open_basis + open_fees),
                       "total_buy_cost_usd": str(cost[key]),
                       "proceeds_usd": str(proceeds[key]),
                       "fees_usd": str(fees[key]),
                       "realized_pnl_usd": str(realized[key])})
    return {"status": "user_supplied_events_unverified", "event_count": total_fills,
            "positions": result,
            "completed_positions": completed, "closures": closures,
            "total_fees_usd": str(sum(fees.values(), Decimal("0"))),
            "unrealized_pnl_usd": None,
            "total_realized_pnl_usd": str(sum((realized[k] for k in realized), Decimal("0")))}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True, help="Local JSON array of verified fill/settlement events")
    args = parser.parse_args()
    report = summarize(json.loads(Path(args.events).read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
