"""Mocked Discord only: no messages leave this suite."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import tempfile
import unittest

from m14_import import connect, import_snapshot, load_history
from m14_performance import build_report
from m14_results_publish import (DeliveryUncertain, confirm_channel, deliver_once, render_results,
                                 send_results, test_webhook as send_connection_test, webhook_identity)
from test_m14_performance import attestation, history
from m14_samples import bundle, fill, settlement

# Nonfunctional synthetic token used exclusively with injected fake HTTP transport.
WEBHOOK = "https://discord.com/api/webhooks/123/SYNTHETIC_TEST_TOKEN"


class Response:
    status = 204
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None


def reconciled_report():
    base = build_report(history(), "live", "daily", "2026-11-02")
    return build_report(history(), "live", "daily", "2026-11-02", attestation(base))


def live_snapshot():
    # All records remain synthetic; the live label exercises the live-only gate.
    data = bundle([fill("synthetic-buy", count=4),
                   fill("synthetic-sell", action="sell", count=1, yes="0.6000", no="0.4000", when="2026-11-02T12:00:00Z")],
                  [settlement(yes_count=3, yes_cost=120, revenue=300, fee="0.06", when="2026-11-03T12:00:00Z")],
                  {"synthetic-buy": "0.04", "synthetic-sell": "0.02"})
    data["data_kind"] = "live"
    return data


def reconciled_store(db, snapshot=None, through="2026-11-02"):
    import_snapshot(db, live_snapshot() if snapshot is None else snapshot)
    events, kind = load_history(db)
    base = build_report(events, kind, "daily", through)
    review = attestation(base)
    return build_report(events, kind, "daily", through, review), review


class ResultsTests(unittest.TestCase):
    def test_private_fields_never_enter_payload(self):
        report = reconciled_report()
        report.update(account_id="SENSITIVE_ACCOUNT", evidence_reference="PRIVATE_STATEMENT")
        report["open_positions"][0]["market_ticker"] = "PRIVATE_MARKET"
        report["metrics"]["profit_by_market_usd"] = {"PRIVATE_MARKET": "10"}
        payload = render_results(report)
        content = json.dumps(payload)
        for value in ("SENSITIVE_ACCOUNT", "PRIVATE_STATEMENT", "PRIVATE_MARKET", report["history_sha256"]):
            self.assertNotIn(value, content)
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertLessEqual(len(payload["content"]), 2000)

    def test_periods_and_labels(self):
        for period in ("daily", "weekly", "cumulative"):
            for kind, label in (("synthetic", "TEST — SYNTHETIC"), ("live", "UNVERIFIED PREVIEW")):
                report = build_report(history(), kind, period, "2026-11-02")
                with self.subTest(period=period, kind=kind):
                    content = render_results(report)["content"]
                    self.assertIn(label, content)
                    self.assertIn(period.title(), content)

    def test_gates_require_real_reconciled_history_and_tested_channel(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            for kind in ("synthetic", "live"):
                report = build_report(history(), kind, "daily", "2026-11-02")
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    send_results(db, report, WEBHOOK, opener=lambda *a, **k: self.fail("HTTP must not run"))
            with self.assertRaises(ValueError):
                send_results(db, reconciled_report(), WEBHOOK)
            with self.assertRaises(ValueError):
                confirm_channel(db, WEBHOOK)

    def test_test_message_contains_no_results_and_channel_confirmation(self):
        calls = []
        def opener(request, timeout):
            calls.append(json.loads(request.data))
            self.assertEqual(timeout, 15)
            return Response()
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            self.assertEqual(send_connection_test(db, WEBHOOK, opener), "delivered")
            self.assertIn("CONNECTION TEST", calls[0]["content"])
            self.assertNotIn("$", calls[0]["content"])
            self.assertEqual(send_connection_test(db, WEBHOOK, opener), "already_delivered")
            confirm_channel(db, WEBHOOK)
            report, review = reconciled_store(db)
            self.assertEqual(send_results(db, report, WEBHOOK, opener, review=review), "delivered")
            self.assertEqual(send_results(db, report, WEBHOOK, opener, review=review), "already_delivered")
            self.assertEqual(len(calls), 2)

    def test_report_correction_does_not_repeat_same_period(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            return Response()
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            send_connection_test(db, WEBHOOK, opener)
            confirm_channel(db, WEBHOOK)
            report, review = reconciled_store(db)
            send_results(db, report, WEBHOOK, opener, review=review)
            snapshot = live_snapshot()
            snapshot["fills_pages"][0]["response"]["fills"].append(fill("additional", ticker="SYNTHETIC-OTHER", when="2026-11-02T13:00:00Z"))
            snapshot["fill_fees"].append({"fill_id": "additional", "fee_usd": "0"})
            changed, changed_review = reconciled_store(db, snapshot)
            self.assertNotEqual(changed["history_sha256"], report["history_sha256"])
            self.assertEqual(send_results(db, changed, WEBHOOK, opener, review=changed_review), "already_delivered")
            self.assertEqual(len(calls), 2)

    def test_unknown_network_outcome_is_not_retried(self):
        calls = []
        def timeout(*args, **kwargs):
            calls.append(1)
            raise TimeoutError("SENSITIVE_URL_SHOULD_NOT_LEAK")
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            with self.assertRaises(DeliveryUncertain) as raised:
                send_connection_test(db, WEBHOOK, timeout)
            self.assertNotIn("SENSITIVE", str(raised.exception))
            self.assertEqual(send_connection_test(db, WEBHOOK, timeout), "blocked_uncertain_delivery")
            self.assertEqual(len(calls), 1)
            with self.assertRaises(ValueError):
                confirm_channel(db, WEBHOOK)

    def test_crash_reservation_blocks_retry(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            with db:
                db.execute("INSERT INTO outbox VALUES ('pending-key', 'hash', 'pending')")
            self.assertEqual(deliver_once(db, "pending-key", {"content": "test"}, WEBHOOK,
                                          lambda *a, **kw: self.fail("No HTTP allowed")), "blocked_uncertain_delivery")

    def test_duplicate_delivery_across_store_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            with connect(path) as db:
                send_connection_test(db, WEBHOOK, lambda *args, **kwargs: Response())
            with connect(path) as db:
                self.assertEqual(send_connection_test(db, WEBHOOK, lambda *a, **kw: self.fail("No second HTTP")), "already_delivered")

    def test_concurrent_publishers_reserve_once(self):
        calls = []
        def opener(*args, **kwargs):
            calls.append(1)
            return Response()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"
            with connect(path):
                pass
            def run(_):
                with connect(path) as db:
                    return send_connection_test(db, WEBHOOK, opener)
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(run, range(2)))
            self.assertEqual(statuses.count("delivered"), 1)
            self.assertEqual(len(calls), 1)

    def test_webhook_and_content_validation(self):
        for url in ("http://discord.com/api/webhooks/123/token", "https://example.com/api/webhooks/123/token",
                    "https://discord.com.evil.test/api/webhooks/123/token", WEBHOOK + "?query=true", ""):
            with self.subTest(url=url), self.assertRaises(ValueError):
                webhook_identity(url)
        report = reconciled_report()
        report["through"] = "@everyone"
        with self.assertRaises(ValueError):
            render_results(report)

    def test_unexpected_status_marks_delivery_uncertain(self):
        class BadResponse(Response):
            status = 429
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            with self.assertRaises(DeliveryUncertain):
                send_connection_test(db, WEBHOOK, lambda *a, **kw: BadResponse())
            self.assertEqual(db.execute("SELECT state FROM outbox").fetchone()[0], "uncertain")
