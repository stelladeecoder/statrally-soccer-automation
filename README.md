# StatRally | Soccer Automation

**The Edge Is in the Data.**

Public GitHub Actions and Discord-delivery infrastructure for **StatRally**, a soccer **Both Teams to Score (BTTS) Yes/No** research project.

> **Status (November 1, 2026):** Milestones **1–12 complete**; **M13 (Discord automation) in progress**. The daily fixture workflow is committed and scheduled, and both Discord webhooks have been tested. **The first unattended daily watchlist post has not yet been verified.** No live betting recommendations or automated trades are authorized.

## What this public repository does

- **Daily match watchlist:** fetches fixtures for the Premier League, La Liga, Bundesliga, Serie A, Ligue 1, MLS, Liga MX, and UEFA Champions League.
- **Discord #match-watchlist:** groups matches by league and displays kickoff times in **America/Chicago**. The dedicated workflow runs at **7:05 AM Central daily**, subject to GitHub Actions scheduling delays.
- **Discord #btts-picks:** a *separate* webhook is connected and its **one-time test message was visually confirmed in Discord**. A guarded formatter for verified selections exists, but **real picks publishing is not enabled**. The private research scanner cannot currently produce approved selections.
- **Read-only research scans:** the separate Kalshi scanner workflow remains gated by the `ENABLE_STAT_RALLY_SCANS` repository variable. Running a scan does not mean placing a bet.

The watchlist is **fixtures only**, with no EV, odds, No Bet decisions, or player recommendations. Not every competition has games every day. Discord team/league logos and richer embeds are deferred to a later enhancement.

## Experimental beta paper picks (M13)

The separate [beta paper picks workflow](.github/workflows/m13-beta-paper-picks.yml) is scheduled at **08:23, 11:23 and 14:23 America/Chicago**. It runs the private read-only research exporter and publishes only eligible, independently fixture-mapped experimental BTTS YES/NO signals to the existing picks channel. **No verified edge, automated trading, or real-money picks are enabled.** The model remains uncalibrated.

A public GitHub Issue is reserved before each Discord attempt to record and deduplicate paper signals. Outcomes remain pending until independently checked. No qualified signal means **no post**. Current reviewed mappings are limited; unattended live beta delivery has not been confirmed. See [beta deployment notes](docs/m13_beta_publishing.md).

## Beta grading and accuracy tracking

The [paper grading workflow](.github/workflows/m13-beta-grading.yml) checks completed ESPN fixtures and adds verified BTTS outcomes to the recorded beta-signal Issues. Once independently graded signals exist, it maintains a public **StatRally BETA | experimental paper performance** Issue showing wins, losses, hit rate and Brier score. These are **paper prediction metrics, not real transaction P&L**. Actual Kalshi performance accounting remains in M14.

The [beta scan](.github/workflows/m13-beta-paper-picks.yml) now attempts strict Kalshi-to-ESPN fixture discovery for the **currently allowlisted EPL, MLS and Liga MX BTTS series**, and uses explicit manually reviewed fixture mappings as well. Team roles, exact names, event IDs and kickoff proximity must agree. Other watchlist leagues require separately verified BTTS market identifiers and supported historical models. A scheduled workflow does **not** guarantee eligible picks or prove Discord delivery; the first unattended beta prediction has not yet been independently confirmed.

## Repository boundaries

| Repository | Responsibility | Visibility |
| --- | --- | --- |
| `stelladeecoder/statrally-soccer-btts` | Research data, model/validation, odds and Kalshi EV logic, fixture collection | Private |
| `stelladeecoder/statrally-soccer-automation` | Public-safe workflows, Discord formatting, guarded publishing, tests | Public |

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

Run the offline unit suite with Python 3.12:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

**Verified:** all **17 tests passed** in GitHub Actions run [41363527302](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41363527302). A controlled message to `#btts-picks` was also confirmed by the server owner. These checks do **not** establish a validated betting edge.

## Development roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| M1–M10 | Soccer data pipelines, feature engineering, model research and validation | Complete |
| M11 | Historical evaluation and fee-aware odds/EV research | Complete |
| M12 | Read-only live Kalshi integration | Complete |
| **M13** | Multi-league Discord watchlist and guarded picks-channel integration | **In progress** |
| M14 | Actual settled positions, fees, win/loss, profit/loss and ROI; `#btts-results` | Planned |
| M15 | Mobile-friendly public dashboard with Discord and referral links, hosted on GitHub Pages | Planned |

### M13 remaining acceptance

1. Verify the **first unattended** scheduled `#match-watchlist` post and its fixture/time accuracy.
2. Keep real `#btts-picks` selections **disabled** until the private engine provides independently validated, qualified recommendations and an approved publishing workflow.

**Future enhancement:** team crests, league logos, and richer Discord embeds after reliable plain-text delivery is confirmed.

## Safety and scope

StatRally is a research and decision-support project, **not** a guarantee of profitability. Historical accuracy alone is not evidence of positive expected value. Private model code, tokens, webhook URLs, and individual account/trading details must never be exposed through this public repository.
