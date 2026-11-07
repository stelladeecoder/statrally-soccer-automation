"""Synthetic tests; never sends messages to Discord or writes real GitHub issues."""
import copy
from datetime import datetime, timedelta, timezone
import unittest

from prediction_ledger import Ledger, GRADE, DELIVERY
from daily_results import report, performance, result_embed, publish_report
from test_prediction_platform import FakeGitHub, prediction, slate, NOW, REPO


class DailyResultsTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeGitHub()
        self.ledger = Ledger(REPO, "synthetic-token", call=self.api).load()
        data = slate(5)
        data['fixtures'][3] = prediction(4, p_yes='0.70')
        data['fixtures'][4] = prediction(5, p_yes='0.70')
        self.ledger.issue_slate(data, now=NOW)
        self.day = "2026-11-05"
        self.sent = []
        self.edited = []

    def grade(self, index, correct=True):
        row = self.ledger.forecasts[index]
        p = row["prediction"]
        self.ledger.append(row["issue_number"], GRADE, {
            "prediction_id": p["prediction_id"], "status": "graded",
            "correct": correct, "result": "WIN" if correct else "LOSS"})

    def top(self, index):
        row = self.ledger.forecasts[index]
        self.ledger.append(row["issue_number"], DELIVERY, {
            "prediction_id": row["prediction"]["prediction_id"], "kind": "top", "state": "reserved"})

    def send(self, payload, webhook, **kwargs):
        self.assertTrue(kwargs["wait"])
        self.sent.append(copy.deepcopy(payload))
        return {"message_id": "11111", "channel_id": "22222"}

    def edit(self, payload, webhook, receipt):
        self.edited.append(copy.deepcopy(payload))
        self.assertEqual(receipt["message_id"], "11111")

    def test_no_data_and_zero_denominator(self):
        self.assertIsNone(report(self.ledger, "2026-11-04"))
        p = report(self.ledger, self.day)
        self.assertEqual(p["overall"]["ALL"]["pending"], 5)
        self.assertEqual(p["overall"]["ALL"]["accuracy"], None)
        self.assertIn("N/A", result_embed(p)["embeds"][0]["fields"][0]["value"])
        self.assertEqual(publish_report(self.ledger, self.day, "fake", sender=self.send), "no_verified_results")
        self.assertEqual(self.sent, [])

    def test_correct_incorrect_yes_no_top_and_pending(self):
        # First two NO calls correct, third NO wrong, fourth YES correct, fifth pending.
        for i in range(3):
            self.grade(i, correct=i != 2)
        self.grade(3)
        for i in (0, 2, 3):
            self.top(i)
        p = report(self.ledger, self.day)
        self.assertEqual(p["overall"]["NO"]["correct"], 2)
        self.assertEqual(p["overall"]["NO"]["incorrect"], 1)
        self.assertEqual(p["overall"]["YES"]["correct"], 1)
        self.assertEqual(p["overall"]["YES"]["pending"], 1)
        self.assertEqual(p["overall"]["ALL"]["accuracy"], 75)
        self.assertEqual(p["top_total"], 3)
        self.assertEqual(p["top"]["correct"], 2)
        self.assertEqual(p["top"]["incorrect"], 1)
        self.assertEqual(result_embed(p)["embeds"][0]["color"], 0x3498DB)

    def test_once_then_update_existing_message_without_reposting(self):
        self.grade(0)
        self.top(0)
        result = publish_report(self.ledger, self.day, "fake", sender=self.send, editor=self.edit)
        self.assertEqual(result, "posted")
        self.assertEqual(publish_report(self.ledger, self.day, "fake", sender=self.send, editor=self.edit), "unchanged")
        self.grade(1, correct=False)
        self.assertEqual(publish_report(self.ledger, self.day, "fake", sender=self.send, editor=self.edit), "updated")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.edited), 1)
        self.assertEqual(publish_report(self.ledger, self.day, "fake", sender=self.send, editor=self.edit), "unchanged")

    def test_failed_delivery_reservation_blocks_retries(self):
        self.grade(0)
        def broken(*args, **kwargs):
            raise TimeoutError("Ambiguous Discord delivery")
        with self.assertRaises(TimeoutError):
            publish_report(self.ledger, self.day, "fake", sender=broken)
        with self.assertRaisesRegex(RuntimeError, "Unresolved daily report reservation"):
            publish_report(self.ledger, self.day, "fake", sender=self.send)
        self.assertEqual(self.sent, [])

    def test_failed_edit_cannot_be_retried_blindly(self):
        self.grade(0)
        publish_report(self.ledger, self.day, "fake", sender=self.send)
        self.grade(1)
        def broken(*args):
            raise TimeoutError("Ambiguous edit")
        with self.assertRaises(TimeoutError):
            publish_report(self.ledger, self.day, "fake", sender=self.send, editor=broken)
        with self.assertRaisesRegex(RuntimeError, "Unresolved daily edit"):
            publish_report(self.ledger, self.day, "fake", sender=self.send, editor=self.edit)

    def test_revision_is_not_counted_twice(self):
        self.grade(0)
        # A second revision with the same fixture must not inflate the original score.
        row = self.ledger.forecasts[0]
        copy_row = copy.deepcopy(row)
        copy_row["prediction"]["prediction_id"] = "later-version-synthetic"
        copy_row["prediction"]["revision"] = 2
        copy_row["comment_id"] = 99999
        copy_row["issued_at"] = (NOW + timedelta(minutes=2)).isoformat()
        self.ledger.forecasts.append(copy_row)
        p = report(self.ledger, self.day)
        self.assertEqual(p["total"], 5)
        self.assertEqual(p["overall"]["ALL"]["graded"], 1)

    def test_daylight_saving_boundary_uses_central_kickoff(self):
        from daily_results import rows_for_day
        self.ledger.forecasts[0]["prediction"]["kickoff_utc"] = "2026-11-01T05:30:00Z"
        self.assertEqual(len(rows_for_day(self.ledger, datetime(2026, 10, 31).date())), 1)


if __name__ == "__main__":
    unittest.main()
