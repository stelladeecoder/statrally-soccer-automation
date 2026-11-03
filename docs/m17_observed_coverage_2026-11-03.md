# Polymarket US observed coverage: 3–10 November 2026

**Source:** [read-only seven-day GitHub Actions audit](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41641869998), sampled from 2026-11-03 13:10 UTC. This audit completed with **failure by design** because the discoverer's `scan_complete` flag was false. Its observations are useful but **not exhaustive market inventory**. Do not interpret absent matches as unavailable across the provider.

| Competition | Future fixtures in window | Verified market mappings | Fully eligible paper candidates | Classification |
|---|---:|---:|---:|---|
| Premier League | 10 | 8 | 7 | Some eligible |
| Bundesliga | 9 | 3 | 2 | Some eligible |
| La Liga | 10 | 1 | 1 | Some eligible |
| Serie A | 10 | 0 | 0 | Fixtures, no verified market mapping |
| Ligue 1 | 9 | 2 | 1 | Some eligible |
| Eredivisie | 9 | 0 | 0 | Fixtures, no verified market mapping |
| Liga Portugal | 9 | 0 | 0 | Fixtures, no verified market mapping |
| Brasileirão | 9 | 0 | 0 | Fixtures, no verified market mapping |
| MLS | 15 | 0 | 0 | Fixtures, no verified market mapping |
| Liga MX | 9 | 0 | 0 | Fixtures, no verified market mapping |
| Argentine Primera | 15 | 0 | 0 | Fixtures, no verified market mapping |
| Champions League | 18 | 7 | 2 | Some eligible |
| Europa League | 18 | 4 | 0 | Matched markets, no eligible predictions |

The 13-league result contains **90 BTTS markets found** across provider events, **25 mapped** to independent ESPN fixtures, and **13 validated** eligible candidates. `fully_validated` is *not* a delivered-pick count, and not every verified market corresponds to a unique usable fixture in a larger time window.

Exclusions among mapped candidates included **11 historical team-identity mismatches** and **one insufficient pre-match-history failure**. Zero ESPN feed failures were reported, but `scan_complete=false` means other completeness conditions were unmet; the captured summary did not preserve enough fields to identify the exact condition. Do not assert that all provider markets have been scanned.

## Classification rules implemented in M17

1. `no_scheduled_fixtures`: independently verified zero fixtures in the observation window, with successful feeds.
2. `fixtures_without_verified_market_match`: at least one match, no unambiguous linked full-match BTTS contract found. This does **not** mean the platform has no such market.
3. `matched_markets_no_eligible_predictions`: a market match exists but no candidate passes prediction/quote/history verification.
4. `some_eligible_predictions` or `all_observed_fixtures_eligible`: validation succeeded for part or all of the observed fixtures; a scan with `scan_complete=false` is still nonexhaustive.
5. `source_incomplete`: failed independent fixtures feed or failed league search, outranking other statuses.

The status classifier deliberately does not conflate a regular-season break with missing trading markets. Overall incompleteness is always reported separately from the per-league classification.

**Operational boundary:** this audit did not place trades, send Discord messages or create paper Issue reservations. Its temporary workflow should not be merged into `main`. The classification module and tests can be moved to a separate small production PR once tested.
