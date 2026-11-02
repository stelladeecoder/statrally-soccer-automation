"""M14: deterministic Kalshi contract ledger. Manual verified fills only; no API/trading."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import argparse
import json

def money(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("Missing monetary value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Invalid monetary value") from None
    if not result.is_finite():
        raise ValueError("Nonfinite money")
    return result

def summarize(events):
    """FIFO basis; BUY, SELL, SETTLE events in chronological input order.

    All amounts USD per contract; SETTLE.price must equal 0 or 1.
    Trading fees are recorded on each event, including settlements.
    """
    if not isinstance(events, list):
        raise ValueError("Events must be a list")
    seen = set()
    positions = defaultdict(list)
    realized = defaultdict(lambda: Decimal("0"))
    fees = defaultdict(lambda: Decimal("0"))
    proceeds = defaultdict(lambda: Decimal("0"))
    cost = defaultdict(lambda: Decimal("0"))
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
        quantity = event.get("quantity")
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("Quantity must be a positive integer")
        price = money(event.get("price"))
        fee = money(event.get("fee_usd"))
        if not Decimal("0") <= price <= Decimal("1") or fee < 0:
            raise ValueError("Invalid price or fee")
        if action == "SETTLE" and price not in (Decimal("0"), Decimal("1")):
            raise ValueError("Settlement payout must be zero or one")
        key = (ticker, side)
        fees[key] += fee
        if action == "BUY":
            positions[key].append([quantity, price])
            cost[key] += quantity * price
        else:
            remaining = quantity
            basis = Decimal("0")
            while remaining:
                if not positions[key]:
                    raise ValueError("Cannot sell/settle more contracts than owned")
                lot = positions[key][0]
                take = min(remaining, lot[0])
                basis += take * lot[1]
                lot[0] -= take
                remaining -= take
                if lot[0] == 0:
                    positions[key].pop(0)
            realized[key] += quantity * price - basis - fee
            proceeds[key] += quantity * price
        total_fills += 1
        if action == "BUY":
            # Deduct entry fees from net realized results immediately.
            realized[key] -= fee
    result = []
    for key in sorted(set(positions) | set(realized)):
        remaining = sum(q for q, _ in positions[key])
        result.append({"market_ticker": key[0], "side": key[1],
                       "open_contracts": remaining,
                       "open_cost_basis_usd": str(sum((q*p for q,p in positions[key]), Decimal("0"))),
                       "total_buy_cost_usd": str(cost[key]),
                       "proceeds_usd": str(proceeds[key]),
                       "fees_usd": str(fees[key]),
                       "realized_pnl_usd": str(realized[key])})
    return {"status": "user_supplied_events_unverified", "event_count": total_fills,
            "positions": result,
            "total_realized_pnl_usd": str(sum((realized[k] for k in realized), Decimal("0")))}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", required=True, help="Local JSON array of verified fill/settlement events")
    args = parser.parse_args()
    report = summarize(json.loads(Path(args.events).read_text(encoding="utf-8")))
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
