"""Audit regressions; all input records are synthetic and HTTP is mocked."""
import copy
from decimal import Inexact, ROUND_UP, localcontext
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from m14_import import canonical, connect, import_snapshot, load_history, normalize_snapshot
from m14_performance import build_report
from m14_position_ledger import summarize
from m14_results_publish import (confirm_channel, dollars, percent, render_results, report_key,
                                 send_results, test_webhook as connection_test)
from m14_samples import bundle, event, fill, settlement
from test_m14_performance import history
from test_m14_results_publish import WEBHOOK, Response, live_snapshot, reconciled_store


class FinalVerificationTests(unittest.TestCase):
    def prepare(self, db):
        report, review = reconciled_store(db)
        connection_test(db, WEBHOOK, lambda *a, **kw: Response())
        confirm_channel(db, WEBHOOK)
        return report, review

    def never_send(self, *args, **kwargs):
        self.fail("Rejected input must never reach Discord")

    def test_accounting_is_independent_of_callers_decimal_context(self):
        events = [event("buy", "BUY", 3, "0.4", "2026-11-01T12:00:00Z", "0.01"),
                  event("sell", "SELL", 1, "0.6", "2026-11-02T12:00:00Z")]
        snapshot = bundle([fill()], [settlement()])
        expected_ledger = summarize(events)
        expected_report = build_report(events, "synthetic", "daily", "2026-11-02")
        expected_import = normalize_snapshot(snapshot)
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_UP
            context.traps[Inexact] = True
            self.assertEqual(summarize(events), expected_ledger)
            self.assertEqual(build_report(events, "synthetic", "daily", "2026-11-02"), expected_report)
            self.assertEqual(normalize_snapshot(snapshot), expected_import)
            self.assertEqual(dollars("123456789012345678.005"), "123456789012345678.01")
            self.assertEqual(percent("0.01005"), "1.01%")

    def test_equivalent_dates_produce_identical_reports_and_receipt_keys(self):
        expected = build_report(history(), "synthetic", "daily", "2026-11-02")
        for value in ("20261102", "2026-W45-1"):
            with self.subTest(value=value):
                report = build_report(history(), "synthetic", "daily", value)
                self.assertEqual(report, expected)
                alias = dict(expected, through=value)
                self.assertEqual(report_key(alias, "destination"), report_key(expected, "destination"))

    def test_alternate_date_cannot_duplicate_delivery(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            return Response()
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            report, review = self.prepare(db)
            self.assertEqual(send_results(db, report, WEBHOOK, opener, review=review), "delivered")
            alias, alias_review = reconciled_store(db, through="20261102")
            self.assertEqual(send_results(db, alias, WEBHOOK, opener, review=alias_review), "already_delivered")
            self.assertEqual(calls, [1])

    def test_report_flags_alone_cannot_authorize_delivery(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            report, review = self.prepare(db)
            with self.assertRaises(ValueError):
                send_results(db, report, WEBHOOK, self.never_send)
            changed = copy.deepcopy(report)
            changed["metrics"]["realized_net_pnl_usd"] = "999.99"
            with self.assertRaises(ValueError):
                send_results(db, changed, WEBHOOK, self.never_send, review=review)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_private_text_cannot_be_inserted_through_report_counts(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            report, review = self.prepare(db)
            for field in ("completed_positions", "wins", "losses", "breakeven", "early_exit_contracts"):
                forged = copy.deepcopy(report)
                forged["metrics"][field] = "PRIVATE_ACCOUNT_IDENTIFIER"
                with self.subTest(field=field), self.assertRaises(ValueError):
                    send_results(db, forged, WEBHOOK, self.never_send, review=review)

    def test_stale_report_rejected_after_history_import_changes(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            report, review = self.prepare(db)
            changed = live_snapshot()
            changed["fills_pages"][0]["response"]["fills"].append(fill("additional", ticker="SYNTHETIC-OTHER", when="2026-11-02T13:00:00Z"))
            changed["fill_fees"].append({"fill_id": "additional", "fee_usd": "0"})
            import_snapshot(db, changed)
            with self.assertRaises(ValueError):
                send_results(db, report, WEBHOOK, self.never_send, review=review)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0], 1)

    def test_stored_event_mutation_rejected_against_raw_sources(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            report, review = self.prepare(db)
            key, record = db.execute("SELECT event_id,record FROM events WHERE source_id='fill:synthetic-buy'").fetchone()
            altered = json.loads(record)
            altered["price"] = "0.3"
            with db:
                db.execute("UPDATE events SET record=? WHERE event_id=?", (canonical(altered), key))
            with self.assertRaises(ValueError):
                load_history(db)
            with self.assertRaises(ValueError):
                send_results(db, report, WEBHOOK, self.never_send, review=review)

    def test_missing_event_and_mismatched_source_reference_rejected(self):
        for mutation in ("DELETE FROM events WHERE source_id='fill:synthetic-buy'",
                         "UPDATE events SET source_id='fee:synthetic-buy' WHERE source_id='fill:synthetic-buy'"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
                reconciled_store(db)
                with db:
                    db.execute(mutation)
                with self.assertRaises(ValueError):
                    load_history(db)

    def test_unreviewed_source_fields_are_not_silently_ignored(self):
        for name in ("fills", "settlements"):
            snapshot = bundle([fill()], [settlement()])
            snapshot[name + "_pages"][0]["response"][name][0]["unreviewed_financial_extension"] = "2.5"
            with self.subTest(name=name), self.assertRaises(ValueError):
                normalize_snapshot(snapshot)

    def test_reconciliation_and_reservation_hold_the_same_write_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            with connect(path) as db:
                report, review = self.prepare(db)
                def under_lock(*args, **kwargs):
                    with sqlite3.connect(path, timeout=0) as other:
                        with self.assertRaises(sqlite3.OperationalError):
                            other.execute("BEGIN IMMEDIATE")
                    return build_report(*args, **kwargs)
                with patch("m14_results_publish.build_report", side_effect=under_lock):
                    self.assertEqual(send_results(db, report, WEBHOOK, lambda *a, **kw: Response(), review=review), "delivered")
