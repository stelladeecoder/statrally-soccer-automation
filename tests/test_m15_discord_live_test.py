import unittest
from datetime import datetime, timezone
from m15_discord_live_test import LEAGUES, watchlist_payloads, picks_payloads


class LiveTestFormatting(unittest.TestCase):
    def test_full_watchlist_is_paginated_without_dropping_fixtures(self):
        fixtures = [{"league": "Premier League", "home_team": "Home " + str(i),
                     "away_team": "Away " + str(i), "kickoff_utc": "2026-11-02T20:00:00Z"}
                    for i in range(120)]
        payloads = watchlist_payloads({"status": "fixture_schedule", "date_central": "2026-11-02",
                                      "fixtures": fixtures, "failed_leagues": []})
        self.assertGreater(len(payloads), 1)
        self.assertEqual(sum(p["content"].count("• Premier League") for p in payloads), 120)
        self.assertTrue(all(len(p["content"]) <= 2000 for p in payloads))
        self.assertTrue(all(p["allowed_mentions"] == {"parse": []} for p in payloads))

    def diagnostics(self):
        return {"discovery": {"leagues": {l: {"fixtures": 0, "mapped": 0, "feed_failures": 0} for l in LEAGUES},
            "window_start_utc": "2026-11-03T00:00:00Z", "window_end_utc": "2026-11-10T00:00:00Z",
            "scan_complete": False}, "leagues": {}}

    def test_empty_scan_is_explicit_test_report_not_fake_pick(self):
        payloads = picks_payloads({"schema_version": 1, "status": "experimental_paper", "trades_placed": 0,
                                  "signals": []}, self.diagnostics())
        text = "\n".join(p["content"] for p in payloads)
        self.assertIn("No eligible paper picks", text)
        self.assertIn("COVERAGE INCOMPLETE", text)
        self.assertTrue(all("• " + l + ":" in text for l in LEAGUES))

    def test_partial_league_scan_cannot_claim_all_leagues(self):
        data = self.diagnostics()
        del data["discovery"]["leagues"]["epl"]
        with self.assertRaises(ValueError):
            picks_payloads({"schema_version": 1, "status": "experimental_paper", "trades_placed": 0,
                            "signals": []}, data)

    def test_watchlist_rejects_wrong_local_date(self):
        with self.assertRaises(ValueError):
            watchlist_payloads({"status": "fixture_schedule", "date_central": "2026-11-02",
                "fixtures": [{"league": "MLS", "home_team": "Home", "away_team": "Away",
                              "kickoff_utc": "2026-11-03T16:00:00Z"}]})


if __name__ == "__main__":
    unittest.main()
