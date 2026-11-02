import unittest
from datetime import datetime, timezone, timedelta
from m13_beta_signals import render_beta

NOW=datetime(2026,11,2,17,0,tzinfo=timezone.utc)
def sample():
    return {"schema_version":1,"status":"experimental_paper","trades_placed":0,
            "signals":[{"fixture_verified":True,"quote_verified":True,"market_ticker":"SAMPLE-MARKET","home_team":"Home","away_team":"Away",
                        "side":"YES","kickoff_utc":(NOW+timedelta(hours=2)).isoformat(),
                        "observed_at_utc":(NOW-timedelta(minutes=3)).isoformat(),
                        "model_probability":"0.58","market_price":"0.53"}]}
class BetaTests(unittest.TestCase):
    def test_valid_beta_has_clear_label(self):
        result=render_beta(sample(),NOW)
        self.assertIn("BETA PAPER PICKS",result["content"])
        self.assertIn("BTTS YES",result["content"])
        self.assertIn("No trades placed",result["content"])
    def test_stale_quote_rejected(self):
        s=sample();s["signals"][0]["observed_at_utc"]=(NOW-timedelta(minutes=16)).isoformat()
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_unverified_fixture_rejected(self):
        s=sample();s["signals"][0]["fixture_verified"]=False
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_unverified_quote_rejected(self):
        s=sample();s["signals"][0]["quote_verified"]=False
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_started_game_rejected(self):
        s=sample();s["signals"][0]["kickoff_utc"]=(NOW-timedelta(seconds=1)).isoformat()
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_nonzero_trade_rejected(self):
        s=sample();s["trades_placed"]=1
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_no_empty_candidates(self):
        s=sample();s["signals"]=[]
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_duplicate_market_rejected(self):
        s=sample();s["signals"]*=2
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_missing_market_price_rejected(self):
        s=sample();del s["signals"][0]["market_price"]
        with self.assertRaises(ValueError):render_beta(s,NOW)
    def test_probability_out_of_bounds(self):
        s=sample();s["signals"][0]["model_probability"]="1.2"
        with self.assertRaises(ValueError):render_beta(s,NOW)
if __name__=="__main__": unittest.main()
