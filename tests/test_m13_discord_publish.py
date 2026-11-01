import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from m13_discord_publish import render,publish

class M13DiscordTests(unittest.TestCase):
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
