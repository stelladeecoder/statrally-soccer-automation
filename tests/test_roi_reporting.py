"""Offline immutable reference-price and gross ROI reporting checks."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from test_prediction_platform import FakeGitHub, slate, NOW, REPO
from prediction_ledger import Ledger, ENTRY_QUOTE
from prediction_platform import annotate, save_original_quotes
from paper_roi import gross_paper_performance
from daily_results import report, result_embed
from recap_reports import summary, weekly_payload, monthly_payload


def quotes(predictions, price="0.50", observed=None):
    return {"schema_version":1, "source":"polymarket_us","trades_placed":0,
            "quotes":[{"prediction_id":p["prediction_id"],"side":p["side"],
                       "status":"verified","market_slug":"fictional-btts-"+p["espn_event_id"],
                       "price_dollars":price,
                       "observed_at":(observed or NOW+timedelta(minutes=1)).isoformat()}
                      for p in predictions]}


class PriceReferenceReportingTests(unittest.TestCase):
    def setUp(self):
        self.api=FakeGitHub()
        self.ledger=Ledger(REPO,"synthetic-token",call=self.api).load()

    def issue(self,count=1):
        predictions=self.ledger.issue_slate(slate(count),now=NOW)["predictions"]
        annotate(self.ledger,{"schema_version":1,"trades_placed":0,
            "markets":[{"prediction_id":p["prediction_id"],"provider":"polymarket_us",
                        "status":"verified_available","checked_at":NOW.isoformat(),
                        "event_slug":"fictional-match-"+p["espn_event_id"],
                        "market_slug":"fictional-btts-"+p["espn_event_id"]}
                       for p in predictions]})
        return predictions

    def grade(self,index=0,win=True):
        p=self.ledger.forecasts[index]["prediction"]
        self.ledger.append(self.ledger.forecasts[index]["issue_number"],
            "statrally-grade-v1:",{"prediction_id":p["prediction_id"],
            "status":"graded","result":"WIN" if win else "LOSS","correct":win})

    def test_no_historical_quote_means_unavailable_not_even_money(self):
        self.issue()
        self.grade()
        day=report(self.ledger,date(2026,11,5))
        self.assertIsNone(day["paper_overall"]["gross_roi_percent"])
        self.assertIn("N/A",str(result_embed(day)))
        self.assertIsNone(day["paper_overall"]["net_roi_percent"])

    def test_immutable_quote_and_gross_50_cent_price(self):
        predictions=self.issue(2)
        self.assertEqual(save_original_quotes(self.ledger,quotes(predictions),now=NOW+timedelta(minutes=1)),2)
        changed=quotes(predictions,"0.80")
        self.assertEqual(save_original_quotes(self.ledger,changed,now=NOW+timedelta(minutes=1)),0)
        for p in predictions:
            self.assertEqual(len(self.ledger.events(self.ledger.forecasts[0]["issue_number"],ENTRY_QUOTE)),2)
            break
        self.grade(0,True)
        self.grade(1,False)
        stats=gross_paper_performance(self.ledger.export()["records"])
        self.assertEqual(stats["gross_profit_dollars"],"0.00")
        self.assertEqual(stats["stake_dollars"],"20.00")
        self.assertEqual(stats["gross_returns_dollars"],"20.00")
        self.assertEqual(stats["gross_roi_percent"],0)
        self.assertIsNone(stats["net_profit_dollars"])

    def test_one_missing_quote_excluded_and_top_is_subset(self):
        predictions=self.issue(2)
        data=quotes(predictions[:1])
        self.assertEqual(save_original_quotes(self.ledger,data,now=NOW+timedelta(minutes=1)),1)
        p=self.ledger.forecasts[0]["prediction"]
        self.ledger.append(self.ledger.forecasts[0]["issue_number"],
            "statrally-prediction-delivery-v1:",
            {"prediction_id":p["prediction_id"],"kind":"top","state":"accepted"})
        self.grade(0,True)
        self.grade(1,False)
        x=summary(self.ledger,date(2026,11,1),date(2026,11,7))
        self.assertEqual(x["paper_overall"]["priced"],1)
        self.assertEqual(x["paper_overall"]["unpriced"],1)
        self.assertEqual(x["paper_overall"]["gross_profit_dollars"],"10.00")
        self.assertEqual(x["paper_top"]["priced"],1)
        self.assertEqual(x["paper_top"]["gross_profit_dollars"],"10.00")
        self.assertIn("1 unpriced excluded",str(weekly_payload(x)))
        m=summary(self.ledger,date(2026,11,1),date(2026,11,30))
        self.assertIn("70%+ Model Picks gross paper ROI",str(monthly_payload(m)))
        self.assertIn("Gross ROI",str(result_embed(report(self.ledger,date(2026,11,5)))))

    def test_stale_and_wrong_side_fail_closed(self):
        predictions=self.issue()
        mismatched=quotes(predictions)
        mismatched["quotes"][0]["side"]="YES" if predictions[0]["side"]=="NO" else "NO"
        self.assertEqual(save_original_quotes(self.ledger,mismatched,now=NOW+timedelta(minutes=1)),0)
        self.assertEqual(save_original_quotes(self.ledger,quotes(predictions),
            now=NOW+timedelta(minutes=12)),0)
        self.assertEqual(len(self.ledger.events(self.ledger.forecasts[0]["issue_number"],ENTRY_QUOTE)),0)

    def test_duplicate_entries_fail_closed(self):
        predictions=self.issue()
        save_original_quotes(self.ledger,quotes(predictions),now=NOW+timedelta(minutes=1))
        q=self.ledger.events(self.ledger.forecasts[0]["issue_number"],ENTRY_QUOTE)[0]
        self.ledger.append(self.ledger.forecasts[0]["issue_number"],ENTRY_QUOTE,q)
        with self.assertRaisesRegex(RuntimeError,"Duplicate immutable"):
            self.ledger.export()


if __name__=="__main__":
    unittest.main()
