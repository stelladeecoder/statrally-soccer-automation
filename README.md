# StatRally | Soccer Data Analytics

**The Edge Is in the Data.**

StatRally turns soccer data across **13 competitions** into match watchlists, experimental predictions, and tracked results delivered through Discord.

This portfolio project brings together **data engineering, statistical analysis, model evaluation, automation, and reporting**. Its focus is turning inconsistent information into useful updates while clearly showing what is known, uncertain, or incomplete.

## The problem

Soccer information arrives in different formats. Team names can vary, kickoff times can change, and some matches have missing information. A useful analytics project needs to handle these problems before presenting a prediction.

StatRally organizes that information into a simple experience: see the day's matches, review eligible practice predictions, and follow confirmed outcomes.

## What I built

- **Data preparation:** combined match information from multiple sources, standardized names and times, and added checks for missing or conflicting records.
- **Analysis and evaluation:** explored historical results, developed probability estimates, and compared predictions with simple benchmarks.
- **Automated reporting:** created scheduled match lists, experimental paper-pick updates, and result tracking through Discord.
- **Quality controls:** added automated tests, duplicate prevention, and checks that keep unconfirmed results separate from completed outcomes.
- **Accessible communication:** translated analytical output into messages that people without a technical background can understand.

## Tools and skills

| Tool | What it supports |
| --- | --- |
| **Python** | Data processing, analysis, and automation |
| **pandas and NumPy** | Cleaning, organizing, and analyzing match data |
| **scikit-learn and SciPy** | Statistical research and historical model evaluation |
| **Git and GitHub** | Version control and project documentation |
| **GitHub Actions** | Scheduled tasks and automated checks |
| **Python unittest** | Testing data validation and reporting behavior |
| **Discord** | Delivering readable updates to users |

Skills demonstrated include data cleaning, combining information from different sources, working with time zones, evaluating predictions, testing software, and communicating findings.

## Public project and private research

This public repository contains the reporting, automation, and testing work available for review.

A separate private repository holds the underlying analytical research and prediction development. The public component presents the resulting updates, while the research implementation remains private.

This README explains the project's purpose, tools, and demonstrated work without publishing proprietary methods, connection details, or setup instructions.

## Evidence and lessons learned

A verified project run passed **116 automated checks**. Controlled tests also successfully delivered real match-list and experimental paper-pick messages to Discord.

Searches cover all 13 competitions, but this does not mean every competition produces a pick. Missing information, unresolved team identities, and limited historical data can prevent a match from qualifying.

Historical evaluation has not established a reliable predictive advantage over simple benchmarks. That finding informs the project: predictions remain experimental, uncertainty is stated clearly, and practice results are kept separate from actual betting profits.

**Current stage:** working match-list and paper-pick delivery, with broader coverage and long-term performance still under evaluation.

## The Discord experience

StatRally focuses on **Both Teams to Score (BTTS)**:

- **YES:** both teams score at least one goal. A 1–1 result is an example.
- **NO:** at least one team does not score. A 2–0 result is an example.

Predictions cover regular match time, including stoppage time, but exclude extra time and penalty shootouts.

| Channel | What users see |
| --- | --- |
| `#match-watchlist` | The day's soccer matches and kickoff times. A listed match is not automatically a pick. |
| `#btts-picks` | Experimental BTTS YES or NO paper picks for upcoming matches. |
| `#btts-results` | Outcomes for recorded paper picks once the final score is confirmed. |

**Paper picks are practice predictions.** The bot does not place bets or use anyone's money. Messages marked **TEST** check delivery and presentation; they are not official tracked picks.

Each pick identifies the match, kickoff time, and prediction. A displayed percentage is an estimated chance, not a guarantee. Market prices can change. Up to three paper picks are shared per check; some checks produce none.

### Expected daily updates

All times are **Central Time**.

| Time | Update |
| --- | --- |
| 7:17 AM | Daily match list |
| 8:23 AM and 2:23 PM | Checks for new paper picks |
| 11:55 PM | Checks for completed results |

Updates may arrive late. Results remain pending until confirmed.

### Competition coverage

Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie, Liga Portugal, Brasileirão Série A, MLS, Liga MX, Argentina Primera División, UEFA Champions League, and UEFA Europa League.

Reported wins and losses describe tracked practice predictions, not actual betting profits. Betting involves risk, and no prediction guarantees a win.
