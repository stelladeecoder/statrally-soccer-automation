# StatRally | Soccer BTTS Automation

**The Edge Is in the Data.**

StatRally is a **soccer Both Teams to Score (BTTS) YES/NO research and paper-tracking project** with a private modeling engine and public-safe GitHub Actions / Discord automation. **It does not place trades, promise positive expected value, or recommend wagering on an unvalidated model.**

> **Status — November 2, 2026:** The M13 experimental Discord beta is operating with scheduled fixture, picks and grading workflows. **Polymarket US is now the active provider configured for the scheduled experimental BTTS paper-picks workflow.** The previous Kalshi scanner is manual-only, and historical Kalshi paper picks remain in the audit ledger. The new Polymarket exporter and public formatting passed an independent live read-only dry run; a *new* unattended Polymarket-to-Discord post has not yet been observed. M14 real-account Kalshi reconciliation is a separate **draft, unmerged** pull request and real-money financial reporting remains off.

## Daily Discord schedule

All times are **America/Chicago (Central)**. GitHub Actions may start scheduled jobs later than their nominal times. A scan or grading check may produce **no message** if nothing new qualifies.

| Time | Channel | Behavior |
| --- | --- | --- |
| **7:17 AM** | `#match-watchlist` | Lists the day's soccer fixtures from all 13 configured competition feeds |
| **8:23 AM** | `#btts-picks` | Morning experimental BTTS paper scan |
| **2:23 PM** | `#btts-picks` | Afternoon experimental BTTS paper scan, with duplicate suppression |
| **11:55 PM** | `#btts-results` | Checks independently confirmed final scores and grades outstanding paper predictions |

The watchlist covers all **13 configured competitions**: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Liga MX, UEFA Champions League, Eredivisie, Liga Portugal, Brasileirão Série A, Argentina Primera División, and UEFA Europa League. A live verification of the private feed expansion on a November 1 sample returned **36 fixtures and zero feed failures** across all 13 competitions ([GitHub Actions run](https://github.com/stelladeecoder/statrally-soccer-btts/actions/runs/41560694807), private repository). Some leagues had no scheduled fixtures that day, which does not indicate a feed failure. All 13 leagues have fixture feeds, but Polymarket market-to-ESPN identity mappings and private model availability remain separately limited; coverage is not presumed.

## What is operational

- **M13 fixtures:** automated daily 13-competition match watchlist in Central Time; provider/API failures can lead to partial or empty fixture coverage.
- **M13 experimental picks:** scheduled read-only beta exporter with pre-kickoff fixture verification, current quote checks, up to three signals per export and persistent GitHub Issue reservations to prevent duplicate paper picks.
- **M13 grading:** independently checks regulation-time final scores; pending matches stay pending; only newly verified paper outcomes are eligible for posting. **Paper win rate and Brier scores are not real-money P&L.**
- **Discord integration:** separate watchlist, picks and results channels and controlled publishing safeguards.
- **Safety:** no order execution, auto-sell, automatic funding, or unattended real-money betting.

The initial documented experimental paper prediction is [Issue #20](https://github.com/stelladeecoder/statrally-soccer-automation/issues/20): **Manchester United vs Aston Villa, November 8, BTTS YES**, model probability **62.9%**, observed Kalshi quote **$0.64**. This is **not** an approved positive-EV betting recommendation. Publishing and deduplication were tested; one successful test does not establish sustained unattended reliability or predictive profitability.

### Model limitations

The private BTTS forecasting work remains **research-only**. A historical chronological calibration test on EPL data showed a simple constant-probability baseline had a **lower Brier score** than raw Poisson, sigmoid-calibrated and isotonic alternatives in that test. Consequently, calibrated profitable performance has **not** been validated; future Discord signals are explicitly experimental.

## Market provider: Polymarket US

| Platform | Status | Current use |
| --- | --- | --- |
| **Polymarket US** (`polymarket.us`) | **Active scheduled paper-picks source** | Independently verified full-match BTTS market, YES/NO quote and provider event; independently reconciled ESPN fixture and experimental private historical forecast |
| **Kalshi (historical only)** | **Retired from scheduled scans** | Existing paper records and separate unfinished M14 draft remain for audit; no Kalshi trade execution or scheduled market sourcing |

**Verified Polymarket US proof:** the private research workflow successfully fetched **two open, full-match BTTS YES/NO markets** with market identities and available BBO quotes: Nottingham Forest vs Manchester City (Nov 7) and Manchester United vs Aston Villa (Nov 8). Its initial league keyword searches returned no verified contracts because nested match-event prop markets were not being found; **a green keyword-search workflow did not establish league coverage**. Read-only event-level discovery was then implemented. This evidence **does not establish BTTS contract coverage, executable depth, or settlement compatibility for all 13 leagues**.

For future research only, first-half and second-half BTTS contracts have also been observed in event data. **They are excluded from the current full-match beta**, and would need separate models and calibration.

**Provider switch:** The scheduled `#btts-picks` workflow now executes the Polymarket US exporter instead of the Kalshi exporter. It uses explicit reviewed provider-to-ESPN event mappings and the existing research-only private forecast. A successful read-only end-to-end dry run produced **one** experimental signal and passed public format and cross-provider duplicate tests ([validation run](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41562116197)). Existing Kalshi Issue records remain untouched, and duplicate paper signals for the same ESPN fixture and side are suppressed across providers. **The current reviewed mapping inventory is narrow (one fixture); all 13 leagues are not yet eligible for Polymarket paper picks.** Broader verified contract mapping, side-specific size/fees, calibrated probabilities, unattended Discord proof, and postgame outcomes remain open validation items.

Public market discovery does **not** require a user's trading credentials; the private repository holds implementation research, not secrets.

## M14: financial reconciliation is not deployed

[Draft PR #13](https://github.com/stelladeecoder/statrally-soccer-automation/pull/13) contains **read-only Kalshi account reconciliation work**, historical fill/fee/settlement handling, private manual authentication, and regression tests. It is **not merged**. A prior authentication test failed input validation before contacting Kalshi; the API credentials were subsequently corrected and an authentication rerun was requested. **Do not infer successful real-account reconciliation from implementation or unit tests.**

No live financial Discord messages, recurring financial publishing, or trading permissions have been enabled. M14 records, when eventually independently reconciled, are **separate** from M13 paper outcomes. The new provider choice does not retroactively turn Kalshi transactions into Polymarket account history.

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
| [M13 Polymarket US paper picks](.github/workflows/m13-beta-paper-picks.yml) | 8:23 AM and 2:23 PM Central, read-only full-match BTTS with guarded Discord dispatch |
| [M13 paper grading](.github/workflows/m13-beta-grading.yml) | 11:55 PM Central final-score grading |
| [Legacy M12 Kalshi scanner](.github/workflows/m12-kalshi-scanner.yml) | Historical/manual-only research; recurring schedule disabled |
| [Polymarket migration dry-run verification](.github/workflows/m15-polymarket-migration-verify.yml) | Tests public formatting and live private read-only exporter without sending Discord messages |
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
| **Polymarket US migration** | Replace Kalshi in scheduled experimental BTTS picks; expand reviewed market/fixture/model coverage | **Scheduled provider switched; one live paper-export fixture verified, broader coverage and unattended posting not yet verified** |
| **M15 web app** | Mobile-first dashboard, Discord tab and referral-links section | **Planned**, separate from the provider-migration work |
| Future | First-half and second-half BTTS research | **Deferred; separate modeling and validation required** |

## Responsible use

StatRally is an evidence-oriented research, automation and portfolio project. A model probability is not a verified edge; market prices must be evaluated against independent calibration, liquidity, trading costs and operational risk. No bet is required simply because a scan runs or a daily posting slot exists.
