# Automatic posting recovery — November 3, 2026

## Observed problem

The 4:17 AM Central watchlist did not get a scheduled run. Controlled manual delivery worked. Resetting the original workflows and trying short cron checks did not establish working native cron delivery. The underlying GitHub scheduling cause was not identified.

## Replacement

`.github/workflows/statrally-scheduler.yml` owns scheduling. The three M13 workflows are reusable posting jobs and remain manually runnable; their independent daily cron entries were removed.

The coordinator converts the current time to America/Chicago and selects the latest due slot:
- Watchlist: today's 04:17 slot, only after that time.
- Picks: today's latest due 05:23, 08:23, or 14:23 slot.
- Grading: the latest 23:55 slot, including yesterday's if delivery is delayed past midnight.

After each job succeeds, a durable GitHub Issue checkpoint records its completed slot. Failed jobs do not advance their checkpoints. A later check catches up to the latest current-day picks slot, rather than replaying stale earlier picks.

A separate timer waits five minutes and uses the repository-scoped GITHUB_TOKEN to dispatch the next coordinator run. Only that continuation job receives actions:write. The job's token expires normally after execution; no new persistent token was created. UTC cron remains a backup. Concurrency permits one active coordinator, and existing message reservations prevent repeat Discord delivery.

GitHub labels API-started workflows as workflow_dispatch. An automatic continuation is distinguished from a person clicking Run workflow by the github-actions[bot] actor and the preceding timer job's dispatch receipt.

## Operational controls

Set the repository variable `STATRALLY_SCHEDULER_PAUSED=true` to stop new posting checks and continuation. Disable the coordinator workflow to stop future dispatches. Existing running jobs can also be cancelled in Actions.

Normal manual posting remains available through the original M13 workflows. Never delete Discord reservations or delivery receipts to force a resend.

## Validation

- Seven new scheduler tests cover Central summer/winter offsets, midnight, delayed slots, completed-slot suppression, and failed-job receipts.
- Bootstrap run 41630783994 completed the gate, watchlist, picks, grading, and success receipts.
- Full validation run 41630784011 passed 124 public tests, 39 private exporter tests, and a live read-only exporter check.
- Continuation verified: run 41631019830 completed its five-minute timer and dispatch. GitHub then created run 41631724904 at 2026-11-03T11:57:45Z (05:57:45 Central), event workflow_dispatch, actor github-actions[bot], without a manual click. The timer path is operational; native cron delivery remains unverified.

Evidence: [bootstrap](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41630783994), [full validation](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41630784011), [timer](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41631019830), [automatic continuation](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41631724904).
