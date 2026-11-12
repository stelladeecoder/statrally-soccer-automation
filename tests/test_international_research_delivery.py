"""One-time international research Discord delivery safety tests."""
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from international_research_delivery import deliver

NOW=datetime(2026,11,12,9,0,tzinfo=ZoneInfo("America/Chicago"))
WEBHOOK="https://discord.com/api/webhooks/123/fixture-token"
PAYLOAD={"content":"**International**\nExperimental, uncalibrated probabilities.\n🔵 Italy vs France | YES 71%",
         "allowed_mentions":{"parse":[]}}

class DeliveryTests(unittest.TestCase):
    def test_no_eligible_forecasts_sends_nothing(self):
        self.assertEqual(deliver([],"owner/repo","token",WEBHOOK,now=NOW)["confirmed"],0)
    def test_invalid_payload_fails_before_sending(self):
        with self.assertRaises(ValueError):
            deliver([{"content":"Unsafe","allowed_mentions":{"parse":[]}}],
                    "owner/repo","token",WEBHOOK,now=NOW)
    def test_invalid_webhook_is_rejected(self):
        with self.assertRaises(ValueError):
            deliver([PAYLOAD],"owner/repo","token","https://example.com/w",now=NOW)
    def test_confirmed_daily_page_is_not_resent(self):
        with patch("international_research_delivery.ledger",return_value=1),\
             patch("international_research_delivery.comments",return_value=[
               {"body":"statrally-intl-research-v1:page:1:confirmed:abc",
                "user":{"login":"github-actions[bot]"}}]),\
             patch("international_research_delivery.urlopen") as sender:
            result=deliver([PAYLOAD],"owner/repo","token",WEBHOOK,now=NOW)
        self.assertEqual(result["confirmed"],0)
        sender.assert_not_called()
    def test_reserve_then_confirm_receipt(self):
        events=[]
        def fake_gh(method,repo,token,path,data=None):
            if method=="POST":
                events.append(data["body"])
                return {"id":42}
            self.fail("Unexpected API call")
        class Reply:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return b'{"id":"1234567"}'
        with patch("international_research_delivery.ledger",return_value=1),\
             patch("international_research_delivery.comments",return_value=[]),\
             patch("international_research_delivery.gh",side_effect=fake_gh),\
             patch("international_research_delivery.urlopen",return_value=Reply()):
            result=deliver([PAYLOAD],"owner/repo","token",WEBHOOK,now=NOW)
        self.assertEqual(result["confirmed"],1)
        self.assertIn(":reserved:",events[0])
        self.assertIn(":confirmed:",events[1])

if __name__=="__main__":
    unittest.main()
