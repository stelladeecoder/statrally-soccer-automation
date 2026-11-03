"""Public pipeline regression checks for Polymarket US replacing Kalshi."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from m13_beta_dispatch import process as dispatch_process
from m13_discord_embeds import payload_text
from m13_beta_signals import render_beta

NOW=datetime(2026,11,3,14,tzinfo=timezone.utc)

def process(*args,**kwargs):
    return dispatch_process(*args,now=NOW,**kwargs)

def envelope(provider="polymarket"):
    now=NOW
    ticker=("astatc-epl-mnu-ast-2026-11-08-btts"
            if provider=="polymarket" else "KXEPLBTTS-26NOV08MUNAVL-BTTS")
    return {"schema_version":1,"status":"experimental_paper","trades_placed":0,
      "signals":[{"market_ticker":ticker,"side":"YES","home_team":"Manchester United",
                  "away_team":"Aston Villa","league":"epl","espn_event_id":"401879240",
                  "kickoff_utc":(now+timedelta(hours=2)).isoformat(),
                  "observed_at_utc":now.isoformat(),
                  "model_probability":"0.63","market_price":"0.63",
                  "fixture_verified":True,"quote_verified":True}]}

class PolymarketPublicTests(unittest.TestCase):
    def test_polymarket_price_label(self):
        content=payload_text(render_beta(envelope(),now=NOW))
        self.assertIn("Polymarket US quote",content)
        self.assertNotIn("Kalshi quote",content)

    def test_old_kalshi_issue_suppresses_same_fixture_pick(self):
        new=envelope()
        prev=dict(new["signals"][0])
        prev["market_ticker"]="KXEPLBTTS-26NOV08MUNAVL-BTTS"
        oldbody="statrally-beta-data:"+json.dumps(prev)
        with patch("m13_beta_dispatch.github",return_value=[{"body":oldbody}]),patch("m13_beta_dispatch.publish") as send:
            self.assertEqual(process(new,"owner/repo","token","synthetic-webhook"),0)
            send.assert_not_called()

    def test_new_polymarket_paper_reservation_before_delivery(self):
        events=[]
        def api(method,path,token,data=None):
            events.append(method)
            if method=="GET":return []
            if "/comments" in path:return {"id":1}
            return {"number":101}
        with patch("m13_beta_dispatch.github",side_effect=api),patch("m13_beta_dispatch.publish") as send:
            self.assertEqual(process(envelope(),"owner/repo","token","synthetic-webhook"),1)
            self.assertEqual(events,["GET","POST","POST"])
            send.assert_called_once()
            self.assertIn("Polymarket US quote",payload_text(send.call_args.args[0]))

if __name__=="__main__":
    unittest.main()
