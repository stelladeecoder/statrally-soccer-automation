import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from m13_discord_publish import render,publish,render_watchlist,render_picks,render_approved_picks

class M13DiscordTests(unittest.TestCase):
    def test_watchlist_rejects_decision_scan(self):
        with self.assertRaises(ValueError):
            render_watchlist({"status":"research_only","decisions":[]})
    def test_watchlist_shows_daily_fixtures_without_bet_decisions(self):
        report={"status":"fixture_schedule","date_central":"2026-11-08","fixtures":[{"league":"Premier League","home_team":"Manchester United","away_team":"Aston Villa","kickoff_utc":"2026-11-08T16:30:00+00:00"}]}
        text=render_watchlist(report)["content"]
        self.assertIn("Manchester United vs Aston Villa",text)
        self.assertIn("10:30 AM CT",text)
        self.assertNotIn("NO_BET",text)
        self.assertNotIn("No betting",text)
    def test_watchlist_does_not_post_empty_day(self):
        self.assertIn("No matches scheduled today",render_watchlist({"status":"fixture_schedule","date_central":"2026-11-01","fixtures":[]})["content"])
    def test_picks_never_publish_unapproved_scan(self):
        self.assertIsNone(render_picks({"status":"research_only","trades_placed":0,"decisions":[{"qualified_bet":True}]}))
    def test_picks_reject_invalid_scan(self):
        with self.assertRaises(ValueError):
            render_picks({"status":"other","trades_placed":0,"decisions":[]})
    def test_approved_picks_format_simulated(self):
        sample={"schema_version":1,"approval":"verified","model_calibrated":True,"picks":[{"fixture_verified":True,"fee_verified":True,"qualified_bet":True,"home_team":"Sample Home","away_team":"Sample Away","side":"YES","market_ticker":"SAMPLE-1","entry_price":0.55,"net_ev_per_contract":0.04}]}
        msg=render_approved_picks(sample)["content"]
        self.assertIn("Sample Home vs Sample Away",msg)
        self.assertIn("net EV",msg)
    def test_unapproved_picks_rejected(self):
        sample={"schema_version":1,"approval":"verified","model_calibrated":False,"picks":[]}
        with self.assertRaises(ValueError):
            render_approved_picks(sample)
    def test_too_many_picks_rejected(self):
        base={"fixture_verified":True,"fee_verified":True,"qualified_bet":True,"home_team":"H","away_team":"A","side":"YES","market_ticker":"T","entry_price":0.5,"net_ev_per_contract":0.01}
        sample={"schema_version":1,"approval":"verified","model_calibrated":True,"picks":[base]*4}
        with self.assertRaises(ValueError):
            render_approved_picks(sample)
    def test_no_bet(self):
        p=render({"status":"research_only","trades_placed":0,"decisions":[{"status":"NO_BET","qualified_bet":False}]})
        self.assertIn("No qualified selections",p["content"])
    def test_reject_wrong_status(self):
        with self.assertRaises(ValueError):
            render({"status":"failed","trades_placed":0,"decisions":[]})
    def test_reject_missing_decisions(self):
        with self.assertRaises(ValueError):
            render({"status":"research_only","trades_placed":0})
    def test_never_advertise_unverified_candidate(self):
        p=render({"status":"research_only","trades_placed":0,"decisions":[{"qualified_bet":True}]})
        self.assertIn("No published selections",p["content"])
    def test_reject_trade_activity(self):
        with self.assertRaises(ValueError):
            render({"status":"research_only","trades_placed":1,"decisions":[]})
    def test_empty_scan_is_no_bet(self):
        payload=render({"status":"research_only","trades_placed":0,"decisions":[]})
        self.assertIn("No qualified selections",payload["content"])
    def test_reject_non_discord_webhook(self):
        with self.assertRaises(ValueError):
            publish({"content":"No Bet"},"https://example.com/token",opener=lambda *a,**kw:None)
    def test_publish_mocked(self):
        class Fake:
            status=204
            def __enter__(self):return self
            def __exit__(self,*args):return None
        opened=[]
        def opener(request,timeout=15):
            opened.append((request,timeout))
            return Fake()
        self.assertTrue(publish({"content":"No Bet"},"https://discord.com/api/webhooks/123/test",opener=opener))
        self.assertEqual(opened[0][1],15)

if __name__=="__main__":unittest.main()
