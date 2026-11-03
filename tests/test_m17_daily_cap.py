"""Daily maximum is shared by all scheduled paper-pick checks (Central time)."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import m13_beta_dispatch as dispatch


class DailyCapTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 3, 16, 0, tzinfo=timezone.utc)

    def signal(self, identifier):
        return dict(market_ticker="market-" + str(identifier), side="YES",
                    kickoff_utc="2026-11-03T22:00:00+00:00",
                    espn_event_id=str(identifier), league="epl",
                    observed_at_utc="2026-11-03T15:59:59+00:00")

    def issue(self, identifier, *, kickoff=None, user="github-actions[bot]"):
        s = self.signal(identifier)
        if kickoff is not None:
            s["kickoff_utc"] = kickoff
        import json
        return {"user": {"login": user},
                "body": "StatRally beta paper signal\nstatrally-beta-data:"
                        + json.dumps(s, separators=(",", ":"))}

    def test_counts_reserved_and_unconfirmed_deliveries(self):
        self.assertEqual(dispatch.reserved_today([self.issue(1), self.issue(2)], now=self.now), 2)

    def test_other_day_not_counted(self):
        other = self.issue(1, kickoff="2026-11-04T16:00:00+00:00")
        self.assertEqual(dispatch.reserved_today([other], now=self.now), 0)

    def test_central_day_not_utc_day(self):
        late = self.issue(1, kickoff="2026-11-04T03:00:00+00:00")
        self.assertEqual(dispatch.reserved_today([late], now=self.now), 1)

    def test_non_bot_and_pull_requests_not_counted(self):
        bad = self.issue(1, user="untrusted")
        pull = self.issue(2)
        pull["pull_request"] = {"url": "example"}
        self.assertEqual(dispatch.reserved_today([bad, pull], now=self.now), 0)

    def test_malformed_saved_reservation_fails_closed(self):
        bad = {"user": {"login": "github-actions[bot]"},
               "body": "statrally-beta-data:{broken"}
        with self.assertRaises(RuntimeError):
            dispatch.reserved_today([bad], now=self.now)

    def test_existing_two_allow_only_one_more(self):
        saved = [self.issue(1), self.issue(2)]
        calls = []
        def api(method, path, token, data=None):
            if method == "GET":
                return saved
            if method == "POST" and path.endswith("/issues"):
                calls.append(("reserve", data))
                return {"number": 90}
            if method == "POST" and path.endswith("/comments"):
                return {"id": 2}
            raise AssertionError((method, path))
        envelope = {"schema_version": 1, "status": "experimental_paper",
                    "trades_placed": 0, "signals": [self.signal(3), self.signal(4), self.signal(5)]}
        with patch.object(dispatch, "github", side_effect=api), \
             patch.object(dispatch, "render_beta", return_value={"content": "mock"}), \
             patch.object(dispatch, "publish") as publish:
            n = dispatch.process(envelope, "owner/repo", "fake", "fake", now=self.now)
        self.assertEqual(n, 1)
        self.assertEqual(len(calls), 1)
        publish.assert_called_once()

    def test_three_existing_prevent_new_posts(self):
        saved = [self.issue(1), self.issue(2), self.issue(3)]
        envelope = {"schema_version": 1, "status": "experimental_paper",
                    "trades_placed": 0, "signals": [self.signal(4)]}
        with patch.object(dispatch, "github", return_value=saved), \
             patch.object(dispatch, "render_beta", return_value={"content": "mock"}), \
             patch.object(dispatch, "publish") as publish:
            n = dispatch.process(envelope, "owner/repo", "fake", "fake", now=self.now)
        self.assertEqual(n, 0)
        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
