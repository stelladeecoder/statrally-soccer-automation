# StatRally | Soccer Data Analytics

**The Edge Is in the Data.**

StatRally is a data analytics portfolio project that turns soccer data into match watchlists, experimental predictions, and tracked results shared through Discord.

The project demonstrates data collection, cleaning, statistical analysis, model evaluation, automated reporting, and clear communication of uncertainty.

It focuses on **Both Teams to Score (BTTS)**:

- **YES:** both teams score at least one goal.
- **NO:** at least one team finishes without scoring.

For example, a 1–1 score is BTTS YES. A 2–0 score is BTTS NO. These predictions cover regular match time, including stoppage time, but exclude extra time and penalty shootouts.

## Project highlights

- **Data engineering:** combine match information from multiple sources, standardize names and times, and check records for missing or conflicting information.
- **Analytics and modeling:** explore historical results, develop probability estimates, and compare predictions with simple benchmarks.
- **Quality and reliability:** test data checks, prevent duplicate records, and keep unconfirmed results separate from completed outcomes.
- **Communication:** turn analytical output into readable updates for people without a technical background.

A verified project test run passed **116 automated checks**, and controlled match-list and paper-pick delivery tests succeeded in Discord. These checks demonstrate software validation; they do not establish profitable predictions.

## Tools used

| Tool | Role in the project |
| --- | --- |
| **Python** | Data processing, analysis, and automation |
| **pandas and NumPy** | Preparing, organizing, and analyzing match data |
| **scikit-learn and SciPy** | Statistical research and historical model evaluation |
| **Git and GitHub** | Version control and project documentation |
| **GitHub Actions** | Scheduled tasks and automated checks |
| **Python unittest** | Testing data validation and reporting behavior |
| **Discord** | Sharing match lists, paper picks, and results |

This overview describes the work and tools at a portfolio level. Proprietary methods and setup instructions are not included.

## Your Discord guide

| Channel | What you will find |
| --- | --- |
| `#match-watchlist` | The day's soccer matches and kickoff times. A listed match is not automatically a pick. |
| `#btts-picks` | Experimental BTTS YES or NO paper picks for upcoming matches. |
| `#btts-results` | Results for previously recorded paper picks once the final score is confirmed. |

**Paper picks are practice predictions.** The bot does not place bets or use your money. Messages marked **TEST** check that information displays correctly; they are not official tracked picks.

## When to check

All times are **Central Time**.

| Time | Expected update |
| --- | --- |
| 7:17 AM | Daily match list |
| 8:23 AM and 2:23 PM | Checks for new paper picks |
| 11:55 PM | Checks for completed results |

Updates can arrive late. A picks check may produce no message when nothing new meets the requirements. Results stay pending until they can be confirmed.

## Understanding a pick

Each paper pick identifies the match, kickoff time, and BTTS YES or NO prediction. A percentage is an estimated chance, not a guarantee. Any displayed market price can change.

StatRally shares up to three paper picks per check. There is no requirement to produce a pick every day.

## Competition coverage

StatRally checks 13 competitions: Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie, Liga Portugal, Brasileirão Série A, MLS, Liga MX, Argentina Primera División, UEFA Champions League, and UEFA Europa League.

**Checking a competition does not guarantee a pick.** Some matches lack enough reliable information. A match may appear on the watchlist without appearing in the picks channel.

## Current stage

StatRally is experimental and still being improved. Match-list and paper-pick messages have been tested in Discord. Coverage is still growing, and reliable long-term prediction performance has not been established.

Reported wins and losses describe tracked practice predictions. They do not represent actual betting profits.

Betting involves risk. No prediction guarantees a win.
