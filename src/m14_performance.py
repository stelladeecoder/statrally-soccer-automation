"""Actual-event performance reports; no mark prices, model returns or API calls."""
import argparse
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
import json
import sqlite3
from zoneinfo import ZoneInfo

from m14_import import canonical, connect, digest, load_history, read_json
from m14_position_ledger import money, summarize, timestamp

CENTRAL = ZoneInfo("America/Chicago")
ZERO = Decimal("0")


def total(rows, field):
    return sum((money(row[field]) for row in rows), ZERO)


def metrics(ledger, events, start, end):
    def included(value):
        return start <= timestamp(value) < end
    closures = [row for row in ledger["closures"] if included(row["timestamp"])]
    completed = [row for row in ledger["completed_positions"] if included(row["closed_at"])]
    interval_events = [row for row in events if included(row["timestamp"])]
    early = [row for row in closures if row["action"] == "SELL"]
    net, denominator = total(closures, "realized_pnl_usd"), total(closures, "entry_cost_usd")
    wins = sum(money(row["realized_pnl_usd"]) > 0 for row in completed)
    losses = sum(money(row["realized_pnl_usd"]) < 0 for row in completed)
    count = len(completed)
    markets = {}
    for row in closures:
        ticker = row["market_ticker"]
        markets[ticker] = markets.get(ticker, ZERO) + money(row["realized_pnl_usd"])
    return {"realized_net_pnl_usd": str(net),
            "fees_paid_usd": str(total(interval_events, "fee_usd")),
            "recognized_fees_usd": str(total(closures, "entry_fee_usd") + total(closures, "exit_fee_usd")),
            "closed_entry_cost_usd": str(denominator),
            "roi": str(net / denominator) if denominator else None,
            "completed_positions": count, "wins": wins, "losses": losses,
            "breakeven": count - wins - losses,
            "win_rate": str(Decimal(wins) / count) if count else None,
            "loss_rate": str(Decimal(losses) / count) if count else None,
            "completed_position_pnl_usd": str(total(completed, "realized_pnl_usd")),
            "early_exit_events": len(early), "early_exit_contracts": sum(row["quantity"] for row in early),
            "early_exit_realized_pnl_usd": str(total(early, "realized_pnl_usd")),
            "profit_by_market_usd": {key: str(value) for key, value in sorted(markets.items())}}


def reconciliation_values(ledger):
    """Independent statement totals must match these values at the cutoff."""
    return {"realized_net_pnl_usd": ledger["total_realized_pnl_usd"],
            "fees_paid_usd": ledger["total_fees_usd"],
            "gross_proceeds_usd": str(total(ledger["positions"], "proceeds_usd")),
            "gross_buy_cost_usd": str(total(ledger["positions"], "total_buy_cost_usd")),
            "open_positions": [{"market_ticker": row["market_ticker"], "side": row["side"],
                                "quantity": row["open_contracts"], "basis_usd": row["open_total_basis_usd"]}
                               for row in ledger["positions"] if row["open_contracts"]]}


def verify_review(review, history_hash, end, actual):
    if review is None:
        return False
    if not isinstance(review, dict) or review.get("schema_version") != 1 or review.get("reviewed") is not True:
        raise ValueError("Reviewed reconciliation evidence required")
    if review.get("history_sha256") != history_hash or review.get("cutoff_exclusive") != end.isoformat():
        raise ValueError("Reconciliation is stale or for another cutoff")
    if review.get("data_kind") != "live":
        raise ValueError("Live reconciliation label required")
    # Evidence is a local operator attestation, not a claim of API authentication.
    if not isinstance(review.get("evidence_reference"), str) or not review["evidence_reference"].strip():
        raise ValueError("Private independent statement reference required")
    expected = review.get("expected")
    if not isinstance(expected, dict) or set(expected) != set(actual):
        raise ValueError("All reconciliation totals required")
    for field in ("realized_net_pnl_usd", "fees_paid_usd", "gross_proceeds_usd", "gross_buy_cost_usd"):
        if money(expected[field]) != money(actual[field]):
            raise ValueError("Independent totals do not reconcile")
    expected_open = expected["open_positions"]
    if not isinstance(expected_open, list):
        raise ValueError("Independent open inventory required")
    def inventory(rows):
        result = {}
        for row in rows:
            key = (row["market_ticker"], row["side"])
            if key in result or type(row["quantity"]) is not int or row["quantity"] <= 0:
                raise ValueError("Invalid reconciliation inventory")
            result[key] = (row["quantity"], money(row["basis_usd"]))
        return result
    if inventory(expected_open) != inventory(actual["open_positions"]):
        raise ValueError("Independent open inventory does not reconcile")
    return True


def build_report(events, data_kind, period, through, review=None):
    with localcontext() as context:
        context.prec = 60
        return _build_report(events, data_kind, period, through, review)


def _build_report(events, data_kind, period, through, review):
    if data_kind not in ("synthetic", "live") or period not in ("daily", "weekly", "cumulative"):
        raise ValueError("Invalid report label or period")
    day = date.fromisoformat(through)
    end = datetime.combine(day + timedelta(days=1), time.min, CENTRAL)
    # Validate even future events; never hide malformed/untimed history at cutoff.
    summarize(events)
    if any("timestamp" not in event for event in events):
        raise ValueError("Calendar reports require timestamps")
    selected = [event for event in events if timestamp(event["timestamp"]) < end]
    ledger = summarize(selected)
    inception = min((timestamp(event["timestamp"]).astimezone(CENTRAL).date() for event in selected), default=day)
    start_day = day if period == "daily" else day - timedelta(days=day.weekday()) if period == "weekly" else inception
    start = datetime.combine(start_day, time.min, CENTRAL)
    inception_start = datetime.combine(inception, time.min, CENTRAL)
    history_hash = digest({"data_kind": data_kind, "events": selected})
    actual = reconciliation_values(ledger)
    verified = verify_review(review, history_hash, end, actual)
    if verified and data_kind != "live":
        raise ValueError("Synthetic data cannot be verified as real results")
    interval = metrics(ledger, selected, start, end)
    cumulative = metrics(ledger, selected, inception_start, end)
    # Sparse daily series: include dates with executions/closures and the cutoff.
    days = sorted({timestamp(event["timestamp"]).astimezone(CENTRAL).date() for event in selected
                   if timestamp(event["timestamp"]) >= start} | {day})
    series = []
    running = total([row for row in ledger["closures"] if timestamp(row["timestamp"]) < start], "realized_pnl_usd")
    for current in days:
        left = datetime.combine(current, time.min, CENTRAL)
        right = datetime.combine(current + timedelta(days=1), time.min, CENTRAL)
        daily = metrics(ledger, selected, left, right)
        running += money(daily["realized_net_pnl_usd"])
        series.append({"date": current.isoformat(), "realized_net_pnl_usd": daily["realized_net_pnl_usd"],
                       "cumulative_realized_net_pnl_usd": str(running)})
    return {"schema_version": 1, "data_kind": data_kind,
            "verification": "operator_reconciled" if verified else "unverified",
            "history_sha256": history_hash, "period": period, "timezone": "America/Chicago",
            "start_inclusive": start.isoformat(), "cutoff_exclusive": end.isoformat(),
            "through": through, "metrics": interval, "cumulative": cumulative,
            "open_positions": actual["open_positions"], "unrealized_pnl_usd": None,
            "performance_over_time": series, "reconciliation_values": actual}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--period", choices=("daily", "weekly", "cumulative"), default="daily")
    parser.add_argument("--through", required=True, help="Inclusive America/Chicago date YYYY-MM-DD")
    parser.add_argument("--reconciliation", help="Private independent review JSON; never auto-generated")
    args = parser.parse_args()
    try:
        with connect(args.database) as db:
            events, kind = load_history(db)
        report = build_report(events, kind, args.period, args.through,
                              read_json(args.reconciliation) if args.reconciliation else None)
        # This output contains market-level personal data: redirect only to private storage.
        print(json.dumps(report, indent=2))
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
        parser.exit(2, f"M14 report rejected ({type(error).__name__}); inspect private inputs.\n")


if __name__ == "__main__":
    main()
