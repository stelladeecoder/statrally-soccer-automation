# Compact Discord presentation

The active experimental picks, daily watchlist and verified paper results use
native Discord embeds. All BTTS prediction cards use blue accents for both YES
and NO. Verified result cards use green for WIN and red for LOSS, regardless of
which BTTS side was predicted. The original YES/NO side remains explicitly labeled. No custom
fonts, colored text, images, banners or fixed-width columns are used. Native
inline fields can stack on mobile; long titles retain full match names in the
description. Visual Discord/mobile inspection is a separate check from API
acceptance and structural limits.

Watchlists group complete fixture rows by competition. Fields continue across
pages without silently dropping fixtures. Every message is checked against
Discord's content, embed, field, footer and combined-text limits using conservative
UTF-16 lengths. Mentions are disabled. Date/kickoff labels use America/Chicago.

Signal identities, JSON signal hashes, delivery-proof comments and grading rules
are unchanged. Pick Issues retain readable summaries of embeds. Existing
watchlist reservations use their saved page counts/hashes, so changing the
presentation does not resend an already recorded day. Pending or unconfirmed
outcomes do not get a verified-result card. Earlier recorded predictions remain
eligible for later grading.

New watchlists and picks are restricted to the current Central calendar day.
Private operational exports filter the verified fixture date; public new-pick
validation checks the date again before reservation and delivery. A current day
with no matches/picks stays empty. Adjacent source dates are permitted, not future-
day output. The same-day guard does not invalidate older saved predictions.

## Fictional design previews

The manual validation workflow has an explicit `design_preview` input, false by
default. Its preview job has no private research checkout, Issues write permission,
official dispatch or grading call. It sends exactly one message per configured
channel, with fictional watchlist, YES/NO and all four side/outcome combinations.
Every message and embed footer is labeled DESIGN TEST · FICTIONAL DATA.

The sender requests Discord message receipts and records jump links/IDs in the
job summary. No webhook values are printed. No POST retries are performed; a
rerun attempt is refused to prevent duplicating an uncertain send. Inspect saved
receipts before taking any further action after a partial failure.

Production schedules remain 4:17 AM, 5:23 AM, 8:23 AM, 2:23 PM and 11:55 PM America/Chicago.
Polymarket US stays active. M14 PR #13 stays draft and unmerged. These presentation
changes enable no trading or financial-result publishing.
