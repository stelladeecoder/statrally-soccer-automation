# StatRally | Soccer BTTS Automation

**The Edge Is in the Data.**

StatRally is a **soccer Both Teams to Score (BTTS) YES/NO research and paper-tracking project** with a private modeling engine and public-safe GitHub Actions / Discord automation. **It does not place trades, promise positive expected value, or recommend wagering on an unvalidated model.**

> **Status — November 2, 2026:** The M13 experimental Discord beta is operating with scheduled fixture, picks and grading workflows. **Polymarket US is the selected next primary market-data provider**, but the current Discord beta still uses Kalshi until an end-to-end Polymarket replacement passes validation. M14 real-account Kalshi reconciliation is a separate **draft, unmerged** pull request and real-money financial reporting remains off.

## Daily Discord schedule

All times are **America/Chicago (Central)**. GitHub Actions may start scheduled jobs later than their nominal times. A scan or grading check may produce **no message** if nothing new qualifies.

| Time | Channel | Behavior |
| --- | --- | --- |
| **7:17 AM** | `#match-watchlist` | Lists the day's soccer fixtures from all 13 configured competition feeds |
| **8:23 AM** | `#btts-picks` | Morning experimental BTTS paper scan |
| **2:23 PM** | `#btts-picks` | Afternoon experimental BTTS paper scan, with duplicate suppression |
| **11:55 PM** | `#btts-results` | Checks independently confirmed final scores and grades outstanding paper predictions |

The watchlist covers all **13 configured competitions**: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Liga MX, UEFA Champions League, Eredivisie, Liga Portugal, Brasileirão Série A, Argentina Primera División, and UEFA Europa League. A live verification of the private feed expansion on a November 1 sample returned **36 fixtures and zero feed failures** across all 13 competitions ([GitHub Actions run](https://github.com/stelladeecoder/statrally-soccer-btts/actions/runs/41560694807), private repository). Some leagues had no scheduled fixtures that day, which does not indicate a feed failure. This fixture coverage is broader than the current Kalshi beta market allowlist.

## What is operational

- **M13 fixtures:** automated daily 13-competition match watchlist in Central Time; provider/API failures can lead to partial or empty fixture coverage.
- **M13 experimental picks:** scheduled read-only beta exporter with pre-kickoff fixture verification, current quote checks, up to three signals per export and persistent GitHub Issue reservations to prevent duplicate paper picks.
- **M13 grading:** independently checks regulation-time final scores; pending matches stay pending; only newly verified paper outcomes are eligible for posting. **Paper win rate and Brier scores are not real-money P&L.**
- **Discord integration:** separate watchlist, picks and results channels and controlled publishing safeguards.
- **Safety:** no order execution, auto-sell, automatic funding, or unattended real-money betting.

The initial documented experimental paper prediction is [Issue #20](https://github.com/stelladeecoder/statrally-soccer-automation/issues/20): **Manchester United vs Aston Villa, November 8, BTTS YES**, model probability **62.9%**, observed Kalshi quote **$0.64**. This is **not** an approved positive-EV betting recommendation. Publishing and deduplication were tested; one successful test does not establish sustained unattended reliability or predictive profitability.

### Model limitations

The private BTTS forecasting work remains **research-only**. A historical chronological calibration test on EPL data showed a simple constant-probability baseline had a **lower Brier score** than raw Poisson, sigmoid-calibrated and isotonic alternatives in that test. Consequently, calibrated profitable performance has **not** been validated; future Discord signals are explicitly experimental.

## Market providers: Kalshi now, Polymarket US in development

| Platform | Status | Current use |
| --- | --- | --- |
| **Kalshi** | Existing M12/M13 beta integration | Current source of experimental paper quotes for the Discord picks pipeline; current reviewed BTTS discovery covers EPL, MLS and Liga MX series |
| **Polymarket US** (`polymarket.us`) | **Preferred future source; integration under validation** | Private read-only SDK research, event-detail BTTS discovery and live best-bid/offer verification |
| Novig | Deferred | No active integration |

**Verified Polymarket US proof:** the private research workflow successfully fetched **two open, full-match BTTS YES/NO markets** with market identities and available BBO quotes: Nottingham Forest vs Manchester City (Nov 7) and Manchester United vs Aston Villa (Nov 8). Its initial league keyword searches returned no verified contracts because nested match-event prop markets were not being found; **a green keyword-search workflow did not establish league coverage**. Read-only event-level discovery was then implemented. This evidence **does not establish BTTS contract coverage, executable depth, or settlement compatibility for all 13 leagues**.

For future research only, first-half and second-half BTTS contracts have also been observed in event data. **They are excluded from the current full-match beta**, and would need separate models and calibration.

**Polymarket migration acceptance gates:** verify the actual full-match contract across supported fixtures; independently reconcile team identity and kickoff; validate side-specific executable prices, size and fees; integrate an appropriate pre-kickoff model forecast; pass paper-publishing and grading tests; and only then switch the scheduled `#btts-picks` source. Until then the existing Kalshi beta is intentionally unchanged.

Public market discovery does **not** require a user's trading credentials; the private repository holds implementation research, not secrets.

## M14: financial reconciliation is not deployed

[Draft PR #13](https://github.com/stelladeecoder/statrally-soccer-automation/pull/13) contains **read-only Kalshi account reconciliation work**, historical fill/fee/settlement handling, private manual authentication, and regression tests. It is **not merged**. A prior authentication test failed input validation before contacting Kalshi; the API credentials were subsequently corrected and an authentication rerun was requested. **Do not infer successful real-account reconciliation from implementation or unit tests.**

No live financial Discord messages, recurring financial publishing, or trading permissions have been enabled. M14 records, when eventually independently reconciled, are **separate** from M13 paper outcomes. Polymarket preference does not retroactively turn Kalshi transactions into Polymarket account history.

## Repository boundaries

| Repository | Visibility | Responsibility |
| --- | --- | --- |
| `stelladeecoder/statrally-soccer-btts` | **Private** | Historical league data, forecasts, calibration, market discovery and price-validation research, Kalshi and Polymarket US provider adapters |
| `stelladeecoder/statrally-soccer-automation` | **Public** | GitHub Actions schedules, guarded Discord delivery, paper-pick issue ledger and result grading, public-safe tests and documentation |

Private research code, API keys, account statements, webhook values and personal transactions should **never** be copied into this public repository.

## Workflows

| Workflow | Purpose |
| --- | --- |
| [Daily watchlist](.github/workflows/m13-daily-watchlist.yml) | 7:17 AM Central fixture posts |
| [M13 experimental paper picks](.github/workflows/m13-beta-paper-picks.yml) | 8:23 AM and 2:23 PM Central guarded scans |
| [M13 paper grading](.github/workflows/m13-beta-grading.yml) | 11:55 PM Central final-score grading |
| [M12 Kalshi scanner](.github/workflows/m12-kalshi-scanner.yml) | Separately gated read-only research scanner using `ENABLE_STAT_RALLY_SCANS` |
| [Picks webhook test](.github/workflows/m13-picks-webhook-smoke.yml) | One-time labeled connectivity test, not a prediction |

Latest runs and their actual outcomes are visible under [GitHub Actions](https://github.com/stelladeecoder/statrally-soccer-automation/actions). Scheduled times are not delivery guarantees.

## Tests

The public repository uses Python 3.12 for local offline regression testing:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Passing synthetic/offline tests is **not** the same as a validated live API session, profitable BTTS model, independent account reconciliation, or successful end-to-end Discord publishing.

## Roadmap

| Milestone | Focus | Current status |
| --- | --- | --- |
| M1–M12 | Private soccer data/model research, odds research and initial Kalshi scanner | Historical development complete; model profitability still unvalidated |
| **M13** | Scheduled Discord fixtures, paper predictions, independent result grading | **Beta operating; unattended and long-run validation ongoing** |
| **M14** | Account fills, fees, settlements, realized P&L and independent reconciliation | **Implemented in draft PR #13; real-account sign-off pending** |
| **Polymarket US migration** | Broader full-match BTTS discovery and provider replacement | **In progress; only specific live contracts verified** |
| **M15 web app** | Mobile-first dashboard, Discord tab and referral-links section | **Planned**, separate from the provider-migration work |
| Future | First-half and second-half BTTS research | **Deferred; separate modeling and validation required** |

## Responsible use

StatRally is an evidence-oriented research, automation and portfolio project. A model probability is not a verified edge; market prices must be evaluated against independent calibration, liquidity, trading costs and operational risk. No bet is required simply because a scan runs or a daily posting slot exists.
