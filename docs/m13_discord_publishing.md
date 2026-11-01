# Milestone 13 — Discord publishing (in progress)

The public automation repo owns publishing; private `statrally-soccer-btts` continues to own research, fixture verification, model probabilities and Kalshi EV.

## Implemented
- `src/m13_discord_publish.py` consumes the private scanner JSON and formats a non-actionable **No Bet** research message. It fails closed on missing/invalid scan evidence and refuses to advertise unsupported qualified selections.
- Dry-run is the default; no Discord HTTP calls occur without `--send`.
- Seven offline regression tests are included in `tests/test_m13_discord_publish.py`.
- The existing public scan workflow builds a draft after each successful private-engine run. Publishing runs only if the Actions variable `ENABLE_DISCORD_POSTS` is `true` and the secret `STATRALLY_DISCORD_WEBHOOK` is present.
- The separate master scan gate `ENABLE_STAT_RALLY_SCANS` must also be `true`. Both switches default to disabled when absent.

## Activation (do not activate before testing)

1. Create a Discord webhook in the intended Discord channel (Server Settings > Integrations > Webhooks, or channel integrations depending on permissions).
2. Store the URL in the **public** repository Actions secret named `STATRALLY_DISCORD_WEBHOOK`. Never paste it into chat or source code. Treat the URL like a password.
3. Run `python -m unittest discover -s tests -p 'test_m13_discord_publish.py' -v` locally, or manually dispatch the public `validate.yml` workflow after reviewing costs.
4. Keep `ENABLE_DISCORD_POSTS` absent/false until one permitted test delivery can be confirmed. Then set it to `true`; `ENABLE_STAT_RALLY_SCANS` must also be `true` for the scheduled workflow to run.
5. Watch the first scheduled job and Discord channel and disable the variable immediately if duplicate, unexpected, or inappropriate messages appear.

## Remaining M13 acceptance work

- Verify the offline tests actually execute successfully and the workflow can create a valid dry-run draft.
- Verify one real Discord delivery via a controlled, explicitly enabled run.
- Establish formatting and authorization for **approved** model-backed research candidates before allowing actionable predictions; the current model is uncalibrated, so the publisher intentionally never advertises a qualifying bet.
- Avoid repeated No Bet messages if there is no change; deduplication/rate-limit policy remains to be implemented.

Do not blend this with M14 realized-P&L tracking or M15 web design. Scheduled scanner remains intentionally gated; do not enable it solely to test formatting.

## November 1 progress

The public scanner workflow now runs Discord draft formatting after the private M12 scan. Automatic webhook delivery uses an independent `ENABLE_DISCORD_POSTS` gate and `--suppress-no-bet` to avoid repeated routine No Bet messages. Eight targeted checks of an equivalent local stdlib publisher implementation passed without any GitHub Actions execution or webhook request. The full repository test suite has **not** been executed in GitHub. The webhook has **not** been configured or tested; M13 remains in progress. The current publisher does not authorize betting selections or attempt trade execution.

## Verified public CI acceptance — November 1, 2026

Temporary PR #3 one-shot GitHub Actions run `41356210451` **passed**. All nine public-repository tests passed. CLI rendered the generic No Bet research message in dry-run, then confirmed suppression with `DISCORD_SKIP_NO_QUALIFIED_SELECTIONS`. No Discord HTTP request was made. The test pull request was closed **without merging**, preserving minimal routine CI overhead. The existing scheduled M12/M13 workflow was also fixed to install `pandas` before invoking the private model bridge.

**M13 still in progress:** `STATRALLY_DISCORD_WEBHOOK` must be configured securely and a controlled real delivery independently verified. `ENABLE_DISCORD_POSTS` and `ENABLE_STAT_RALLY_SCANS` stay off unless explicitly activated by the repository owner. No betting candidate publications are approved.

## One-time webhook acceptance — November 1, 2026

Temporary verification PR #4 ran GitHub Actions run `41358959877`, which completed successfully: the publisher unit tests passed and the webhook POST command returned successfully. PR #4 was closed without merging the test workflow. The intended destination is `#match-watchlist`; the GitHub success verifies successful webhook delivery, not independent visual confirmation of the destination channel. **Scheduled scans and posts remain gated and disabled**. The remaining Step 5 scope is channel-specific watchlist formatting and picks routing, suppression of redundant posts, and validation of the actual combined scheduled workflow before turning on schedules. A second independently scoped picks-channel webhook would be required to publish to `#btts-picks`.

## Combined workflow verification — November 1, 2026

One-time public Actions run `41359571503` passed. It checked out both repositories, installed the private engine dependency, passed 13 public automation tests, scanned live Kalshi markets, generated a verified Manchester United vs Aston Villa watchlist draft, and suppressed any picks-channel message because no approved selection evidence existed. Temporary PR #6 was closed without merging; **no live Discord message** was sent during this run. The earlier controlled real webhook delivery was independently successful in run `41358959877`.

**Operational controls:** The regular workflow remains gated by `ENABLE_STAT_RALLY_SCANS`. Daily Discord watchlist posts are additionally gated by `ENABLE_DISCORD_POSTS`, restricted to the 13:10 UTC cron. Both are still disabled unless configured by the repository owner. It does not implement qualified-picks delivery because the model is not approved and a separate picks-channel webhook has not been configured. M13's safe research-only workflow is technically tested; full channel routing and unattended scheduled delivery have not been verified in production.

## November 1 — Picks publishing safety verification

The separate `render_approved_picks` formatter now accepts only a `schema_version=1` envelope with `approval=verified`, `model_calibrated=true`, 1–3 picks and positive net EV with reviewed fixture and fee flags. This is a **formatting and safety contract only**: the private research scanner never emits this envelope, and there is no automatic picks-webhook routing. Seventeen public-unit tests passed in GitHub Actions run `41363005670`. The one-off PR #10 was closed without merging.

The independent multi-league fixture-watchlist workflow `.github/workflows/m13-daily-watchlist.yml` is committed with a 7:05 AM America/Chicago schedule and has no enable-variable gate. However, the first unattended scheduled delivery and its destination-channel verification remain unobserved. Scheduled workflows may be delayed or skipped by the hosting service. A distinct `#btts-picks` webhook is still needed before real picks are routed there, but **no live publishing** can be approved until the underlying model independently qualifies selections. M14 settlement/P&L tracking is not part of M13.
