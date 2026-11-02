"""Dedicated #btts-results dry-run/report publisher with a durable outbox.

No scheduler is enabled. A result requires independent local reconciliation,
then a tested webhook and explicit confirmation of its destination channel.
"""
import argparse
from datetime import date
from decimal import Context, Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import os
import re
import sqlite3
from urllib.request import Request, urlopen

from m14_import import CURRENT_SCHEMA, canonical, connect, digest, load_history, read_json
from m14_performance import build_report
from m14_position_ledger import contracts, money, timestamp


class DeliveryUncertain(RuntimeError):
    """Do not retry until the operator checks the channel/outbox."""


def dollars(value):
    with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
        return format(money(value).quantize(Decimal("0.01")), ".2f")


def percent(value):
    with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
        return "N/A" if value is None else format((money(value) * 100).quantize(Decimal("0.01")), ".2f") + "%"


def render_results(report):
    # Only selected aggregate fields enter Discord; never copy arbitrary source text,
    # account IDs, tickers, evidence references, database paths or history hashes.
    kind = report.get("data_kind")
    if kind not in ("live", "synthetic") or report.get("schema_version") != 1:
        raise ValueError("M14 report required")
    period = report.get("period")
    if period not in ("daily", "weekly", "cumulative"):
        raise ValueError("Invalid results period")
    through = date.fromisoformat(report["through"]).isoformat()
    verified = kind == "live" and report.get("verification") == "operator_reconciled"
    label = "RECONCILED RESULTS" if verified else "TEST — SYNTHETIC" if kind == "synthetic" else "UNVERIFIED PREVIEW — DO NOT PUBLISH"
    metrics = report["metrics"]
    cumulative = report["cumulative"]
    for field in ("completed_positions", "wins", "losses", "breakeven"):
        if type(metrics.get(field)) is not int or metrics[field] < 0:
            raise ValueError("Nonnegative numeric report counts required")
    contracts(metrics.get("early_exit_contracts"), zero=True)
    lines = [f"**StatRally | {label}**", f"{period.title()} through {through} (America/Chicago)",
             f"Realized net P&L: ${dollars(metrics['realized_net_pnl_usd'])}",
             f"Fees paid in period: ${dollars(metrics['fees_paid_usd'])}",
             f"ROI on closed entry cost including entry fees: {percent(metrics['roi'])}",
             f"Completed positions: {metrics['completed_positions']} | wins {metrics['wins']} | losses {metrics['losses']} | breakeven {metrics['breakeven']}",
             f"Win rate: {percent(metrics['win_rate'])} | loss rate: {percent(metrics['loss_rate'])}",
             f"Open positions at cutoff: {len(report['open_positions'])} (excluded from completed win/loss counts)",
             f"Early exit contracts: {metrics['early_exit_contracts']} | realized P&L ${dollars(metrics['early_exit_realized_pnl_usd'])}",
             f"Cumulative realized net P&L: ${dollars(cumulative['realized_net_pnl_usd'])}",
             "No unrealized P&L or model backtest returns included."]
    payload = {"content": "\n".join(lines), "allowed_mentions": {"parse": []}}
    if len(payload["content"]) > 2000:
        raise ValueError("Report exceeds Discord content limit")
    return payload


def webhook_identity(webhook):
    if not isinstance(webhook, str) or not re.fullmatch(r"https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+", webhook):
        raise ValueError("Dedicated Discord results webhook required")
    return hashlib.sha256(webhook.encode()).hexdigest()


def report_key(report, destination):
    # One report per destination/period/cutoff, even if history is later corrected.
    return digest([destination, "live", report["period"], date.fromisoformat(report["through"]).isoformat()])


def deliver_once(db, key, payload, webhook, opener=urlopen, *, validate=None):
    webhook_identity(webhook)
    serialized = canonical(payload)
    with db:
        db.execute("BEGIN IMMEDIATE")
        if validate is not None:
            validate()
        existing = db.execute("SELECT state FROM outbox WHERE report_key=?", (key,)).fetchone()
        if existing:
            return "already_delivered" if existing[0] == "delivered" else "blocked_uncertain_delivery"
        db.execute("INSERT INTO outbox VALUES (?,?, 'pending')", (key, digest(payload)))
    # Commit reservation BEFORE HTTP. A crash leaves pending, never auto-retried.
    request = Request(webhook, data=serialized.encode(),
                      headers={"Content-Type": "application/json", "User-Agent": "StatRally-M14/0.1"}, method="POST")
    try:
        with opener(request, timeout=15) as response:
            if response.status not in (200, 204):
                raise DeliveryUncertain("Unexpected Discord response")
    except Exception:
        with db:
            db.execute("UPDATE outbox SET state='uncertain' WHERE report_key=?", (key,))
        raise DeliveryUncertain("Delivery outcome uncertain; check the results channel before any manual recovery") from None
    with db:
        db.execute("UPDATE outbox SET state='delivered' WHERE report_key=?", (key,))
    return "delivered"


def send_results(db, report, webhook, opener=urlopen, *, review=None):
    if report.get("data_kind") != "live" or report.get("verification") != "operator_reconciled":
        raise ValueError("Only independently reconciled live results can be sent")
    if review is None:
        raise ValueError("Independent reconciliation evidence required at send time")
    destination = webhook_identity(webhook)
    def validate():
        # Source/event integrity, review, history and payload are checked while
        # holding the SAME write lock as the durable reservation. Never trust
        # caller-supplied verification flags or stale report metrics.
        events, kind = load_history(db)
        schema = db.execute("SELECT value FROM metadata WHERE key='input_schema'").fetchone()
        if not schema or schema[0] != CURRENT_SCHEMA:
            raise ValueError("Legacy SDK histories cannot authorize current live results")
        snapshot = db.execute("SELECT record FROM rest_snapshots WHERE snapshot_hash=(SELECT value FROM metadata WHERE key='current_snapshot')").fetchone()
        if not snapshot or timestamp(report["cutoff_exclusive"]) > timestamp(json.loads(snapshot[0])["captured_at"]):
            raise ValueError("Report cutoff exceeds captured source history")
        current = build_report(events, kind, report["period"], report["through"], review)
        if current["verification"] != "operator_reconciled" or canonical(current) != canonical(report):
            raise ValueError("Report changed or does not match reconciled stored history")
        confirmed = db.execute("SELECT value FROM metadata WHERE key=?", ("results_channel:" + destination,)).fetchone()
        if not confirmed or confirmed[0] != "confirmed":
            raise ValueError("Test webhook and confirm #btts-results destination first")
    return deliver_once(db, report_key(report, destination), render_results(report), webhook, opener, validate=validate)


def test_webhook(db, webhook, opener=urlopen):
    destination = webhook_identity(webhook)
    return deliver_once(db, "test:" + destination,
                        {"content": "**StatRally M14 RESULTS CONNECTION TEST**\nTest message only. No financial results, predictions or trades.",
                         "allowed_mentions": {"parse": []}}, webhook, opener)


def confirm_channel(db, webhook):
    destination = webhook_identity(webhook)
    test = db.execute("SELECT state FROM outbox WHERE report_key=?", ("test:" + destination,)).fetchone()
    if not test or test[0] != "delivered":
        raise ValueError("Successful connection test required before channel confirmation")
    with db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES (?, 'confirmed')", ("results_channel:" + destination,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--period", choices=("daily", "weekly", "cumulative"), default="daily")
    parser.add_argument("--through")
    parser.add_argument("--reconciliation")
    parser.add_argument("--send", action="store_true", help="Explicitly enable delivery to the dedicated results webhook")
    special = parser.add_mutually_exclusive_group()
    special.add_argument("--test-message", action="store_true", help="Connection test only; requires --send")
    special.add_argument("--confirm-results-channel", action="store_true", help="Operator visually confirmed test in #btts-results")
    args = parser.parse_args()
    try:
        with connect(args.database) as db:
            if args.test_message or args.confirm_results_channel:
                webhook = os.environ.get("STATRALLY_RESULTS_DISCORD_WEBHOOK", "")
                if args.test_message:
                    if not args.send:
                        raise ValueError("Connection test requires explicit --send")
                    status = test_webhook(db, webhook)
                else:
                    if args.send:
                        raise ValueError("Channel confirmation is a local operation")
                    confirm_channel(db, webhook)
                    status = "results_channel_confirmed"
                print(canonical({"status": status}))
                if status == "blocked_uncertain_delivery":
                    parser.exit(2, "M14 test delivery blocked; operator review required.\n")
                return
            if not args.through:
                raise ValueError("Report cutoff required")
            events, kind = load_history(db)
            review = read_json(args.reconciliation) if args.reconciliation else None
            report = build_report(events, kind, args.period, args.through, review)
            if not args.send:
                print(canonical({"status": "dry_run", "payload": render_results(report)}))
                return
            status = send_results(db, report, os.environ.get("STATRALLY_RESULTS_DISCORD_WEBHOOK", ""), review=review)
            print(canonical({"status": status}))
            if status == "blocked_uncertain_delivery":
                parser.exit(2, "M14 delivery blocked; operator review required.\n")
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError, DeliveryUncertain) as error:
        parser.exit(2, f"M14 results rejected ({type(error).__name__}); inspect private state and documentation.\n")


if __name__ == "__main__":
    main()
