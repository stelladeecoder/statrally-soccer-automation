import unittest
from m13_beta_grading import LEAGUES, grade, aggregate
SIGNAL={"league":"epl","espn_event_id":"123","home_team":"Alpha","away_team":"Beta","side":"YES",
        "kickoff_utc":"2026-11-02T20:00:00+00:00","model_probability":"0.60","market_price":"0.55"}
def fixture(h=2,a=1,complete=True):
    return {"events":[{"id":"123","date":SIGNAL["kickoff_utc"],"status":{"type":{"completed":complete,"name":"STATUS_FULL_TIME"}},
      "competitions":[{"competitors":[{"homeAway":"home","team":{"displayName":"Alpha"},"score":str(h)},
                                     {"homeAway":"away","team":{"displayName":"Beta"},"score":str(a)}]}]}]}
class GradingTests(unittest.TestCase):
    def test_bound_team_ids_allow_display_updates_but_never_changed_or_reversed_teams(self):
        signal=dict(SIGNAL,espn_home_team_id="1",espn_away_team_id="2")
        data=fixture()
        teams=data["events"][0]["competitions"][0]["competitors"]
        teams[0]["team"]={"id":"1","displayName":"Updated Alpha"}
        teams[1]["team"]={"id":"2","displayName":"Updated Beta"}
        self.assertEqual(grade(signal,data)["result"],"WIN")
        teams[0]["team"]["id"]="2"
        with self.assertRaisesRegex(ValueError,"ID mismatch"):grade(signal,data)
    def test_all_thirteen_configured_leagues_can_be_graded(self):
        self.assertEqual(len(LEAGUES),13)
        for league in LEAGUES:
            with self.subTest(league=league):
                self.assertEqual(grade(dict(SIGNAL,league=league),fixture())["result"],"WIN")

    def test_postponed_cancelled_and_rescheduled_need_confirmation(self):
        for status in ("STATUS_POSTPONED","STATUS_CANCELED","STATUS_SUSPENDED"):
            data=fixture(complete=False)
            data["events"][0]["status"]["type"]["name"]=status
            self.assertEqual(grade(SIGNAL,data)["status"],"pending")
        data=fixture()
        data["events"][0]["date"]="2026-11-03T20:00:00Z"
        with self.assertRaisesRegex(ValueError,"Kickoff changed"):
            grade(SIGNAL,data)
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
    def test_cancelled_or_extra_time_game_is_not_a_regulation_result(self):
        for name in ("STATUS_CANCELED","STATUS_FINAL_AET","STATUS_FINAL_PEN",None):
            feed=fixture();feed["events"][0]["status"]["type"]["name"]=name
            with self.subTest(name=name):self.assertEqual(grade(SIGNAL,feed)["status"],"pending")
    def test_ambiguous_competitors_rejected(self):
        feed=fixture();feed["events"][0]["competitions"][0]["competitors"].append({"homeAway":"other"})
        with self.assertRaises(ValueError):grade(SIGNAL,feed)
    def test_invalid_probability_cannot_crash_or_invent_brier_score(self):
        report=aggregate([{"status":"graded","result":"WIN","side":"YES","model_probability":"invalid","btts_yes":True}])
        self.assertIsNone(report["brier_score"])
if __name__=="__main__":unittest.main()
