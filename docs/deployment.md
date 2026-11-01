# Deployment guardrails

This public repository currently contains only a no-secret scaffold and unit test.

The original `statrally-soccer-btts` repository stays private. Do not copy its Git history, research datasets, model weights, notebooks, local configuration, or private credentials here.

Future public deployment requires a file-by-file review and specific opt-in for publishing model artifacts. Use GitHub Actions repository secrets for tokens, minimize job permissions, and never log secret values. Workflow logs and published outputs may be publicly readable.

No scheduled jobs or live betting picks are enabled. Before scheduling, validate odds and fixture sources, model reliability, and deployment permissions. No profitable-edge claims without evidence.

## Milestone 12 public runner integration (November 1, 2026)

A read-only scanner workflow exists at `.github/workflows/m12-kalshi-scanner.yml`. It runs at 13:10, 18:10 and 23:10 UTC **only if** the public repository Actions variable `ENABLE_STAT_RALLY_SCANS` equals `true`. With the variable absent/disabled, the job is skipped before runner allocation.

It checks out `stelladeecoder/statrally-soccer-btts` directly into the ephemeral runner using a GitHub Actions secret named `STAT_RALLY_PRIVATE_READ_TOKEN`. Create a short-lived or narrowly scoped fine-grained GitHub personal access token with **Contents: read-only** permission restricted to the private repository, then add it under the public repository Actions secrets. Do not paste tokens in chat, logs, or source control. Rotate/revoke it when no longer needed. This does **not** publish the private repository: the code only exists in the runner workspace. Note that public workflow logs may be public; the scan prints bounded research-only status.

The private entrypoint `src/m12_operational_scan.py` collects at most three Kalshi market quotes and looks for an exact reviewed fixture manifest at `config/m12_reviewed_fixtures.json`. If missing, it generates **No Bet**. The manifest is a JSON list of full, independently reviewed Kalshi-to-ESPN event/team ID mappings, each with `reviewed: true`; do not fabricate mappings from ticker fragments. Independently verified mapping, currently available markets, and a reliable model remain separate acceptance checks.

**Not activated or certified yet:** No secret/variable has been set by this change, and no runner job/test has been executed. M12 still requires evidence of a successfully completed public-runner job and reviewed, current fixture/provider identities. GitHub API access provided to the assistant cannot configure Actions secrets or dispatch workflows.
