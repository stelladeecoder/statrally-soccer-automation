# StatRally Soccer Automation

Public-safe remote automation framework for the StatRally soccer BTTS research project.

**Current status:** Infrastructure scaffold only. No live odds, Discord posting, scheduled market scans, or betting recommendations are enabled.

## Development boundaries

- Private research and model development remain in `statrally-soccer-btts`.
- Only reviewed public-safe automation code should be deployed here.
- Store API and Discord credentials in GitHub Actions Secrets, never files or logs.
- Historical model results do not currently demonstrate a validated positive betting edge.

## CI

The `Validate public automation scaffold` workflow runs a minimal Python unit test with GitHub-hosted standard runners. It does not access private repositories or APIs.

## Next steps

Complete private Milestones 9–11 validation, then deploy verified live-fixture/odds readers and guarded Discord reporting for Milestones 12–14. See `docs/deployment.md`.
