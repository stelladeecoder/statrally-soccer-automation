"""Synthetic Issues/ESPN data and mocked Discord; never real outcomes."""
import copy
from datetime import datetime, timezone
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from m13_beta_grade_issues import BOT, DELIVERED, delivered_record, run
from m13_beta_signals import signal_identity, signal_proof
from test_m13_beta_grading import SIGNAL, fixture

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def paper_record():
    signal = dict(SIGNAL, fixture_verified=True, quote_verified=True,
                  market_ticker="SYNTHETIC-MARKET", observed_at_utc="2026-11-02T17:59:59Z")
    identity = signal_identity(signal)
    issue = {"number": 7, "user": {"login": BOT}, "created_at": "2026-11-02T18:00:00Z",
             "body": "statrally-beta-id:" + identity + "\nstatrally-beta-data:" + json.dumps(signal)}
    proof = {"id": 1, "user": {"login": BOT}, "created_at": "2026-11-02T18:00:02Z",
             "updated_at": "2026-11-02T18:00:02Z",
             "body": DELIVERED + "\nstatrally-beta-delivery-proof:" + signal_proof(signal)}
    return issue, proof, signal


class FakeAPI:
    def __init__(self):
        issue, proof, self.signal = paper_record()
        self.issues, self.comments, self.writes = [issue], [proof], []
    def __call__(self, method, path, token, data=None):
        if method == "GET":
            page = int(path.rsplit("page=", 1)[1])
            rows = self.comments if "/comments?" in path else self.issues
            return copy.deepcopy(rows[(page - 1)*100:page*100])
        self.writes.append((method, path, data))
        if method == "POST" and "/comments" in path:
            item = {"id": len(self.comments)+1, "user": {"login": BOT}, "body": data["body"],
                    "created_at": NOW.isoformat(), "updated_at": NOW.isoformat()}
            self.comments.append(item)
            return item
        if method == "POST":
            item = {"number": 88, "user": {"login": BOT}, **data}
            self.issues.append(item)
            return item
        return {}


class IssueGradingTests(unittest.TestCase):
    def test_test_only_record_never_enters_official_performance(self):
        issue, proof, _=paper_record()
        issue["body"]="statrally-test-only\n"+issue["body"]
        self.assertIsNone(delivered_record(issue,[proof]))

    def test_duplicate_delivered_record_is_counted_only_once(self):
        api=FakeAPI()
        api.issues.append(dict(api.issues[0],number=8))
        with patch("m13_beta_grade_issues.github",side_effect=api),patch("m13_beta_grade_issues.fetch_scoreboard",return_value=fixture()),patch("m13_beta_grade_issues.publish") as send:
            report=run("owner/repo","token",now=NOW,webhook="synthetic-webhook")
        self.assertEqual(report["snapshot"]["graded"],1)
        self.assertEqual(report["checks"]["duplicate_records"],1)
        send.assert_called_once()
    def setUp(self):
        # Synthetic accuracy figures must not look like live deployment output.
        output=redirect_stdout(StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__,None,None,None)
    def test_grade_persist_reserve_deliver_confirm_then_skip_repeat(self):
        api = FakeAPI()
        events = []
        def send(payload, webhook):
            self.assertTrue(any(c["body"].startswith("statrally-beta-results-reserved:") for c in api.comments))
            events.append(payload)
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard", return_value=fixture()), patch("m13_beta_grade_issues.publish", side_effect=send):
            first = run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
            second = run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        self.assertEqual(first["checks"]["results_delivered"], 1)
        self.assertEqual(second["checks"]["already_reserved"], 1)
        self.assertEqual(second["snapshot"]["wins"], 1)
        self.assertEqual(len(events), 1)
        self.assertIn("BETA PAPER RESULT", events[0]["content"])
        self.assertIn("No financial P&L", events[0]["content"])
        dashboard = next(i for i in api.issues if i.get("number") == 88)
        self.assertIn("\n", dashboard["body"])
        self.assertNotIn("\\n", dashboard["body"])
        self.assertTrue(any(c["body"].startswith("statrally-beta-results-delivered:") for c in api.comments))

    def test_delivery_error_fails_and_reservation_blocks_retry(self):
        api = FakeAPI()
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard", return_value=fixture()), patch("m13_beta_grade_issues.publish", side_effect=OSError("uncertain")) as send:
            with self.assertRaises(OSError):
                run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
            with self.assertRaisesRegex(RuntimeError, "no automatic resend"):
                run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
            send.assert_called_once()
        self.assertTrue(any(c["body"].startswith("statrally-beta-results-reserved:") for c in api.comments))
        self.assertFalse(any(c["body"].startswith("statrally-beta-results-delivered:") for c in api.comments))

    def test_pending_game_is_counted_but_never_posted_as_a_result(self):
        api = FakeAPI()
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard", return_value=fixture(complete=False)), patch("m13_beta_grade_issues.publish") as send:
            report = run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        self.assertEqual(report["snapshot"]["pending"], 1)
        self.assertEqual(report["snapshot"]["graded"], 0)
        send.assert_not_called()

    def test_upcoming_delivered_game_is_pending_without_fetch(self):
        api = FakeAPI()
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard") as fetch, patch("m13_beta_grade_issues.publish") as send:
            report = run("owner/repo", "token", now=datetime(2026, 11, 2, 19, tzinfo=timezone.utc), webhook="synthetic-webhook")
        self.assertEqual(report["snapshot"]["pending"], 1)
        fetch.assert_not_called()
        send.assert_not_called()

    def test_public_user_cannot_spoof_the_delivery_receipt(self):
        issue, proof, signal = paper_record()
        for target in ("issue", "comment"):
            changed_issue, changed_comment = copy.deepcopy(issue), copy.deepcopy(proof)
            (changed_issue if target == "issue" else changed_comment)["user"]["login"] = "untrusted-user"
            self.assertIsNone(delivered_record(changed_issue, [changed_comment]))

    def test_postgame_signal_edit_cannot_become_a_new_prediction(self):
        issue, proof, signal = paper_record()
        signal["side"] = "NO"
        signal["model_probability"] = "0.99"
        issue["body"] = "statrally-beta-id:" + signal_identity(signal) + "\nstatrally-beta-data:" + json.dumps(signal)
        self.assertIsNone(delivered_record(issue, [proof]))

    def test_postgame_delivery_proof_edit_is_not_valid(self):
        issue, proof, signal = paper_record()
        proof["updated_at"] = "2026-11-03T12:00:00Z"
        self.assertIsNone(delivered_record(issue, [proof]))
        proof["updated_at"] = proof["created_at"]
        proof["created_at"] = "2026-11-03T12:00:00Z"
        self.assertIsNone(delivered_record(issue, [proof]))

    def test_missing_old_unbound_receipt_does_not_certify_a_signal(self):
        issue, proof, _ = paper_record()
        proof["body"] = DELIVERED
        self.assertIsNone(delivered_record(issue, [proof]))

    def test_comment_pagination_finds_valid_proof_after_first_page(self):
        api = FakeAPI()
        api.comments = [{"body": "unrelated", "user": {"login": "someone"}} for _ in range(100)] + api.comments
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard", return_value=fixture()), patch("m13_beta_grade_issues.publish") as send:
            run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        send.assert_called_once()

    def test_source_failure_remains_pending_and_does_not_erase_dashboard(self):
        api = FakeAPI()
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard", side_effect=OSError("unavailable")), patch("m13_beta_grade_issues.publish") as send:
            with self.assertRaisesRegex(RuntimeError, "previous dashboard retained"):
                run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        self.assertEqual(api.writes, [])
        send.assert_not_called()

    def test_conflicting_previously_recorded_grade_is_not_overwritten(self):
        api = FakeAPI()
        api.comments.append({"user": {"login": BOT}, "body": "statrally-beta-grade:" + signal_identity(api.signal) + "\nPaper outcome: **LOSS** | Final 0-0 | No trade."})
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.fetch_scoreboard", return_value=fixture()), patch("m13_beta_grade_issues.publish") as send:
            with self.assertRaisesRegex(RuntimeError, "differs"):
                run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        send.assert_not_called()

    def test_comment_reservation_must_be_confirmed_before_discord(self):
        api = FakeAPI()
        def unconfirmed(method, path, token, data=None):
            if method == "POST" and data["body"].startswith("statrally-beta-results-reserved:"):
                return {}
            return api(method, path, token, data)
        with patch("m13_beta_grade_issues.github", side_effect=unconfirmed), patch("m13_beta_grade_issues.fetch_scoreboard", return_value=fixture()), patch("m13_beta_grade_issues.publish") as send:
            with self.assertRaisesRegex(RuntimeError, "not confirmed"):
                run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        send.assert_not_called()

    def test_no_paper_records_creates_no_outcomes_or_dashboard(self):
        api = FakeAPI()
        api.issues = []
        with patch("m13_beta_grade_issues.github", side_effect=api), patch("m13_beta_grade_issues.publish") as send:
            report = run("owner/repo", "token", now=NOW, webhook="synthetic-webhook")
        self.assertEqual(report["snapshot"]["graded"], 0)
        self.assertEqual(api.writes, [])
        send.assert_not_called()
