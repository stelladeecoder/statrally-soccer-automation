# Deployment guardrails

StatRally reports experimental soccer predictions. Polymarket US is the active
market-data provider. The retained Kalshi scanner is manual-only historical work;
there is no active-provider fallback or automated trading.

Research code, datasets, model internals and credentials stay private. Public
workflow logs, Issues and Discord messages must contain only reviewed reporting
fields. Deployment configuration and webhook provisioning are documented privately.

See the [operational audit](m13_operational_audit.md) for configured schedules,
successful manual tests and the remaining unattended-operation evidence.

The three reporting workflows use `America/Chicago` schedules and separate
concurrency groups. Picks/results require Issues write access for durable
reservations and receipts. The audit branch adds this protection to watchlists.

## Delivery and results safeguards

Reservations precede Discord delivery. A failed send or missing durable receipt
requires review before retrying: the message may already have arrived. Never
delete a reservation to force another send. HTTP acceptance does not establish
visual confirmation of the channel destination.

Public PR tests have no webhook bindings. Read-only coverage audits send no
messages. Deliberate Discord tests must be clearly labeled and must not enter
official prediction reservations or cumulative performance.

Only genuine bot-reserved predictions with a hash-bound pre-kickoff delivery
receipt enter grading. New records carry explicit ESPN event/team IDs; legacy
records retain exact-name checks. Regulation-time final scores are required.
Postponed, cancelled, suspended, extra-time and penalty outcomes do not become
ordinary BTTS wins/losses. Changed kickoffs, conflicting predictions and corrected
scores require review. Source failures preserve the previous dashboard and fail
the run. Uncertain results delivery blocks an automatic resend.

Practice accuracy and probability scoring stay separate from account
transactions, fees and financial returns. M14 PR #13 remains draft and unmerged;
no actual financial publishing is enabled.
