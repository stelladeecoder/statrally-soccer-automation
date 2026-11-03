# M13 — Experimental BTTS beta publishing

> **Current audit:** see [schedule, delivery and genuine lifecycle evidence](m13_operational_audit.md).
> Pick times are **8:23 AM and 2:23 PM Central**. No unattended scheduled execution
> or completed prediction-result lifecycle has been verified. The audit branch
> expands grading to all 13 competitions; older pipeline details below are historical.

> **Current source update — November 2, 2026:** The scheduled M13 BTTS paper-picks workflow now uses the **Polymarket US** private exporter, not the Kalshi export path described below. The legacy M12 Kalshi scan schedule is disabled. Private live read-only exporter verification passed for one explicitly reviewed EPL fixture, and public full-suite validation passed **80 tests**. A controlled actual scheduled-workflow dispatch [run #41562467939](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41562467939) completed successfully: it recorded **BETA_ALREADY_RECORDED**, so no second Discord post was sent for the same previously published fixture. New Polymarket-to-Discord delivery for a different fixture remains unverified. **Historical Kalshi sections below document previous M12/M13 behavior and must not be read as current provider configuration.** No trading is enabled.

**November 2, 2026:** Scheduled *paper-only* dispatch is committed to the public repository. Manual real-source beta delivery and a separate results connection test now have successful Actions runs and durable delivery evidence (see the latest verification below). This is not a production betting recommendation system; unattended scheduled posting and a completed beta outcome remain unverified.

## Pipeline

1. Public Actions workflow `.github/workflows/m13-beta-paper-picks.yml` is configured for **08:23 and 14:23 America/Chicago**, plus manual dispatch.
2. It checks out the public automation and private model repositories. Public `src/m13_beta_capture.py` calls the existing private exporter/discovery/evaluator, with a consistent conservative scan clock and observed provider responses. The exporter uses **independently reviewed market-to-ESPN fixture mappings**, an uncalibrated historical Poisson probability, and current verified Kalshi order-book asks. It requires a live pre-kickoff fixture and a quote no older than 15 minutes. Source transport/schema/pagination failures cannot masquerade as a successful zero-signal scan.
3. It emits only model-generated YES/NO paper signals for eligible verified fixtures; **0 signals is normal and posts nothing**. There is no fabricated fallback or forced daily pick. The existing private reviewed mapping manifest may contain very few upcoming matches; additional independently reviewed fixture mappings are required for broad coverage.
4. Public `src/m13_beta_signals.py` validates price, probability, identities, fixture start, quote freshness, and an explicit experimental, no-trades contract.
5. Public `src/m13_beta_dispatch.py` uses the workflow's scoped `issues:write` GitHub token to create a **durable public GitHub Issue reservation** before attempting Discord delivery. An existing identity or incomplete issue-history lookup suppresses re-posts. Following a successful Discord POST it comments on the Issue. An ambiguous failure leaves a reserved Issue requiring operator review, never an automatic retry.
6. The beta post uses the existing `STATRALLY_PICKS_DISCORD_WEBHOOK` secret and labels the message **BETA PAPER PICKS — EXPERIMENTAL**. The verified-picks publisher remains independent and fail-closed.

Each reserved Issue stores match identity, side, model estimate, quoted price and post state. Its outcome remains **pending**, for a later independent historical result evaluation. This is a paper signal log, NOT Kalshi actual-trading profit/loss (M14). No orders or real wagers are placed.

## Operational requirements and limitations

- GitHub Issues must be enabled on the public automation repository; the schedule must be allowed to use `issues: write`. If creation fails, **the Discord post is blocked**.
- Real beta recommendations remain explicitly experimental; current model probabilities are not calibrated and have no proven betting edge.
- Current reviewed Kalshi/ESPN mappings and team-name aliases are intentionally narrow. Not every scheduled run will produce a signal. **Do not infer zero signals means the workflow failed.**
- Source mappings are hand-reviewed for market identity and kickoff; the beta model chooses the higher-probability YES or NO prediction, not necessarily positive net EV. The post is a paper hypothesis, not a profitable bet.
- Deduplication is conservative: workflows are serialized using a dedicated Actions concurrency group, and complete Issues history is checked up to 20 pages of 100 records. Bounds and malformed pagination fail closed. Equivalent UTC kickoff representations share one identity. Freshness is rechecked after durable reservation and immediately before posting.
- Issue reservation protects against uncertain network delivery by refusing to retry. An Issue with a reservation but no delivery-confirmation comment needs manual Discord inspection.
- The postgame ingestion/grading automation described below publishes only independently verified regulation-time paper outcomes; unresolved, canceled, extra-time and shootout cases remain pending for review. A results connection test is not an actual graded outcome.
- This is a public repository: GitHub Issue paper signal records are publicly visible. No sensitive account data, personal transactions, or webhook URLs should be stored in Issues.
- Real picks use independent model/fee qualification gates; never use this workflow to bypass them.

## Verification

Public Actions run [41500697967](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41500697967) passed **15 offline beta formatter/dispatcher tests**. Private Actions run [41500982555](https://github.com/stelladeecoder/statrally-soccer-btts/actions/runs/41500982555) passed **4 exporter tests** using synthetic evaluations. Neither test confirms an unattended live Discord beta pick or live real-market availability.

**Next acceptance checks:** confirm the first eligible scheduled run creates an Issue and Discord beta signal, with matching contents and no duplicates. Add postgame grading before interpreting results.

## November 2 — Postgame grading and performance logging

`src/m13_beta_grading.py` grades **only completed** ESPN matches using the saved ESPN event ID, exact home/away identities, and kickoff timestamp. Draws and zero-goal scorelines are handled by BTTS rules, while missing events, mismatched teams, moved kickoffs and incomplete games are rejected or left pending. It provides aggregate graded count, W/L, hit rate and pending count; these are experimental paper-prediction metrics, never actual Kalshi profit.

`src/m13_beta_grade_issues.py` and `.github/workflows/m13-beta-grading.yml` perform daily grading at **5:41 PM Central**, writing durable outcome comments back to qualifying paper Issue records. Records require proof of a successful Discord delivery comment. Historical counts are reconstructed from the Issues checked, and only confirmed final matches count. An ungraded signal remains pending. No actual trading statements or account credentials are accessed.

**Current blockers, not completed:** Across the eight watchlist competitions, the private market allowlist presently covers only candidate EPL, MLS and Liga MX BTTS series, and team aliases for the private historical Poisson forecast currently cover only a handful of EPL clubs. Automatic Kalshi-to-ESPN discovery with strict identity verification and broader reviewed team-history mapping are **not yet implemented**. Existing production beta exporter still uses explicit reviewed fixture manifests. Scheduled delivery cannot be claimed verified until an actual scheduled workflow posts a real eligible signal and creates its log. Offline grader unit tests passed in public Actions run [41502401814](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41502401814); end-to-end scheduled grading and live ESPN results have not been independently confirmed.

## November 2 — Strict auto-discovery and paper performance expansion

The private research repo now includes `src/m13_beta_fixture_discovery.py` and `src/m13_beta_auto_discovery.py`. The scheduled exporter invokes `--discover` to inspect permitted Kalshi BTTS market series and check exact, ordered `Home vs Away` names against unique ESPN event IDs, home/away team IDs, league and bounded kickoff/market-close dates. Abbreviations, reversed teams, ambiguous matches or unsupported series are rejected. The existing manual-reviewed fixture mapping file remains supported. Only the **three allowlisted BTTS series (EPL, MLS, Liga MX)** are presently eligible for auto-discovery; the other five watchlist leagues do not yet have validated Kalshi BTTS series identifiers or usable model coverage. The forecast bridge now allows **exact historical names**, but does not guess aliases.

`src/m13_beta_grading.py` additionally computes a Brier score for graded paper predictions with valid probability inputs. The scheduled `src/m13_beta_grade_issues.py` updates a public GitHub Issue called **StatRally BETA | experimental paper performance**, only when there are verified completed predictions. These stats are *hypothetical model accuracy*, not P&L. GitHub Issues is the durable record and the dashboard is a calculated snapshot, not a private account data store.

Private unit verification [41503118695](https://github.com/stelladeecoder/statrally-soccer-btts/actions/runs/41503118695) **passed 9 tests**, including exact-match and ambiguity rejection. Public beta grading tests passed in Actions [41502811169](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41502811169). **Unattended scheduled Discord posting and current real-market mapping coverage are still not independently verified.** The paper-grading job is scheduled; this does not establish that any real grade was written to an Issue. Neither workflow places trades.

## November 2 — Live beta deployment verification and hardening

- Initial main picks run [41505582351](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41505582351) completed without a paper record. Inspection found the exporter's clock could reject newly observed quotes as future, and provider errors could be suppressed into an empty list. The public capture integration now supplies a common scan/evaluation clock without weakening quote freshness or model/fixture gates. Actual posting rechecks wall-clock freshness after reservation.
- Corrected live picks run [41508988525](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41508988525) succeeded. Sanitized Checks annotations show **5 successful observed Kalshi requests, 16 successful ESPN requests, zero provider/collection failures, one successful evaluation and one eligible signal**. Automatic mapping discovery added zero mappings; the eligible fixture came from an existing independently reviewed mapping. Counts describe observed requests/records, not unique matches or comprehensive league coverage.
- [Issue #20](https://github.com/stelladeecoder/statrally-soccer-automation/issues/20) records the genuine experimental **BTTS YES paper prediction for Manchester United vs Aston Villa, November 8 at 16:30 UTC**. Its bot-authored delivery receipt matches the original prediction hash and predates kickoff. Discord acceptance is verified; no profitable-edge or real-money recommendation is claimed.
- The results connection workflow was dispatched **once**: [41505588396](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41505588396). Its guarded single POST succeeded, meaning Discord returned HTTP 200/204 for the clearly labeled connection-only message. No financial figures or fabricated outcomes were sent. Destination-channel visual confirmation remains a human check.
- Public full-suite CI [41508981492](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41508981492) passed the **77-test** suite. Synthetic regression tests cover real-source diagnostics, clock consistency, equivalent-date duplicates, durable reservations, failed sends, complete comment history, prediction hash binding, pending counts and verified regulation-time grading.
- Branch grading verification [41508993161](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41508993161) passed without inventing an outcome. The newly posted fixture is in the future; it must remain pending until a matching independent full-time score exists.

The grader now requires Actions-bot reservations and delivery receipts created
before kickoff. Each receipt contains a hash of the exact signal; edits to the
signal or proof after kickoff cannot certify a prediction. Unknown signal fields
are rejected before any public Issue write, preventing unintended private fields
from entering paper logs. Complete comments are paged before duplicate checks.

Outcome comments, results reservations and successful Discord confirmations are
durable. A failed/uncertain results request fails the workflow, retains its
reservation and blocks subsequent sends pending operator review. Source failures
leave matches pending and preserve the previous dashboard rather than publishing
misleading reduced statistics. Changed final outcomes conflict with immutable
recorded grades and require review. The dashboard uses real newlines and counts
delivered future/unverified matches as pending.

Remaining acceptance: observe the first unattended scheduled executions; visually
confirm channel destinations; independently grade a genuinely completed beta
prediction; expand only reviewed market/model coverage. Raw Actions log downloads
are restricted by this cloud environment's access to GitHub log-storage hosts;
run/step conclusions, sanitized Checks annotations and durable Issue receipts are
available independently. M14 PR #13 stays draft and unmerged. No automated trading
or actual financial-result publishing is enabled by this beta deployment.
