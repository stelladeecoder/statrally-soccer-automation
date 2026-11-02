# M14 current Kalshi REST inputs

Status: current-format implementation tested with **synthetic fixtures**. Real
account acceptance, independent statement reconciliation and financial publishing
remain disabled/unverified. This is an offline response importer, not an account
client. It performs no account HTTP requests, orders or trades.

## Official schema evidence

`kalshi-rest-3.35.0` is a StatRally adapter version for the OpenAPI document
version **3.35.0** in Kalshi's maintained
[`kalshi-typescript@3.35.0`](https://www.npmjs.com/package/kalshi-typescript/v/3.35.0).
The npm registry identifies maintainer `kalshi` with a Kalshi-domain address and
an OIDC trusted publisher. The package was downloaded with npm integrity
verification and scripts disabled, and inspected outside the repository; no
third-party SDK was installed as an application dependency or copied here.

Inspected archive SHA-256:
`4c5853d80089d1eb72c6319e496656bd3646c0c3706d5d8f7628d6b08c690982`.
Relevant package sources and generated documentation:

- `models/fill.ts`, `settlement.ts`, `market-position.ts`, `book-side.ts`,
  `outcome-side.ts`, `get-historical-cutoff-response.ts` and response wrappers;
- `docs/Fill.md`, `Settlement.md`, `MarketPosition.md`, `HistoricalApi.md`,
  `PortfolioApi.md`, `Order.md` and `BookSide.md`;
- `api/portfolio-api.ts`, `api/historical-api.ts`, `auth.ts` and `README.md`.

These directly document the requested current fields and historical semantics.
They supplement the official web-schema review recorded in commit `a74eb3d`.
Direct access to `docs.kalshi.com` remains denied in this runtime; do not describe
this as an authenticated live-account compatibility check.

Official web references:
[portfolio fills](https://docs.kalshi.com/api-reference/portfolio/get-fills),
[settlements](https://docs.kalshi.com/api-reference/portfolio/get-settlements),
[historical fills](https://docs.kalshi.com/api-reference/historical/get-historical-fills),
[historical positions](https://docs.kalshi.com/api-reference/historical/get-historical-positions).

The current generated SDK's base URL is
`https://external-api.kalshi.com/trade-api/v2`; paths below are relative to
`/trade-api/v2`. Its signer supports RSA-PSS/SHA-256 **or Ed25519** API keys and
emits the key, timestamp and signature headers. Use the official client's
approved signing implementation for authorized collection; no signer/key handling
is implemented by this offline importer. Some registered-partner endpoints also
support explicitly scoped OAuth, which this direct-user adapter does not implement.

## Provider records and accounting

Fill inputs use `fill_id`, `exchange_index`, `order_id`, `ticker`, `outcome_side`,
`book_side`, `count_fp`, `yes_price_dollars`, `no_price_dollars`, `is_taker`,
`fee_cost`, direct-user `subaccount_number`, and `created_time` or `ts`.
`trade_id`/`market_ticker` aliases must agree if present. Deprecated `side` and
`action` are independently optional; when both are present, their direction must
agree with the canonical fields. Unknown fields require schema review.

Counts are **two-place decimal strings** at 0.01-contract granularity, never
floats or truncated integers. Dollar source strings support up to six places.
The source's `fee_cost` supplies the actual per-fill fee; no external fee map or
estimated fee formula is used. Missing or negative fees are rejected.

For event contracts, `book_side=bid` means buy YES exposure and `ask` means sell
YES exposure (economically buy NO). The canonical `outcome_side` must respectively
be `yes` / `no`. Only explicitly declared **net-position accounts** are supported.
An incoming opposite-direction fill first closes the existing side, then opens
any remainder on the other side. The ledger records SELL proceeds using the
closed leg's dollar price and BUY basis using the opened leg's dollar price.
Fill fees split proportionally between these legs, with the residual retained
on the final leg. The original provider record remains one immutable source;
its one or two normalized events have distinct IDs referencing that source.

The existing FIFO ledger now accepts integers and exact fractional count strings.
Entry fees remain in open basis until closure. Internal arithmetic uses 60-digit
Decimal precision; proportional fee allocations use 18 USD decimal places with
residual conservation. Whole quantities retain integer JSON output; fractional
quantities remain strings. ROI, partial exits, open positions and cycle win/loss
metrics retain their [documented definitions](m14_performance.md#accounting-and-metric-definitions).

Settlement inputs use `exchange_index`, `ticker`, `event_ticker`, `market_result`,
`yes_count_fp`, `no_count_fp`, `yes_total_cost_dollars`, `no_total_cost_dollars`,
`fee_cost`, `settled_time`, and optional nullable `value`.
**`revenue` remains integer cents in the inspected current schema**; the adapter
never invents a `revenue_dollars` field. Binary winning fractional contracts pay
the corresponding cent amount. Counts, gross FIFO basis, payout and fee totals
must reconcile. Settlement `fee_cost` is conservatively required to match the
market's accumulated source fill fees and is not charged twice. Actual provider
fee/basis conventions and any cash-rounding differences still need authenticated
statement validation; mismatches block import rather than forcing a fit.
Scalar/void/refund settlements, rebates and settlement revisions are unsupported.

## Complete capture wrapper (StatRally metadata)

Use one private account, direct-user subaccount and exchange shard per database.
The current scope supports subaccount numbers 0–63 and explicitly reviewed netting
mode. Mixed shards/accounts and unknown netting settings are rejected. Historical
endpoints lack every live filter; multi-shard histories need separate reviewed
collection handling and are not silently filtered by this adapter.

The following empty synthetic wrapper shows the complete structure. Collection
names, `scope`, `captured_at`, `history_from_inception`, endpoint/query metadata,
page request cursors and retained-evidence wrappers are **StatRally fields**, not
invented Kalshi API response fields. Nonempty synthetic record examples live in
`tests/m14_rest_samples.py`.

```json
{
  "schema": "kalshi-rest-3.35.0",
  "data_kind": "synthetic",
  "history_from_inception": true,
  "scope": {
    "account_ref": "SYNTHETIC-ACCOUNT-ONLY",
    "subaccount_number": 0,
    "exchange_index": 0,
    "netting_mode": "net"
  },
  "captured_at": "2026-11-05T12:00:00Z",
  "historical_cutoff": {
    "market_settled_ts": "2026-10-01T00:00:00Z",
    "trades_created_ts": "2026-10-01T00:00:00Z",
    "orders_updated_ts": "2026-10-01T00:00:00Z",
    "market_positions_last_updated_ts": "2026-10-01T00:00:00Z"
  },
  "collections": {
    "portfolio_fills": {
      "endpoint": "/portfolio/fills", "query": {"subaccount": 0, "exchange_index": 0},
      "pages": [{"request_cursor": "", "response": {"fills": [], "cursor": ""}}]
    },
    "historical_fills": {
      "endpoint": "/historical/fills", "query": {"subaccount": 0},
      "pages": [{"request_cursor": "", "response": {"fills": [], "cursor": ""}}]
    },
    "portfolio_settlements": {
      "endpoint": "/portfolio/settlements", "query": {"subaccount": 0},
      "pages": [{"request_cursor": "", "response": {"settlements": [], "cursor": ""}}]
    },
    "portfolio_positions": {
      "endpoint": "/portfolio/positions", "query": {"subaccount": 0, "exchange_index": 0, "settlement_status": "all"},
      "pages": [{"request_cursor": "", "response": {"market_positions": [], "event_positions": [], "cursor": ""}}]
    },
    "historical_positions": {
      "endpoint": "/historical/positions", "query": {"subaccount": 0},
      "pages": [{"request_cursor": "", "response": {"market_positions": [], "event_positions": [], "cursor": ""}}]
    }
  },
  "retained_settlements": []
}
```

`historical_cutoff` is the raw response from GET `/historical/cutoff`. Fill time
before `trades_created_ts` requires historical-fill coverage. Position
`market_positions_last_updated_ts` is a **backfill horizon**, not an exact
live/archive partition: whole events move after a buffered handoff. Settled
positions can remain live even when older than that horizon. Read all live states
with `settlement_status=all` as well as historical positions; default unsettled-only
position reads are insufficient. Never omit a historical collection just because
live pagination terminates or a cutoff appears recent.

Every collection requires at least one page, even when empty. First request cursor
is empty; each next request matches the preceding response cursor; only the final
page terminates. Missing pages, loops, mixed query scopes and time/ticker/order/
count filters reject the snapshot. A positive `limit` is allowed. Current fills
require a response cursor; settlements and positions permit its documented
omission at the end. Null cursors are not silently coerced to empty.

Identical overlapping live/historical fills deduplicate by shard/fill identity.
Conflicting records reject atomically. A fill moving between endpoints retains its
identity; it does not become a second event. Same-market timestamp ties are
rejected rather than guessing FIFO order. Position snapshots must not predate the
latest imported event or exceed capture time. Provider net inventory, known-market
coverage and aggregate paid fees are checked against normalized history.

## Archived positions are not archived settlement events

GET `/historical/positions` returns the current `MarketPosition` shape:
`ticker`, `exchange_index`, `total_traded_dollars`, `position_fp`,
`market_exposure_dollars`, `realized_pnl_dollars`, `fees_paid_dollars`,
`last_updated_ts`, inside `market_positions`. These are **aggregate observations**.
They do not supply contract-by-contract closing fills, a settlement payout price
or a settlement execution timestamp. GET `/portfolio/settlements` does not return
archived settlements. There is no fabricated archived-settlement endpoint.

If archived holdings require a settlement to close the ledger, provide an actual
retained current-format settlement record from an earlier export, with private
independent review evidence:

```json
{
  "record": {"...": "actual retained Settlement fields, not aggregate-derived values"},
  "reviewed": true,
  "evidence_reference": "private statement/export reference"
}
```

Place these wrappers in `retained_settlements`; the schematic `record` above is
not executable sample data. An archived position alone cannot satisfy this
requirement. A position closed entirely by recorded SELL fills needs no invented
settlement. Unresolved archive gaps reject the import. Retain actual closure
records before the provider archives them, and preserve independent statements.
Do not infer payout dates from `last_updated_ts` or solve payout amounts from
aggregate P&L. Provider aggregate P&L/exposure fields remain raw evidence; their
provider accounting conventions are not assumed to be FIFO or net of fees.

## Storage, reports and deployment

Use `src/m14_import.py --snapshot /PRIVATE/snapshot.json --database /PRIVATE/rest.sqlite`.
Paths must be outside Git. Immutable fill/settlement sources and normalized events
remain separate; each complete current capture (including position observations,
queries and cutoff metadata) is retained in `rest_snapshots`. Repeated captures
do not double-count transactions. Later snapshots must preserve all prior
transaction sources, including retained settlements after archival. Scope, schema
and synthetic/live labels cannot change within a store. A source change or changed
normalization requires explicit investigation, not silent history replacement.
Legacy and current formats must use different private stores; do not delete
receipts or overwrite an existing database to migrate.

On reporting, the latest capture is re-normalized and matched to retained sources,
events, source references and account metadata. Source/record mutations fail.
The results send gate accepts only current-format stores, fresh independent
reconciliation evidence and reports whose full cutoff is covered by capture time.
Dry-run/preview behavior remains available without any credential.

These checks detect missing collections/pages, wrong scope, missing opening or
closing records, unexplained provider inventory, fees and orphan markets. They
**cannot prove inception completeness or source authenticity**. An omitted
zero-fee closed round trip could leave inventory unchanged. Independent statement
gross buy/proceeds totals, fees, realized P&L and all open quantities/basis remain
mandatory at the existing reconciliation gate. Do not copy computed totals into
a review to claim independent validation.

The manual-only `M14 results connection-only test` workflow is prepared. It uses
an empty temporary test store and sends only the existing fixed CONNECTION TEST
message; no account input, report date, financial payload or live-publishing mode
is available in that workflow. It has no PR, push or scheduled trigger. Preparing
it does not execute it or visually verify the channel. Secret configuration and
an authorized test procedure are documented in the private deployment runbook,
outside this public repository. No financial results publishing has been enabled.

Remaining acceptance: real authenticated, read-only source collection; account
scope/netting and complete archived history; actual provider fee/basis/rounding
semantics; independent statement reconciliation; results-channel connection and
visual confirmation; durable private scheduling/state ownership; required PR
review. Do not label M14 complete or merge PR #13 before its compatibility and
review requirements are satisfied.
