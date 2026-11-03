"""Manual, private-runner Kalshi validation. Public output is status/counts only."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
from decimal import Context, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from m14_import import CURRENT_SCHEMA, canonical, connect, digest, import_snapshot, load_history, private_path
from m14_kalshi_client import KalshiReadOnly, NoRedirect, ReadOnlyError, json_object
from m14_kalshi_rest import COLLECTIONS
from m14_performance import reconciliation_values, verify_review
from m14_position_ledger import contracts, money, summarize, timestamp

MONEY_FIELDS = ("realized_net_pnl_usd", "fees_paid_usd", "gross_proceeds_usd", "gross_buy_cost_usd")
CHECK_NAMES = {"realized_net_pnl_usd": "realized_pnl", "fees_paid_usd": "fees",
               "gross_proceeds_usd": "gross_proceeds", "gross_buy_cost_usd": "gross_buy_cost"}
MAX_PAGES = 100
MAX_EVIDENCE_BYTES = 64 * 1024


class EvidenceError(ValueError):
    pass


class CoverageError(ValueError):
    pass


def evidence_available(runner_temp):
    return bool(os.environ.get("M14_RECONCILIATION_EVIDENCE_URL")) or (Path(runner_temp) / "statrally-m14-independent-evidence.json").exists()


def load_private_evidence(runner_temp, *, opener=None):
    """Read an existing private source; never store account figures in repo secrets.

    A private HTTPS source is optional. Only its locator/access token are secret
    bindings; statement contents remain in memory/temporary runner files.
    """
    root = private_path(runner_temp)
    path = root / "statrally-m14-independent-evidence.json"
    try:
        if path.exists():
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise EvidenceError()
                raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        else:
            url = os.environ.get("M14_RECONCILIATION_EVIDENCE_URL", "")
            if not url:
                return ""
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443):
                raise EvidenceError()
            token = os.environ.get("M14_EVIDENCE_ACCESS_TOKEN", "")
            if "\r" in token or "\n" in token:
                raise EvidenceError()
            headers = {"Accept": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            # No Kalshi authentication headers or credentials are used here.
            open_request = opener or build_opener(NoRedirect()).open
            with open_request(Request(url, headers=headers, method="GET"), timeout=20) as response:
                if response.status != 200:
                    raise EvidenceError()
                raw = response.read(MAX_EVIDENCE_BYTES + 1)
        if len(raw) > MAX_EVIDENCE_BYTES:
            raise EvidenceError()
        return raw.decode("utf-8")
    except Exception:
        raise EvidenceError() from None


def amount(value, *, signed=False):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?", value):
        raise EvidenceError()
    result = money(value)
    if result.copy_abs() >= money("1e30") or (not signed and result < 0):
        raise EvidenceError()
    return result


def inventory(rows, *, strict=True):
    if not isinstance(rows, list):
        raise EvidenceError()
    result = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"market_ticker", "side", "quantity", "basis_usd"}:
            raise EvidenceError()
        ticker, side = row["market_ticker"], row["side"]
        if not isinstance(ticker, str) or not ticker.strip() or side not in ("YES", "NO"):
            raise EvidenceError()
        key = ticker, side
        if key in result:
            raise EvidenceError()
        basis = amount(row["basis_usd"]) if strict else money(row["basis_usd"])
        if basis < 0:
            raise EvidenceError()
        result[key] = (contracts(row["quantity"]), basis)
    return result


def independent_evidence(raw, key_id, now):
    """Expected figures must come from an independently reviewed statement.

    Never populate expected values from the same collected API data or our ledger.
    The private key-ID digest binds the operator's statement to this credential.
    """
    try:
        data = json_object(raw)
        required = {"schema_version", "source_type", "reviewed", "evidence_reference", "api_key_id_sha256",
                    "scope", "cutoff_exclusive", "coverage", "expected", "retained_settlements"}
        if set(data) != required or type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise EvidenceError()
        if data["source_type"] != "independent_account_statement" or data["reviewed"] is not True:
            raise EvidenceError()
        if not isinstance(data["evidence_reference"], str) or not data["evidence_reference"].strip():
            raise EvidenceError()
        if data["api_key_id_sha256"] != hashlib.sha256(key_id.encode()).hexdigest():
            raise EvidenceError()
        scope = data["scope"]
        if not isinstance(scope, dict) or set(scope) != {"account_ref", "subaccount_number", "exchange_index", "netting_mode"}:
            raise EvidenceError()
        if not isinstance(scope["account_ref"], str) or not scope["account_ref"].strip() or scope["netting_mode"] != "net":
            raise EvidenceError()
        if type(scope["subaccount_number"]) is not int or not 0 <= scope["subaccount_number"] <= 63:
            raise EvidenceError()
        if type(scope["exchange_index"]) is not int or scope["exchange_index"] < 0:
            raise EvidenceError()
        cutoff = timestamp(data["cutoff_exclusive"])
        if cutoff > now:
            raise EvidenceError()
        if data["coverage"] != {"history_from_inception": True, "historical_records_reviewed": True} or any(type(v) is not bool for v in data["coverage"].values()):
            raise EvidenceError()
        expected = data["expected"]
        if not isinstance(expected, dict) or set(expected) != set(MONEY_FIELDS) | {"open_positions"}:
            raise EvidenceError()
        for field in MONEY_FIELDS:
            amount(expected[field], signed=field == "realized_net_pnl_usd")
        inventory(expected["open_positions"])
        if not isinstance(data["retained_settlements"], list):
            raise EvidenceError()
        for record in data["retained_settlements"]:
            if not isinstance(record, dict) or set(record) != {"record", "reviewed", "evidence_reference"} or record["reviewed"] is not True:
                raise EvidenceError()
            if not isinstance(record["record"], dict) or not isinstance(record["evidence_reference"], str) or not record["evidence_reference"].strip():
                raise EvidenceError()
        return data
    except Exception:
        raise EvidenceError() from None


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(canonical(value))


def collect(client, evidence, directory, *, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    scope = evidence["scope"]
    settings = client.get_json("/portfolio/subaccounts/netting")
    private_json(directory / "netting.json", settings)
    configs = settings.get("netting_configs")
    if not isinstance(configs, list) or any(not isinstance(item, dict) for item in configs):
        raise CoverageError()
    matches = [item for item in configs if type(item.get("subaccount_number")) is int and item["subaccount_number"] == scope["subaccount_number"]
               and type(item.get("exchange_index")) is int and item["exchange_index"] == scope["exchange_index"]]
    if len(matches) != 1 or matches[0].get("enabled") is not True:
        raise CoverageError()
    cutoff = client.get_json("/historical/cutoff")
    private_json(directory / "historical-cutoff.json", cutoff)
    collections = {}
    for name, (route, array) in COLLECTIONS.items():
        query = {"subaccount": scope["subaccount_number"], "limit": 100}
        if name in ("portfolio_fills", "portfolio_positions"):
            query["exchange_index"] = scope["exchange_index"]
        if name == "portfolio_positions":
            query["settlement_status"] = "all"
        cursor, visited, pages = "", set(), []
        for page in range(MAX_PAGES):
            if cursor in visited:
                raise CoverageError()
            visited.add(cursor)
            response = client.get_json(route, dict(query, **({"cursor": cursor} if cursor else {})))
            private_json(directory / f"{name}-{page:04d}.json", response)
            if not isinstance(response.get(array), list):
                raise CoverageError()
            pages.append({"request_cursor": cursor, "response": response})
            cursor = response.get("cursor", "" if array != "fills" else None)
            if not isinstance(cursor, str):
                raise CoverageError()
            if not cursor:
                break
        else:
            raise CoverageError()
        collections[name] = {"endpoint": route, "query": query, "pages": pages}
    return {"schema": CURRENT_SCHEMA, "data_kind": "live", "history_from_inception": True,
            "scope": scope, "captured_at": clock().isoformat(), "historical_cutoff": cutoff,
            "collections": collections, "retained_settlements": evidence["retained_settlements"]}


def compare(events, evidence):
    with localcontext(Context(prec=60)):
        cutoff = timestamp(evidence["cutoff_exclusive"])
        selected = [event for event in events if timestamp(event["timestamp"]) < cutoff]
        actual = reconciliation_values(summarize(selected))
        counts = {CHECK_NAMES[field]: int(money(evidence["expected"][field]) != money(actual[field])) for field in MONEY_FIELDS}
        counts["open_inventory"] = int(inventory(evidence["expected"]["open_positions"]) != inventory(actual["open_positions"], strict=False))
        if not any(counts.values()):
            # Bind the private independent expected figures to this exact imported
            # history. Only the digest/cutoff are derived here, never the figures.
            review = {"schema_version": 1, "reviewed": True, "data_kind": "live",
                      "history_sha256": digest({"data_kind": "live", "events": selected}),
                      "cutoff_exclusive": cutoff.isoformat(), "evidence_reference": evidence["evidence_reference"],
                      "expected": evidence["expected"]}
            if verify_review(review, review["history_sha256"], cutoff, actual) is not True:
                raise EvidenceError()
        return counts


def execute(mode, runner_temp, key_id, private_pem, evidence_raw="", *, client_factory=KalshiReadOnly,
            now=None, evidence_loader=None, has_evidence=None):
    report = {"mode": mode, "status": "failed", "authentication": "not_run", "reconciliation": "not_run",
              "independent_evidence": "present" if (bool(evidence_raw) if has_evidence is None else has_evidence) else "missing", "discrepancy_counts": {}}
    phase = "authentication"
    try:
        client = client_factory(key_id, private_pem)
        client.authenticate()
        report["authentication"] = "passed"
        if mode == "auth-only":
            report["status"] = "passed"
            if report["independent_evidence"] == "missing":
                report["discrepancy_counts"]["independent_evidence_missing"] = 1
            return report, 0
        if mode != "reconcile":
            raise EvidenceError()
        phase = "independent_evidence"
        if evidence_loader is not None:
            evidence_raw = evidence_loader()
        if not evidence_raw:
            report["status"], report["reconciliation"] = "blocked", "blocked"
            report["discrepancy_counts"]["independent_evidence_missing"] = 1
            return report, 2
        evidence = independent_evidence(evidence_raw, key_id, now or datetime.now(timezone.utc))
        # A new owner-only directory is the ONLY storage location for account data.
        root = private_path(runner_temp)
        if not root.is_dir():
            raise CoverageError()
        with tempfile.TemporaryDirectory(prefix="statrally-m14-private-", dir=root) as private:
            directory = Path(private)
            os.chmod(directory, 0o700)
            private_json(directory / "independent-evidence.json", evidence)
            phase = "historical_coverage"
            snapshot = collect(client, evidence, directory, clock=(lambda: now) if now is not None else None)
            private_json(directory / "account-snapshot.json", snapshot)
            phase = "normalization"
            with closing(connect(directory / "ledger.sqlite")) as db:
                import_snapshot(db, snapshot)
                events, kind = load_history(db)
            phase = "reconciliation"
            counts = compare(events, evidence)
            report["discrepancy_counts"] = counts
            report["reconciliation"] = "passed" if not any(counts.values()) else "failed"
            report["status"] = report["reconciliation"]
            return report, 0 if report["status"] == "passed" else 2
    except ReadOnlyError as error:
        if error.category == "missing_credentials":
            # Presence diagnostics only: never emit lengths or credential values.
            for field, value in (("missing_api_key_id", key_id), ("missing_private_key", private_pem)):
                if not value:
                    report["discrepancy_counts"][field] = 1
        else:
            report["discrepancy_counts"][error.category] = 1
    except EvidenceError:
        report["discrepancy_counts"]["independent_evidence_invalid"] = 1
    except CoverageError:
        report["discrepancy_counts"]["historical_coverage"] = 1
    except ValueError as error:
        # Existing importer errors are classified internally, never printed.
        reason = str(error)
        category = phase + "_validation"
        if phase == "normalization":
            if reason.startswith(("Settlement fee total", "Provider fee total")):
                category = "fee_reconciliation"
            elif reason.startswith(("Archived holdings", "Settlement cent revenue", "Settlement value", "Settlement cost")):
                category = "settlement_evidence"
            elif reason.startswith(("Missing live/archived", "Settlement quantity", "Provider net inventory", "Position has activity")):
                category = "historical_coverage"
        report["discrepancy_counts"][category] = 1
    except Exception:
        # No exception text, paths, response bodies, balances or account IDs.
        report["discrepancy_counts"][phase + "_validation"] = 1
    if report["authentication"] != "passed":
        report["authentication"] = "failed"
    else:
        report["reconciliation"] = "blocked" if phase == "independent_evidence" else "failed"
    return report, 2


def emit(report):
    serialized = canonical(report)
    print(serialized)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        level = "notice" if report["status"] == "passed" else "error"
        print(f"::{level} title=M14 private validation status::{serialized}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("### M14 private validation status\n\n```json\n" + serialized + "\n```\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("auth-only", "reconcile"), default="auth-only")
    parser.add_argument("--runner-temp", required=True)
    args = parser.parse_args()
    try:
        report, code = execute(args.mode, args.runner_temp, os.environ.get("KALSHI_API_KEY_ID", ""),
                               os.environ.get("KALSHI_PRIVATE_KEY", ""),
                               evidence_loader=lambda: load_private_evidence(args.runner_temp),
                               has_evidence=evidence_available(args.runner_temp))
        emit(report)
    except Exception:
        # Even report/cleanup failures must not produce an exception traceback.
        print('{"status":"failed","discrepancy_counts":{"private_validation":1}}')
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
