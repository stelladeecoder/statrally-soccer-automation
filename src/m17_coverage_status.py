"""Coverage states that separate schedule gaps, market gaps and model eligibility.

These are observation-window classifications, never assertions that a league
does not offer BTTS markets outside the verified scan.
"""


def classify_league(row):
    if not isinstance(row, dict):
        raise ValueError("Per-league coverage record required")
    keys = ("fixtures", "mapped", "markets_found", "fully_validated", "feed_failures")
    if any(type(row.get(k)) is not int or row[k] < 0 for k in keys):
        raise ValueError("Nonnegative coverage counters required")
    fixtures = row["fixtures"]
    mapped = row["mapped"]
    valid = row["fully_validated"]
    if mapped > fixtures or valid > mapped or row["markets_found"] < mapped:
        raise ValueError("Inconsistent coverage totals")
    if row["feed_failures"] or str(row.get("search_status", "")).startswith("failed"):
        status = "source_incomplete"
    elif fixtures == 0:
        status = "no_scheduled_fixtures"
    elif mapped == 0:
        status = "fixtures_without_verified_market_match"
    elif valid == 0:
        status = "matched_markets_no_eligible_predictions"
    elif valid < fixtures:
        status = "some_eligible_predictions"
    else:
        status = "all_observed_fixtures_eligible"
    return {
        "status": status,
        "scheduled_fixtures": fixtures,
        "verified_market_matches": mapped,
        "eligible_predictions": valid,
        "fixtures_without_verified_market_match": fixtures - mapped,
        "market_matches_not_eligible": mapped - valid,
        "complete_for_window": row["feed_failures"] == 0 and row.get("search_status") == "pages_exhausted",
    }


def classify_report(per_league, *, scan_complete):
    if not isinstance(per_league, dict) or type(scan_complete) is not bool:
        raise ValueError("Per-league coverage and verified scan completeness required")
    classified = {name: classify_league(row) for name, row in sorted(per_league.items())}
    return {
        "scan_complete": scan_complete,
        "not_exhaustive": not scan_complete,
        "leagues": classified,
        "counts_by_status": {
            status: sum(v["status"] == status for v in classified.values())
            for status in ("source_incomplete", "no_scheduled_fixtures",
                           "fixtures_without_verified_market_match",
                           "matched_markets_no_eligible_predictions",
                           "some_eligible_predictions", "all_observed_fixtures_eligible")
        },
    }
