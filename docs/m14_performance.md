# M14 — Actual-event accounting and results reporting

Status: **in progress**. The public implementation extends the migrated M14 ledger;
all M14 code, tests and public documentation stay in this repository. No private
engine changes, order placement, live account requests or live reporting schedules
are included. Synthetic tests establish software behavior, not trading performance.
M13 delivery verification, IFTTT and M15 remain separate work.

## Architecture

- `m14_position_ledger.py`: existing Decimal FIFO ledger, now allocating entry fees
  to lots, tracking closures and flat-to-flat position cycles.
- `m14_import.py`: offline SDK-response normalization, source deduplication,
  settlement checks, atomic SQLite persistence. Raw sources and normalized events
  occupy separate tables with source references.
- `m14_performance.py`: daily, week-to-date and cumulative metrics, private
  market-level details, a sparse daily cumulative series and reconciliation gate.
- `m14_results_publish.py`: dedicated results formatter, test/confirmation steps
  and durable outbox. Dry-run by default; independent of M13 publisher modes.

Python 3.12 standard library only. Run the whole local suite:

```bash
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
```

Tests use explicitly synthetic records and mocked HTTP. They cover YES/NO winning
and losing settlements, multi-lot FIFO, fees, partial/full exits and settlements,
reopened cycles, invalid quantities and payouts, duplicate/missing records,
pagination, repeat imports, atomic conflicts, empty/open histories, ROI and
win/loss definitions, DST boundaries, reconciliation, payload privacy,
concurrent delivery reservations, crashes/timeouts, and CLI execution.

## Supported input and schema evidence

The adapter is deliberately versioned `kalshi-sdk-3.2.0`. Its schema evidence is
Kalshi's published **kalshi-python-sync 3.2.0** SDK, generated from its OpenAPI
specification. The package metadata identifies Kalshi / support@kalshi.com and
links its official documentation. Relevant generated definitions inspected:

- `kalshi_python_sync/models/fill.py`
- `models/settlement.py`, `models/get_fills_response.py`,
  `models/get_settlements_response.py`
- `api/portfolio_api.py`: GET `/portfolio/fills` and GET `/portfolio/settlements`
  relative to the configured `/trade-api/v2` base.

Sources: [SDK release](https://pypi.org/project/kalshi-python-sync/3.2.0/),
[official documentation](https://docs.kalshi.com/).
Inspected wheel SHA-256:
`667f6b4ed1e8dbc5b173e7d19e796dbda8602b0a9943506a87e46e6539a6301c`.
The wheel was inspected outside the checkout, not installed as a runtime dependency.
Direct access to `docs.kalshi.com` was denied by this cloud environment's proxy.
**Current live API compatibility and fee semantics have not been validated with
an authenticated account or real exports.** SDK schema evidence is not a claim
that every current API version is supported. No CSV export layout is assumed.

The supported fill subset uses `fill_id`, `ticker`, `side` (`yes`/`no`), `action`
(`buy`/`sell`), integer `count`, `yes_price_fixed` / `no_price_fixed` (USD strings),
and aware `created_time` or integer Unix `ts`. Legacy aliases, cent prices and
`ts`, when supplied alongside their replacements, must agree. Complementary
YES/NO prices must sum to one; deprecated `price` is not used. This supports
subcent fixed-dollar prices when no contradictory integer-cent field is present.

Settlements use `ticker`, `market_result`, `yes_count`, `no_count`,
`yes_total_cost`, `no_total_cost`, `revenue` (integer cents), `settled_time`,
`fee_cost` (fixed-dollar string), and optional `value` (YES payout in cents).
Quantities, **gross remaining FIFO basis**, binary payout and aggregate fees must
reconcile exactly. The adapter conservatively interprets `fee_cost` as the
market's aggregate trading fees and compares it to explicit fill fee evidence;
it never charges that aggregate again as a settlement fee. If provider basis or
fee conventions differ, the import fails for review; do not relabel values to
force a match. Scalar/void/refund records, settlement revisions, fractional
counts and opposite-side netting are unsupported and rejected. A BUY on the
opposite side while a position is open needs separately verified exchange
netting semantics; this adapter will not invent a SELL or hold fictitious hedges.
SELL fills without sufficient preceding BUY fills are rejected.

The inspected SDK fill schema has **no fee field**. Supply independently
reviewed per-fill fee evidence, including explicit zero fees. Do not calculate
fees from an assumed taker rate or infer them from order status. A partially
filled/cancelled order contributes only its actual fills; unfilled order
quantities are ignored. Aggregated fee evidence alone cannot allocate a closed
and open position's fees accurately and is insufficient for this adapter.

### StatRally snapshot wrapper (not a Kalshi API response)

Store the following wrapper **outside all Git checkouts**. `fill_fees`,
`request_cursor`, `schema`, `data_kind`, and `history_from_inception` are StatRally
metadata, not invented provider fields. The empty example represents a synthetic
empty history; see `tests/m14_samples.py` for nonempty synthetic responses.

```json
{
  "schema": "kalshi-sdk-3.2.0",
  "data_kind": "synthetic",
  "history_from_inception": true,
  "fills_pages": [
    {"request_cursor": "", "response": {"fills": [], "cursor": ""}}
  ],
  "settlements_pages": [
    {"request_cursor": "", "response": {"settlements": [], "cursor": ""}}
  ],
  "fill_fees": []
}
```

A nonempty `fill_fees` entry is `{"fill_id":"synthetic-fill-1","fee_usd":"0.02"}`.
An optional private `evidence_reference` can identify an independent fee record.
Use `data_kind: live` only for actual account records; synthetic and live data
cannot share a database. Input labels and history completeness are operator
assertions, not authenticated proof supplied by this software.

Provide all unfiltered response pages from account inception. Each next page's
`request_cursor` must equal the preceding response cursor, and the final response
cursor must be empty. Pagination validity cannot prove the account history was
not filtered or that archived fills were included: independent reconciliation is
required. Exact duplicate records deduplicate; changed records with the same
source identity reject the entire import. Settlement identity is ticker plus
normalized settlement time (there is no invented provider settlement ID).

Events sort by aware execution time. Distinct records at the same time in the
same market are rejected rather than guessing economic order. Normalize with
higher-resolution verified source evidence in a separately reviewed adapter if
needed. Historical sources are immutable: later imports must be complete
supersets, not partial incremental pages. Missing prior records or changed fee
allocations require investigation and an explicitly reviewed rebuilt store,
never silent correction. Prior outbox receipts must be retained separately when
rebuilding so already delivered periods cannot be reposted.

## Accounting and metric definitions

- Monetary input uses Decimal strings or integer cents, never binary floats.
  Quantities are positive integers up to signed 64-bit range. Prices are USD per
  contract in [0,1]; binary settlement payouts must be 0 or 1. Monetary inputs
  support up to 18 decimal places; individual fees must be below $10^18.
- Entry fees remain in the lot's open basis. Closing contracts consume FIFO
  price basis and their share of entry fees, plus any exit fee. Pro-rata entry
  fees round to 18 decimal USD places, with remaining residual carried in the
  lot and consumed by its final closure. Arithmetic uses 60-digit precision.
- Realized net P&L = gross closing proceeds minus matched entry price basis,
  allocated entry fees and exit fees. Open entry fees are **not realized losses**.
  The earlier open-only regression expected an immediate fee loss; that assertion
  was corrected with the accounting defect. Fully closed historical P&L is unchanged.
- Gross open basis and fee-inclusive open basis are separate. Unrealized P&L is
  `null`: no mark prices are supplied, so an open position is not valued at zero.
- ROI = period realized net P&L / entry cost **including entry fees of contracts
  closed in that period**. It includes partial exits and settlements, and is
  neither return on deposits nor on all capital ever deployed. Zero denominator
  gives `null` / N/A, including zero-cost winning contracts.
- A position is a `(market_ticker, side)` cycle from flat to flat. Reopening starts
  another cycle. Win/loss rates classify only cycles reaching flat during the
  period, using the full cycle's net outcome including its earlier partial exits.
  Breakeven cycles count in the denominator; zero completed cycles gives N/A.
- Period P&L includes only closures executed in the period; completed-cycle P&L
  may include earlier partial exits. They are separate fields. Early exits are
  SELL closures, including partially closed cycles; not automatically wins/losses.
- Fees paid in a period use event dates, including fees on still-open buys.
  Recognized fees use the contracts closed in the period. These intentionally
  differ. Cumulative fees count each event fee once.
- Daily boundaries use America/Chicago, including 23/25-hour DST days. `--through`
  is inclusive; the cutoff is the next local midnight. Weekly means Monday
  through the selected date (week-to-date); cumulative means inception through
  that date. Events at the exclusive cutoff are excluded.
- Market profit and sparse daily/cumulative series are available in the private
  report. Days without activity are omitted except for the selected cutoff date.

## Local operation

Use private paths such as `/workspace/statrally-local/`. Raw snapshots, fee
records, reconciliation evidence, SQLite state and detailed reports must never
be committed or uploaded as public CI artifacts. State paths inside Git
checkouts are refused. Database files are mode 0600; this is not encryption.
Use a private machine/storage policy for any real financial data. Do not put
real account data in a reusable shared environment snapshot. Tests create only
synthetic temporary state and need no credentials.

```bash
cd /workspace/statrally-soccer-automation
python3.12 src/m14_import.py --snapshot /workspace/statrally-local/snapshot.json --database /workspace/statrally-local/ledger.sqlite
python3.12 src/m14_performance.py --database /workspace/statrally-local/ledger.sqlite --period weekly --through 2026-11-02 > /workspace/statrally-local/report.json
python3.12 src/m14_results_publish.py --database /workspace/statrally-local/ledger.sqlite --period daily --through 2026-11-02
```

The import prints counts and labels only. Detailed performance stdout is private;
redirect it accordingly. Results dry-run prints only an aggregate preview.
Malformed inputs fail with nonzero status and redacted CLI errors. Repeating the
same snapshot import is a no-op; concurrent imports serialize transactionally.
Back up the private database securely: the same durable database holds both
history and delivery receipts and must survive all reporting jobs/restarts.

### Reconciliation and results activation (not performed)

`--reconciliation` accepts a local review document with `schema_version: 1`,
`reviewed: true`, `data_kind: live`, the current `history_sha256`, the exact
`cutoff_exclusive`, a private `evidence_reference`, and an `expected` object.
Expected values must come from independent statement review, **not copied from
the report to make the gate pass**. Its required fields are:

- `realized_net_pnl_usd`, `fees_paid_usd`, `gross_proceeds_usd`, `gross_buy_cost_usd`
- `open_positions`: entries with `market_ticker`, `side`, integer `quantity` and
  `basis_usd` (including entry fees); an empty list when flat.

For the hash/cutoff and computed comparison values inspect the private report's
`history_sha256`, `cutoff_exclusive`, and `reconciliation_values`. A changed
history/cutoff or mismatched total/inventory fails verification. Reconciliation
is explicitly an **operator attestation**; it cannot authenticate the source or
prove an operator checked independent evidence. The CLI rebuilds the report from
local events each time; it never accepts an arbitrary pre-rendered report file
as authorization to send. Synthetic reports remain test previews and cannot be
sent as live financial results.

Only after a separately authorized activation, securely configure
`STATRALLY_RESULTS_DISCORD_WEBHOOK` for **#btts-results**, run a connection test,
and visually confirm the destination:

```bash
python3.12 src/m14_results_publish.py --database /workspace/statrally-local/ledger.sqlite --test-message --send
python3.12 src/m14_results_publish.py --database /workspace/statrally-local/ledger.sqlite --confirm-results-channel
```

Connection tests contain no financial figures. A successful HTTP response alone
does not certify the channel. After reconciliation and channel confirmation,
authorized daily/weekly/cumulative reporting can run this command on a private
scheduler sharing the same durable database (choose the corresponding period):

```bash
python3.12 src/m14_results_publish.py --database /workspace/statrally-local/ledger.sqlite --period daily --through 2026-11-02 --reconciliation /workspace/statrally-local/review.json --send
```

No workflow/scheduler or live secret was configured by this implementation.
Do not use a fresh ephemeral GitHub runner without durable private state, or
public Actions logs/artifacts for raw data. M13 variables/webhooks are not used.
Discord payloads contain aggregate numbers only, never market/account identifiers
or evidence references; mentions are disabled.

The outbox reserves each destination/period/cutoff **before** making a request.
Confirmed deliveries cannot repeat even if the history is later corrected.
Timeouts, unexpected responses and crashes leave `uncertain` or `pending` entries
that block retries; those CLI outcomes exit nonzero. Check the channel and private
outbox before any operator-controlled recovery. Mark a receipt delivered if it
actually arrived; remove/retry a reservation only after establishing it did not.
There is no automatic destructive reset or retry flag. Discord offers no webhook
idempotency key, so exactly-once delivery across a crash cannot be promised.
Do not delete the database, rotate a webhook or rebuild history to bypass receipts.
A separate daily/weekly/cumulative report is intentional, not a duplicate.

## Remaining acceptance

1. Confirm the supported schema against current official docs and representative
   actual authenticated response data, including provider cost-basis/fee semantics,
   account history completeness, netting and archived data limitations.
2. Reconcile actual fills and fees against independent account statements.
3. Configure, test and visually confirm the dedicated results webhook only when
   explicitly authorized; no connection test has been sent by this development.
4. Choose durable private state and a private scheduler/review procedure before
   enabling automated live reports. Verify final CI if GitHub API access permits.

Until these operational checks are satisfied, M14 remains **in progress**.
