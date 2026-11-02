import unittest
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from m13_beta_signals import render_beta
from m13_beta_dispatch import process

NOW=datetime.now(timezone.utc)
def envelope():
    return {"schema_version":1,"status":"experimental_paper","trades_placed":0,
      "signals":[{"market_ticker":"TEST-MARKET","side":"YES","home_team":"Home","away_team":"Away",
        "kickoff_utc":(NOW+timedelta(hours=2)).isoformat(),
        "observed_at_utc":NOW.isoformat(),
        "model_probability":"0.58","market_price":"0.52",
        "fixture_verified":True,"quote_verified":True}]}
class BetaPipelineTests(unittest.TestCase):
    def test_render_has_real_newlines(self):
        self.assertIn(chr(10),render_beta(envelope())["content"])
        self.assertNotIn(chr(92)+"n",render_beta(envelope())["content"])
    def test_durable_reservation_before_send(self):
        calls=[]
        def api(method,path,token,data=None):
            calls.append(method)
            if method=="GET":return []
            if "/comments" in path:return {}
            return {"number":77}
        with patch("m13_beta_dispatch.github",side_effect=api),patch("m13_beta_dispatch.publish") as send:
            self.assertEqual(process(envelope(),"owner/repo","token","https://discord.com/api/webhooks/1/test"),1)
        self.assertEqual(calls,["GET","POST","POST"])
        send.assert_called_once()
    def test_duplicate_not_resent(self):
        e=envelope();identity="TEST-MARKET|YES|"+e["signals"][0]["kickoff_utc"]
        with patch("m13_beta_dispatch.github",return_value=[{"body":"statrally-beta-id:"+identity}]),patch("m13_beta_dispatch.publish") as send:
            self.assertEqual(process(e,"owner/repo","token","https://discord.com/api/webhooks/1/test"),0)
            send.assert_not_called()
    def test_failed_send_never_marked_delivered(self):
        with patch("m13_beta_dispatch.github",side_effect=[[],{"number":77}]) as api,patch("m13_beta_dispatch.publish",side_effect=OSError("network")):
            with self.assertRaises(OSError):
                process(envelope(),"owner/repo","token","https://discord.com/api/webhooks/1/test")
            self.assertEqual(api.call_count,2)
    def test_full_history_refuses_to_guess(self):
        with patch("m13_beta_dispatch.github",return_value=[{"body":"x"}]*100),patch("m13_beta_dispatch.publish") as send:
            with self.assertRaises(RuntimeError):
                process(envelope(),"owner/repo","token","https://discord.com/api/webhooks/1/test")
            send.assert_not_called()
if __name__=="__main__":unittest.main()
