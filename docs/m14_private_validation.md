# Manual private M14 account validation

The `m14-kalshi-reconciliation.yml` workflow supports only manual execution and a
guarded reusable call from `validate.yml`. It has no schedule, Discord binding,
artifact upload, account-data cache or order-placement route. PR tests run with
synthetic records and mocked HTTP, without account secrets. PR #13 remains draft;
this workflow does not authorize a merge or financial publishing.

## Run authentication first

The existing validation workflow provides an entry point while the new workflow
is still on the unmerged feature branch:

```bash
gh workflow run validate.yml \
  --repo stelladeecoder/statrally-soccer-automation \
  --ref feat/m14-performance-tracking \
  -f m14_account_mode=auth-only
```

The client accepts an unencrypted PKCS#8 Ed25519 PEM signing key. It does not fall
back to RSA or accept a proxy placeholder. It signs GET `/portfolio/balance`,
requires HTTP 200 and discards the response without reading balances. No fills,
positions, statement contents or settlement records are read by this mode.
Successful authentication alone does not establish importer compatibility.

Only the sanitized `M14 private validation status` annotation/summary is needed
to assess the result. Missing credential bindings and invalid key formats fail
before network access. Other fixed categories identify rejected authentication,
redirects or network failure without printing requests, responses or exceptions.
Do not paste credentials or private account evidence into an issue or PR.

## Reconciliation gate

After authentication succeeds, reconciliation still requires an independently
reviewed, private statement covering the selected account/subaccount/shard from
inception through an explicit exclusive cutoff. Expected fee totals, gross
buy cost, gross proceeds, realized net P&L and open quantities/basis must come
from that evidence, never from this importer. The private deployment runbook
defines the evidence contract and provisioning procedure. Financial statement
contents are not workflow inputs or repository secrets.

Evidence can be staged in an owner-only runner-temporary file by an approved
private staging mechanism, or read from an existing private HTTPS source. The
workflow does not create or populate such a source. The default GitHub-hosted
runner has no pre-staged evidence file. Without either source, reconciliation
fails closed before retrieving transaction records.

When adequate private evidence is available:

```bash
gh workflow run validate.yml \
  --repo stelladeecoder/statrally-soccer-automation \
  --ref feat/m14-performance-tracking \
  -f m14_account_mode=reconcile
```

The client verifies netting configuration and collects the historical cutoff,
all pages of current/historical fills, current settlements, and live-all/archived
positions. Actual `fee_cost` values supply fees. Historical position summaries
cannot replace missing settlement events: independently reviewed retained
settlements are required when the live endpoint no longer returns them.

Raw pages, the statement, snapshot and SQLite ledger are written only below
`RUNNER_TEMP`, outside Git, in a fresh directory with mode 0700 and files 0600.
They are removed on completion/failure, with an additional always-run cleanup
step. Credentials stay in the step environment/memory. No private artifacts are
uploaded. Public output contains statuses and discrepancy counts only, without
amounts, account references, tickers, record counts, cursors or statement digests.

Pagination loops/limits, malformed pages, missing historical coverage, unknown
schemas, unsupported account modes, missing archive closures and fee/basis
disagreements all block reconciliation. Provider fee and settlement conventions
remain unverified until a real, independently reconciled account run passes.

## Offline verification

```bash
python3.12 -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements-m14-auth.txt
PYTHONPATH=src python3.12 -m unittest discover -s tests -v
```

The authentication and reconciliation tests use synthetic keys, independently
specified synthetic totals and mocked HTTP. Passing them does not imply live
account authentication, financial validation or Discord delivery.
