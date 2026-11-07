"""Manual checking is append-only and does not pretend to verify an API market."""
import unittest
from manual_market_reviews import apply_reviews, DECISIONS
from prediction_ledger import MANUAL_MARKET

class FakeLedger:
    def __init__(self):
        self.reviews=[]
        self.mismatched=False
    def export(self):
        out=[]
        for identity,(home,away,decision) in DECISIONS.items():
            events=[e for e in self.reviews if e["prediction_id"]==identity]
            out.append({"prediction":{"prediction_id":identity,
                        "home_team":("WRONG" if self.mismatched else home),
                        "away_team":away,"league":"mls" if decision=="available" else "primera_lpf"},
                        "issue_number":75,
                        "market":{"status":"manual_"+events[0]["decision"] if events else "identity_mismatch"}})
        return {"records":out}
    def events(self,issue,prefix):
        assert issue==75 and prefix==MANUAL_MARKET
        return self.reviews
    def append(self,issue,prefix,value):
        self.reviews.append(value)

class TestManualReviews(unittest.TestCase):
    def test_five_exact_review_decisions_and_idempotency(self):
        ledger=FakeLedger()
        r=apply_reviews(ledger)
        self.assertEqual((r["manual_available"],r["manual_unavailable"],r["new_events"]),(2,3,5))
        self.assertEqual(apply_reviews(ledger)["new_events"],0)
        self.assertEqual(len(ledger.reviews),5)
        self.assertTrue(all(x["source"]=="user_manual_check" for x in ledger.reviews))

    def test_fixture_mismatch_causes_no_writes(self):
        ledger=FakeLedger()
        ledger.mismatched=True
        with self.assertRaisesRegex(RuntimeError,"wrong match"):apply_reviews(ledger)
        self.assertEqual(ledger.reviews,[])

    def test_conflicting_manual_review_fails_closed(self):
        ledger=FakeLedger()
        identity=next(iter(DECISIONS))
        ledger.reviews.append({"prediction_id":identity,"decision":"unavailable",
                               "source":"user_manual_check"})
        with self.assertRaisesRegex(RuntimeError,"Conflicting"):apply_reviews(ledger)

if __name__=="__main__":
    unittest.main()
