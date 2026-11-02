# M13 — Experimental BTTS beta publishing

**November 2, 2026:** Scheduled *paper-only* dispatch is committed to the public repository. It is not a production betting recommendation system. No live Discord beta prediction has been independently verified.

## Pipeline

1. Public Actions workflow `.github/workflows/m13-beta-paper-picks.yml` runs at **08:23, 11:23 and 14:23 America/Chicago**, plus manual dispatch.
2. It checks out the public automation and private model repositories, then runs `src/m13_beta_export.py` in the private engine. The exporter uses **independently reviewed market-to-ESPN fixture mappings**, an uncalibrated historical Poisson probability, and current verified Kalshi order-book asks. It requires a live pre-kickoff fixture and a quote no older than 15 minutes.
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
- Deduplication is conservative: workflows are serialized using a dedicated Actions concurrency group, and issues are checked before posting. If public Issues history exceeds one response page, dispatch blocks rather than risk a duplicate.
- Issue reservation protects against uncertain network delivery by refusing to retry. An Issue with a reservation but no delivery-confirmation comment needs manual Discord inspection.
- The postgame result ingestion and grading automation is **not implemented**; outcomes must remain pending until verified through a separate source.
- This is a public repository: GitHub Issue paper signal records are publicly visible. No sensitive account data, personal transactions, or webhook URLs should be stored in Issues.
- Real picks use independent model/fee qualification gates; never use this workflow to bypass them.

## Verification

Public Actions run [41500697967](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41500697967) passed **15 offline beta formatter/dispatcher tests**. Private Actions run [41500982555](https://github.com/stelladeecoder/statrally-soccer-btts/actions/runs/41500982555) passed **4 exporter tests** using synthetic evaluations. Neither test confirms an unattended live Discord beta pick or live real-market availability.

**Next acceptance checks:** confirm the first eligible scheduled run creates an Issue and Discord beta signal, with matching contents and no duplicates. Add postgame grading before interpreting results.

## November 2 — Postgame grading and performance logging

`src/m13_beta_grading.py` grades **only completed** ESPN matches using the saved ESPN event ID, exact home/away identities, and kickoff timestamp. Draws and zero-goal scorelines are handled by BTTS rules, while missing events, mismatched teams, moved kickoffs and incomplete games are rejected or left pending. It provides aggregate graded count, W/L, hit rate and pending count; these are experimental paper-prediction metrics, never actual Kalshi profit.

`src/m13_beta_grade_issues.py` and `.github/workflows/m13-beta-grading.yml` perform daily grading at **5:41 PM Central**, writing durable outcome comments back to qualifying paper Issue records. Records require proof of a successful Discord delivery comment. Historical counts are reconstructed from the Issues checked, and only confirmed final matches count. An ungraded signal remains pending. No actual trading statements or account credentials are accessed.

**Current blockers, not completed:** Across the eight watchlist competitions, the private market allowlist presently covers only candidate EPL, MLS and Liga MX BTTS series, and team aliases for the private historical Poisson forecast currently cover only a handful of EPL clubs. Automatic Kalshi-to-ESPN discovery with strict identity verification and broader reviewed team-history mapping are **not yet implemented**. Existing production beta exporter still uses explicit reviewed fixture manifests. Scheduled delivery cannot be claimed verified until an actual scheduled workflow posts a real eligible signal and creates its log. Offline grader unit tests passed in public Actions run [41502401814](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41502401814); end-to-end scheduled grading and live ESPN results have not been independently confirmed.
