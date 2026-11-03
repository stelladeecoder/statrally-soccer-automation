# M13 operational verification

Audit date: November 2, 2026, Central Time. The fixes described here are on the
coverage/schedules/results audit branch until its PR is reviewed and merged.

## Configured schedule versus observed operation

| Workflow | America/Chicago time | Winter UTC | Summer UTC | Scheduled-run evidence at audit |
| --- | --- | --- | --- | --- |
| Daily watchlist | 4:17 AM | 10:17 | 09:17 | None recorded |
| Experimental picks | 5:23 AM, 8:23 AM, 2:23 PM | 11:23, 14:23, 20:23 | 10:23, 13:23, 19:23 | None recorded |
| Results checks | 11:55 PM | 05:55 next day | 04:55 next day | None recorded |

All three workflows are active in GitHub and use native IANA timezone schedules.
GitHub documents this behavior in its
[schedule reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
The configured times avoid the spring-forward skipped hour and fall-back repeated
hour. ZoneInfo conversion was checked on both sides of the 2026 transitions.
Scheduling runs the default branch. GitHub may delay or drop scheduled jobs;
configuration does not prove execution.

The Polymarket reporting configuration was updated after the November 2
morning/afternoon slots. The API returned zero `event=schedule` executions for
each reporting workflow. The first actual schedule event and its source/delivery
checks remain acceptance evidence to collect. Manual dispatches and push-triggered
bootstrap tests must not be relabeled scheduled executions. The audit removes
the watchlist's push-triggered live posting hook.

## Existing delivery evidence

- [Controlled live-data test 41564103599](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41564103599)
  delivered labeled watchlist and picks test output. Those test predictions were
  not reserved in the official paper ledger.
- [Manual paper dispatch 41562467939](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41562467939)
  found an existing reservation and sent no duplicate pick.
- [Results connection test 41505588396](https://github.com/stelladeecoder/statrally-soccer-automation/actions/runs/41505588396)
  was accepted by Discord. This is connection evidence, not a completed
  prediction lifecycle or financial result.

No additional test posts were needed in this audit.

## Genuine prediction lifecycle

[Issue #20](https://github.com/stelladeecoder/statrally-soccer-automation/issues/20)
contains Manchester United–Aston Villa, BTTS YES, kickoff November 8 at 10:30 AM
Central (16:30 UTC). Its reservation and hash-bound delivery receipt were recorded
on November 2 before kickoff. Independently fetched ESPN event `401879240`
still lists that kickoff and a scheduled, incomplete fixture.

The valid state is **pending**. No result message, win, loss or completed
prediction lifecycle can be certified yet. [Issue #21](https://github.com/stelladeecoder/statrally-soccer-automation/issues/21)
records zero graded outcomes and one pending delivered prediction. Retaining
this pre-migration record does not reactivate its former market source.

## Fixes and remaining acceptance

The audit adds grading for all 13 competitions, stable team-ID checks, test-record
exclusion, duplicate-fixture suppression, confirmed pick receipts, and durable
watchlist reservations/page receipts. Multi-page watchlists retain every validated
fixture and suppress mentions. Failed/uncertain delivery blocks an automatic
resend. Corrected final scores conflict with earlier grades and require review.

Acceptance still requires actual unattended scheduled executions, a genuinely
completed recorded prediction with independent final-score evidence, and a
confirmed results receipt. Broader market/model coverage is assessed separately
in private research records. Mocked tests do not close these gates.
