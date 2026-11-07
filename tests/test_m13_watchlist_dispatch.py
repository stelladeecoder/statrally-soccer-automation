"""Synthetic schedules and mocked durable storage/Discord only."""
import copy
from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

from m13_discord_publish import render_watchlist_pages
from m13_discord_embeds import payload_text, validate_payload
from m13_watchlist_dispatch import process as dispatch_process

def process(*args,**kwargs):
    return dispatch_process(*args,now=datetime(2026,11,8,14,tzinfo=timezone.utc),**kwargs)


def scan(count=1):
    return {"status":"fixture_schedule","date_central":"2026-11-08","failed_leagues":[],
            "fixtures":[{"league":"Premier League","home_team":f"SYNTHETIC Home {i}",
                         "away_team":f"SYNTHETIC Away {i}","kickoff_utc":"2026-11-08T16:30:00Z"}
                        for i in range(count)]}


class WatchlistTests(unittest.TestCase):
    def test_old_plaintext_reservation_blocks_new_embed_resend(self):
        old={'number':42,'body':'statrally-watchlist-day:2026-11-08\nPayload SHA256: LEGACY-PAYLOAD-HASH\nPages: 2'}
        receipts=[{'user':{'login':'github-actions[bot]'},'body':f'statrally-watchlist-page-delivered:{i}/2\nDiscord accepted this page. Payload SHA256: LEGACY-PAYLOAD-HASH'} for i in (1,2)]
        with patch('m13_watchlist_dispatch.records',side_effect=[[old],receipts]),patch('m13_watchlist_dispatch.publish') as send:
            self.assertEqual(process(scan(),'owner/repo','token','synthetic'),0)
        send.assert_not_called()
    def setUp(self):
        self.output=redirect_stdout(StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__,None,None,None)

    def test_pagination_never_silently_omits_fixtures_or_allows_mentions(self):
        pages=render_watchlist_pages(scan(300))
        self.assertGreater(len(pages),1)
        content="\n".join(payload_text(p) for p in pages)
        for i in range(300):self.assertIn(f"SYNTHETIC Home {i} vs SYNTHETIC Away {i}**",content+"\n")
        self.assertTrue(all(validate_payload(p) and p["allowed_mentions"]=={"parse":[]} for p in pages))

    def test_total_count_is_visible_on_every_page_and_not_a_mock_value(self):
        pages=render_watchlist_pages(scan(300))
        self.assertGreater(len(pages),1)
        for page in pages:
            summary=page["embeds"][0]["description"]
            self.assertIn("300 games scheduled",summary)
            self.assertIn("13 leagues tracked",summary)

    def test_reservation_precedes_delivery_and_repeat_is_blocked(self):
        issues=[]
        comments=[]
        def api(method,path,token,data=None):
            if method=="GET":return copy.deepcopy(comments if "/comments?" in path else issues)
            if "/comments" in path:
                comments.append({"id":1,"user":{"login":"github-actions[bot]"},**data})
                return comments[-1]
            issues.append({"number":42,**data})
            return issues[-1]
        def send(*args):self.assertEqual(len(issues),1)
        with patch("m13_beta_grade_issues.github",side_effect=api),patch("m13_watchlist_dispatch.github",side_effect=api),patch("m13_watchlist_dispatch.publish",side_effect=send) as publish:
            self.assertEqual(process(scan(),"owner/repo","token","synthetic"),1)
            self.assertEqual(process(scan(),"owner/repo","token","synthetic"),0)
        publish.assert_called_once()

    def test_explicit_v2_update_has_separate_one_time_reservation(self):
        issues=[]
        comments=[]
        sent=[]
        def api(method,path,token,data=None):
            if method=="GET":
                return copy.deepcopy(comments if "/comments?" in path else issues)
            if "/comments" in path:
                comments.append({"id":len(comments)+1,"user":{"login":"github-actions[bot]"},**data})
                return comments[-1]
            issues.append({"number":42+len(issues),**data})
            return issues[-1]
        def sender(payload,webhook):
            sent.append(payload)
        with patch("m13_beta_grade_issues.github",side_effect=api), patch(
                "m13_watchlist_dispatch.github",side_effect=api), patch(
                "m13_watchlist_dispatch.publish",side_effect=sender):
            self.assertEqual(process(scan(),"owner/repo","token","synthetic"),1)
            self.assertEqual(process(scan(),"owner/repo","token","synthetic",revision="v2"),1)
            self.assertEqual(process(scan(),"owner/repo","token","synthetic",revision="v2"),0)
        self.assertEqual(len(sent),2)
        self.assertIn("Updated ·",sent[1]["embeds"][0]["title"])
        self.assertEqual(len(issues),2)
        self.assertIn("statrally-watchlist-update-v2-day:2026-11-08",issues[1]["body"])

    def test_uncertain_send_keeps_reservation_and_blocks_retry(self):
        history=[]
        def api(*args):
            history.append({"body":"statrally-watchlist-day:2026-11-08"})
            return {"number":42}
        with patch("m13_watchlist_dispatch.records",side_effect=lambda *a:list(history)),patch("m13_watchlist_dispatch.github",side_effect=api),patch("m13_watchlist_dispatch.publish",side_effect=OSError("synthetic")) as publish:
            with self.assertRaises(OSError):process(scan(),"owner/repo","token","synthetic")
            with self.assertRaisesRegex(RuntimeError,"no automatic resend"):
                process(scan(),"owner/repo","token","synthetic")
        publish.assert_called_once()

    def test_naive_or_wrong_central_date_is_rejected(self):
        for stamp in ("2026-11-08T16:30:00","2026-11-08T01:00:00Z"):
            data=scan();data["fixtures"][0]["kickoff_utc"]=stamp
            with self.assertRaises(ValueError):render_watchlist_pages(data)

    def test_partial_empty_feed_never_becomes_no_matches_claim(self):
        data=dict(scan(0),status="partial_fixture_schedule",failed_leagues=["Premier League"])
        with patch("m13_watchlist_dispatch.github") as api,patch("m13_watchlist_dispatch.publish") as publish:
            with self.assertRaises(RuntimeError):process(data,"owner/repo","token","synthetic")
        api.assert_not_called();publish.assert_not_called()

    def test_missing_durable_reservation_or_receipt_fails(self):
        with patch("m13_watchlist_dispatch.records",return_value=[]),patch("m13_watchlist_dispatch.github",return_value={}),patch("m13_watchlist_dispatch.publish") as publish:
            with self.assertRaises(RuntimeError):process(scan(),"owner/repo","token","synthetic")
            publish.assert_not_called()
        with patch("m13_watchlist_dispatch.records",return_value=[]),patch("m13_watchlist_dispatch.github",side_effect=[{"number":42},{}]),patch("m13_watchlist_dispatch.publish") as publish:
            with self.assertRaisesRegex(RuntimeError,"receipt unconfirmed"):process(scan(),"owner/repo","token","synthetic")
            publish.assert_called_once()
