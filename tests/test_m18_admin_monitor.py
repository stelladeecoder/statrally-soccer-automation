"""Regression tests for the private alert monitor. No live calls or messages."""
import unittest
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo
from m18_admin_monitor import due_slots, alert, failure, watch, CENTRAL, expected_windows, window_status_lines, completed_window_audit, delivery_counts


class TestAdminMonitor(unittest.TestCase):
    def test_central_due_slots_and_grading_previous_night(self):
        now = datetime(2026, 11, 3, 14, 50, tzinfo=timezone.utc)
        due = {(kind, slot.strftime("%H:%M")) for kind, slot in due_slots(now)}
        self.assertIn(("watchlist", "04:17"), due)
        self.assertIn(("picks", "08:23"), due)
        self.assertNotIn(("picks", "14:23"), due)
        self.assertIn(("grading", "23:55"), due)

    def test_dst_timezone(self):
        local = datetime(2026, 6, 3, 8, 50, tzinfo=CENTRAL)
        due = [slot for kind, slot in due_slots(local) if kind == "picks"]
        self.assertEqual(due[-1].utcoffset(), timedelta(hours=-5))

    def test_no_duplicate_notifications(self):
        now = datetime(2026, 11, 3, 16, tzinfo=timezone.utc)
        data = {"alerts": {}, "report_day": ""}
        saved, delivered = [], []
        fake = lambda method, repo, path, payload: (saved.append(payload) or {"number": 99})
        sender = lambda webhook, message: delivered.append(message)
        for _ in range(2):
            alert("owner/repo", 99, data, "slot:picks:test", "An alert", "stub",
                  now=now, call=fake, sender=sender)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(len(saved), 1)

    def test_successful_workflow_silent(self):
        delivered = []
        def fake(method, repo, path, data=None):
            self.assertEqual(path, "/actions/runs/12")
            return {"head_branch": "main", "conclusion": "success"}
        failure("owner/repo", "stub", 12, now=datetime.now(timezone.utc),
                call=fake, sender=lambda *args: delivered.append(args))
        self.assertEqual(delivered, [])

    def test_no_picks_duplicate_runs_silent(self):
        now = datetime(2026, 11, 3, 6, 0, tzinfo=CENTRAL).astimezone(timezone.utc)
        rows = [{"number": 99, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-admin-monitor-v1:{"alerts":{},"report_day":""}'},
                {"number": 33, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"watchlist","completed_slot":"2026-11-03T04:17:00-06:00"}'},
                {"number": 34, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"picks","completed_slot":"2026-11-03T05:23:00-06:00"}'},
                {"number": 35, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"grading","completed_slot":"2026-11-02T23:55:00-06:00"}'}]
        recorded = {"workflow_runs": [{"head_branch": "main", "status": "completed",
                     "created_at": (now-timedelta(minutes=3)).isoformat(),
                     "conclusion": "success"}]}
        def fake(method, repo, path, data=None):
            if path.startswith("/issues?"):
                return rows
            if path.startswith("/actions/workflows/"):
                return recorded
            raise AssertionError("Unexpected write during silent run " + path)
        delivered = []
        watch("owner/repo", "stub", now=now, call=fake,
              sender=lambda *args: delivered.append(args))
        self.assertEqual(delivered, [])

    def test_missed_slot_alerts_only_once(self):
        now = datetime(2026, 11, 3, 8, 48, tzinfo=CENTRAL).astimezone(timezone.utc)
        state = {"alerts": {}, "report_day": "2026-11-02"}
        rows = [{"number": 99, "user": {"login": "github-actions[bot]"},
                 "body": "statrally-admin-monitor-v1:" +
                         __import__("json").dumps(state)},
                {"number": 34, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"picks","completed_slot":"2026-11-03T05:23:00-06:00"}'},
                {"number": 33, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"watchlist","completed_slot":"2026-11-03T04:17:00-06:00"}'},
                {"number": 35, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"grading","completed_slot":"2026-11-02T23:55:00-06:00"}'}]
        runs = {"workflow_runs": [{"head_branch": "main", "status": "completed",
                 "created_at": (now-timedelta(minutes=2)).isoformat(),
                 "conclusion": "success"}]}
        delivered = []
        def fake(method, repo, path, data=None):
            if path.startswith("/issues?"):
                return rows
            if path.startswith("/actions/workflows/"):
                return runs
            if method == "PATCH":
                state.update(__import__("json").loads(data["body"].split(":", 1)[1]))
                rows[0]["body"] = data["body"]
                return {"number": 99}
            raise AssertionError((method, path))
        for _ in range(2):
            watch("owner/repo", "stub", now=now, call=fake,
                  sender=lambda webhook, content: delivered.append(content))
        self.assertEqual(len(delivered), 1)
        self.assertIn("picks", delivered[0])


    def test_expected_windows_show_all_five_daily_slots(self):
        day = date(2026, 11, 4)
        windows = expected_windows(day)
        self.assertEqual(len(windows), 5)
        self.assertEqual({(name, slot.strftime("%H:%M")) for name, slot in windows},
                         {("watchlist", "04:17"), ("picks", "05:23"),
                          ("picks", "08:23"), ("picks", "14:23"),
                          ("grading", "23:55")})

    def test_missing_window_only_flagged_after_rollout(self):
        day = date(2026, 11, 4)
        completed = {expected_windows(day)[0]}
        body = "\n".join(window_status_lines(day, completed))
        self.assertIn("1/5", body)
        self.assertIn("Missed/unconfirmed windows: 4", body)
        old = "\n".join(window_status_lines(date(2026, 11, 3), set()))
        self.assertIn("historical / not verified", old)
        self.assertNotIn("missed / no receipt", old)

    def test_completed_window_audit_uses_verified_bot_comments(self):
        issue = {"number": 34, "user": {"login": "github-actions[bot]"},
                 "body": 'statrally-scheduler-checkpoint-v1:{"task":"picks","completed_slot":"2026-11-04T08:23:00-06:00"}'}
        calls = []
        def fake(method, repo, path, data=None):
            calls.append(path)
            return [{"user": {"login": "github-actions[bot]"},
                     "body": 'statrally-scheduler-slot-v1:{"task":"picks","completed_slot":"2026-11-04T05:23:00-06:00"}'}]
        seen = completed_window_audit("owner/repo", [issue], fake)
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(calls), 1)


    def test_delivery_totals_are_confirmed_comments_in_central_day(self):
        start = datetime(2026, 11, 4, 0, 0, tzinfo=CENTRAL).astimezone(timezone.utc)
        end = datetime(2026, 11, 5, 0, 0, tzinfo=CENTRAL).astimezone(timezone.utc)
        rows = [
            {"number": 4, "title": "BETA PAPER | X", "user": {"login": "github-actions[bot]"}},
            {"number": 5, "title": "StatRally watchlist | 2026-11-04", "user": {"login": "github-actions[bot]"}},
        ]
        records = {
            4: [
                {"created_at": "2026-11-04T13:00:00Z", "user": {"login": "github-actions[bot]"},
                 "body": "Discord delivery returned success.\nstatrally-beta-delivery-proof:abc"},
                {"created_at": "2026-11-04T23:59:00Z", "user": {"login": "github-actions[bot]"},
                 "body": "statrally-beta-results-delivered:abc"},
                {"created_at": "2026-11-05T13:00:00Z", "user": {"login": "github-actions[bot]"},
                 "body": "Discord delivery returned success.\nstatrally-beta-delivery-proof:later"},
            ],
            5: [
                {"created_at": "2026-11-04T14:00:00Z", "user": {"login": "github-actions[bot]"},
                 "body": "statrally-watchlist-page-delivered:1/2\nDiscord accepted this page."},
                {"created_at": "2026-11-04T14:01:00Z", "user": {"login": "github-actions[bot]"},
                 "body": "statrally-watchlist-page-delivered:2/2\nDiscord accepted this page."},
            ],
        }
        def fake(method, repo, path, data=None):
            number = int(path.split("/")[2])
            return records[number]
        totals = delivery_counts("owner/repo", rows, start, end, fake)
        self.assertEqual(totals, {"paper_picks": 1, "watchlist_pages": 2, "graded_results": 1})


if __name__ == "__main__":
    unittest.main()
