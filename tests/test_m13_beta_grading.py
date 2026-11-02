import unittest
from m13_beta_grading import grade, aggregate
SIGNAL={"league":"epl","espn_event_id":"123","home_team":"Alpha","away_team":"Beta","side":"YES",
        "kickoff_utc":"2026-11-02T20:00:00+00:00","model_probability":"0.60","market_price":"0.55"}
def fixture(h=2,a=1,complete=True):
    return {"events":[{"id":"123","date":SIGNAL["kickoff_utc"],"status":{"type":{"completed":complete}},
      "competitions":[{"competitors":[{"homeAway":"home","team":{"displayName":"Alpha"},"score":str(h)},
                                     {"homeAway":"away","team":{"displayName":"Beta"},"score":str(a)}]}]}]}
class GradingTests(unittest.TestCase):
    def test_yes_win(self): self.assertEqual(grade(SIGNAL,fixture())["result"],"WIN")
    def test_yes_loss(self): self.assertEqual(grade(SIGNAL,fixture(a=0))["result"],"LOSS")
    def test_no_win(self): self.assertEqual(grade(dict(SIGNAL,side="NO"),fixture(a=0))["result"],"WIN")
    def test_pending(self): self.assertEqual(grade(SIGNAL,fixture(complete=False))["status"],"pending")
    def test_wrong_event_rejected(self):
        with self.assertRaises(ValueError):grade(dict(SIGNAL,espn_event_id="999"),fixture())
    def test_wrong_team_rejected(self):
        with self.assertRaises(ValueError):grade(dict(SIGNAL,home_team="Other"),fixture())
    def test_aggregate(self):
        x=aggregate([{"status":"graded","result":"WIN"},{"status":"graded","result":"LOSS"},{"status":"pending"}])
        self.assertEqual(x,{"graded":2,"wins":1,"losses":1,"hit_rate":0.5,"brier_score":None,"pending":1})
    def test_brier_for_yes_paper_prediction(self):
        x=aggregate([{"status":"graded","result":"WIN","side":"YES","model_probability":"0.6","btts_yes":True}])
        self.assertEqual(x["brier_score"],"0.16")
    def test_empty(self):self.assertIsNone(aggregate([])["hit_rate"])
if __name__=="__main__":unittest.main()
