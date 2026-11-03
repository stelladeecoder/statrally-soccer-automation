"""M17 coverage classes distinguish fixture absence from market/model gaps."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from m17_coverage_status import classify_league, classify_report, summarize_beta_diagnostics


class CoverageStatusTests(unittest.TestCase):
    def row(self, **kwargs):
        base = dict(fixtures=10, mapped=5, markets_found=6,
                    fully_validated=3, feed_failures=0, search_status="pages_exhausted")
        base.update(kwargs)
        return base

    def test_no_fixtures_is_not_market_failure(self):
        row = self.row(fixtures=0, mapped=0, markets_found=0, fully_validated=0)
        self.assertEqual(classify_league(row)["status"], "no_scheduled_fixtures")

    def test_fixtures_but_no_verified_market(self):
        row = self.row(mapped=0, markets_found=0, fully_validated=0)
        self.assertEqual(classify_league(row)["status"], "fixtures_without_verified_market_match")

    def test_found_market_but_no_eligible_prediction(self):
        row = self.row(fully_validated=0)
        self.assertEqual(classify_league(row)["status"], "matched_markets_no_eligible_predictions")

    def test_subset_eligible(self):
        result = classify_league(self.row())
        self.assertEqual(result["status"], "some_eligible_predictions")
        self.assertEqual(result["fixtures_without_verified_market_match"], 5)
        self.assertEqual(result["market_matches_not_eligible"], 2)

    def test_all_eligible(self):
        row = self.row(mapped=10, markets_found=10, fully_validated=10)
        self.assertEqual(classify_league(row)["status"], "all_observed_fixtures_eligible")

    def test_feed_error_takes_precedence(self):
        row = self.row(fixtures=0, mapped=0, markets_found=0, fully_validated=0, feed_failures=1)
        self.assertEqual(classify_league(row)["status"], "source_incomplete")

    def test_search_failure_takes_precedence(self):
        self.assertEqual(classify_league(self.row(search_status="failed_ValueError"))["status"], "source_incomplete")

    def test_reject_inconsistent_totals(self):
        with self.assertRaises(ValueError):
            classify_league(self.row(mapped=11))

    def test_reject_noninteger_counters(self):
        with self.assertRaises(ValueError):
            classify_league(self.row(fixtures=True))

    def test_live_diagnostics_distinguish_idle_and_eligibility(self):
        data = {"discovery": {"scan_complete": True, "leagues": {
            "epl": self.row(),
            "mls": self.row(fixtures=0, mapped=0, markets_found=0, fully_validated=0),
            "europa_league": self.row(fully_validated=0)}},
            "leagues": {"epl": {"validated": 3}, "europa_league": {"validated": 0}}}
        report = summarize_beta_diagnostics(data)
        self.assertEqual(report["leagues"]["mls"]["status"], "no_scheduled_fixtures")
        self.assertEqual(report["leagues"]["europa_league"]["status"], "matched_markets_no_eligible_predictions")
        self.assertEqual(report["leagues"]["epl"]["status"], "some_eligible_predictions")

    def test_report_labels_incomplete_scan(self):
        r = classify_report({"epl": self.row(), "mls": self.row(mapped=0, markets_found=0, fully_validated=0)}, scan_complete=False)
        self.assertTrue(r["not_exhaustive"])
        self.assertEqual(r["counts_by_status"]["some_eligible_predictions"], 1)
        self.assertEqual(r["counts_by_status"]["fixtures_without_verified_market_match"], 1)


if __name__ == "__main__":
    unittest.main()
