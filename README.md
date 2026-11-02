# StatRally | Soccer Automation

**The Edge Is in the Data.**

Public GitHub Actions and Discord-delivery infrastructure for **StatRally**, a soccer **Both Teams to Score (BTTS) Yes/No** research project.

> **Status (November 2, 2026):** Milestones **1–12 complete**; **M13 (Discord automation) and M14 (performance tracking) in progress**. M14 has local accounting, SDK-shaped response importing, performance reports and a guarded results publisher tested with synthetic data. Live account reconciliation and results-channel activation remain unverified. **The first unattended daily watchlist post has not yet been verified.** No live betting recommendations or automated trades are authorized.

## What this public repository does

- **Daily match watchlist:** fetches fixtures for the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Liga MX, and UEFA Champions League.
- **Discord #match-watchlist:** groups matches by league and displays kickoff times in **America/Chicago**. The dedicated workflow runs at **7:05 AM Central daily**, subject to GitHub Actions scheduling delays.
- **Discord #btts-picks:** a *separate* webhook is connected and its **one-time test message was visually confirmed in Discord**. A guarded formatter for verified selections exists, but **real picks publishing is not enabled**. The private research scanner cannot currently produce approved selections.
- **Read-only research scans:** the separate Kalshi scanner workflow remains gated by the `ENABLE_STAT_RALLY_SCANS` repository variable. Running a scan does not mean placing a bet.

The watchlist is **fixtures only**, with no EV, odds, No Bet decisions, or player recommendations. Not every competition has games every day. Discord team/league logos and richer embeds are deferred to a later enhancement.

## Repository boundaries

| Repository | Responsibility | Visibility |
| --- | --- | --- |
| `stelladeecoder/statrally-soccer-btts` | Research data, model/validation, odds and Kalshi EV logic, fixture collection | Private |
| `stelladeecoder/statrally-soccer-automation` | Public-safe workflows, Discord formatting, guarded publishing, M14 accounting/importing/performance code, tests | Public |

The current research model is **not approved to claim a profitable betting edge**. This repository does not place or execute trades.

## Workflows

| Workflow | Purpose | Operational state |
| --- | --- | --- |
| [Daily soccer fixture watchlist](.github/workflows/m13-daily-watchlist.yml) | Retrieves multi-league fixtures from the private engine and posts the schedule to Discord | Scheduled daily at 7:05 AM America/Chicago; first unattended post pending verification |
| [M12 Kalshi scanner](.github/workflows/m12-kalshi-scanner.yml) | Bounded, read-only research scan and dry-run publisher checks | Requires `ENABLE_STAT_RALLY_SCANS=true`; does not publish actionable selections |
| [M13 picks webhook smoke test](.github/workflows/m13-picks-webhook-smoke.yml) | One-time Discord connectivity message, explicitly labeled **NOT A BETTING PICK** | Test message confirmed in `#btts-picks`; not a daily picks publisher |

The fixture watchlist is **independent** of the gated M12 scanner so a research-scanner error does not prevent the day's schedule.

## Code and local tests

- `src/m13_discord_publish.py`: watchlist formatter, guarded research reporting, picks formatting, webhook transport.
- `tests/test_m13_discord_publish.py`: safety and formatting regression tests.
- `docs/m13_discord_publishing.md`: development log and acceptance notes.
- `src/m14_position_ledger.py`: Decimal FIFO positions, fee allocation and realized closures.
- `src/m14_import.py`: versioned Kalshi response adapter and private transactional store.
- `src/m14_kalshi_rest.py`: current fixed-point/dollar REST schemas and historical-data coverage.
- `src/m14_performance.py`: daily, weekly and cumulative actual-event metrics.
- `src/m14_results_publish.py`: separate, dry-run-by-default `#btts-results` reporting.
- [M14 architecture, input contracts and limitations](docs/m14_performance.md).

Run the offline unit suite with Python 3.12:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

**Verified:** all **17 tests passed** in GitHub Actions run [41363527302](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41363527302). A controlled message to `#btts-picks` was also confirmed by the server owner. These checks do **not** establish a validated betting edge.

The expanded M14 suite runs locally with the same command and in read-only
pull-request CI. All new account and
performance examples are **synthetic**, and Discord transport is mocked. Local
validation does not establish live account compatibility or real financial results.

## Development roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| M1–M10 | Soccer data pipelines, feature engineering, model research and validation | Complete |
| M11 | Historical evaluation and fee-aware odds/EV research | Complete |
| M12 | Read-only live Kalshi integration | Complete |
| **M13** | Multi-league Discord watchlist and guarded picks-channel integration | **In progress** |
| **M14** | Actual settled positions, fees, win/loss, profit/loss and ROI; `#btts-results` | **In progress — synthetic/local validation; live reconciliation and activation pending** |
| M15 | Mobile-friendly public dashboard with Discord and referral links, hosted on GitHub Pages | Planned |

### M13 remaining acceptance

1. Verify the **first unattended** scheduled `#match-watchlist` post and its fixture/time accuracy.
2. Keep real `#btts-picks` selections **disabled** until the private engine provides independently validated, qualified recommendations and an approved publishing workflow.

**Future enhancement:** team crests, league logos, and richer Discord embeds after reliable plain-text delivery is confirmed.

### M14 development status

The migrated ledger now keeps entry fees in open FIFO basis until contracts close.
Reports distinguish partial exits from completed position cycles and define ROI
as net realized P&L divided by fee-inclusive entry cost of the contracts closed.
Unrealized P&L stays unknown without mark prices.

The offline importer supports current REST/OpenAPI 3.35.0 fixed-point fills,
source-provided fees and dollar-denominated binary settlements, with fractional
contract quantities, scoped netting, live/historical pagination and position
coverage checks. Archived summaries never become invented settlement events;
missing closure records and inconsistent histories reject the import. The older
SDK 3.2.0 adapter remains for offline legacy calculations only. The importer does
not fetch account data or place orders. See the [current REST input guide](docs/m14_current_rest.md).
Raw sources, personal transaction data and delivery receipts belong in durable
private storage **outside this public checkout**.

The separate results publisher produces daily, week-to-date and cumulative
summaries. Sending real results requires an independently reconciled live history,
a tested dedicated results webhook, visual channel confirmation and explicit
delivery. A durable outbox prevents automatic duplicate retries, including after
uncertain network outcomes. **No results schedule or live publishing is enabled.**

M14 remains in progress pending current live schema/fee validation, actual account
reconciliation, and authorized results-webhook testing and deployment. See the
[M14 operating guide](docs/m14_performance.md) for input formats, metric definitions,
tests and remaining acceptance requirements. M13 and M15 are separate work.

A manual-only M14 results connection-test workflow is prepared. It sends a labeled
connection message with no financial figures; it has no scheduled or push trigger.
No connection test or live financial publication is activated by preparing it.

## Safety and scope

StatRally is a research and decision-support project, **not** a guarantee of profitability. Historical accuracy alone is not evidence of positive expected value. Private model code, tokens, webhook URLs, and individual account/trading details must never be exposed through this public repository.
