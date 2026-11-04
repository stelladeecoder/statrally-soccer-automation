import unittest
from io import BytesIO
from urllib.error import HTTPError
from datetime import datetime
from m16_scheduler import due_slots, plan, complete, checkpoints, MARKER, resume_dispatch


class SchedulerTests(unittest.TestCase):
    def test_central_slots_across_dst(self):
        for stamp in ["2026-07-03T09:17:00+00:00", "2026-11-03T10:17:00+00:00"]:
            slots = due_slots(datetime.fromisoformat(stamp))
            self.assertIn("T04:17:00", slots["watchlist"])
            self.assertEqual(slots["picks"], "")

    def test_late_trigger_catches_up_latest_pick_slot(self):
        slots = due_slots(datetime.fromisoformat("2026-11-03T15:00:00-06:00"))
        self.assertEqual(slots["picks"], "2026-11-03T14:23:00-06:00")

    def test_midnight_never_posts_yesterdays_watchlist_or_picks(self):
        slots = due_slots(datetime.fromisoformat("2026-11-04T00:10:00-06:00"))
        self.assertEqual(slots["watchlist"], "")
        self.assertEqual(slots["picks"], "")
        self.assertEqual(slots["grading"], "2026-11-03T23:55:00-06:00")

    def test_completed_slot_is_skipped_but_next_slot_runs(self):
        saved = {"picks": {"completed_slot": "2026-11-03T05:23:00-06:00"}}
        self.assertEqual(plan(datetime.fromisoformat("2026-11-03T06:00:00-06:00"), saved)["picks"], "")
        self.assertIn("T08:23:00", plan(datetime.fromisoformat("2026-11-03T08:24:00-06:00"), saved)["picks"])

    def test_failures_do_not_mark_slots_complete(self):
        calls = []
        def fake(method, path, data=None):
            calls.append(method)
            return [] if method == "GET" else {"number": 1, "id": 5}
        slots = {"picks": "2026-11-03T05:23:00-06:00"}
        complete("owner/repo", slots, {"picks": "failure"}, "run", fake)
        self.assertEqual(calls, ["GET"])
        complete("owner/repo", slots, {"picks": "success"}, "run", fake)
        self.assertEqual(calls[-1], "POST")

    def test_ambiguous_history_fails_closed(self):
        def fake(*args):
            return {"error": "unavailable"}
        with self.assertRaises(RuntimeError):
            checkpoints("owner/repo", fake)

    def test_dispatch_retries_transient_github_500(self):
        attempts, delays = [], []
        def fake(method, path, data=None):
            attempts.append((method, path, data))
            if len(attempts) == 1:
                raise HTTPError("https://api.github.com", 500, "Internal error", {}, BytesIO())
        resume_dispatch("owner/repo", call=fake, sleeper=delays.append)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(delays, [2])
        self.assertEqual(attempts[-1][2], {"ref": "main"})

    def test_dispatch_does_not_retry_permission_errors(self):
        attempts, delays = [], []
        def fake(method, path, data=None):
            attempts.append(method)
            raise HTTPError("https://api.github.com", 403, "Forbidden", {}, BytesIO())
        with self.assertRaises(HTTPError):
            resume_dispatch("owner/repo", call=fake, sleeper=delays.append)
        self.assertEqual(attempts, ["POST"])
        self.assertEqual(delays, [])

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            due_slots(datetime(2026, 11, 3))


if __name__ == "__main__":
    unittest.main()
