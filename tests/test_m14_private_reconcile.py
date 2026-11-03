"""Synthetic statement/account responses only. No real credentials or HTTP."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import copy
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from m14_kalshi_client import ReadOnlyError
from m14_private_reconcile import EvidenceError, collect, compare, emit, execute, independent_evidence, load_private_evidence
from m14_import import normalize_snapshot
from m14_rest_samples import integration_snapshot, rest_bundle, rest_fill, rest_position

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
KEY_ID = "SYNTHETIC-KEY-ID"


def statement():
    # Independent, hand-calculated synthetic totals. Do NOT build expected
    # figures from the imported ledger in production or in this regression.
    return {"schema_version": 1, "source_type": "independent_account_statement", "reviewed": True,
            "evidence_reference": "SYNTHETIC-STATEMENT-ONLY",
            "api_key_id_sha256": hashlib.sha256(KEY_ID.encode()).hexdigest(),
            "scope": copy.deepcopy(integration_snapshot()["scope"]),
            "cutoff_exclusive": "2026-11-04T00:00:00Z",
            "coverage": {"history_from_inception": True, "historical_records_reviewed": True},
            "expected": {"realized_net_pnl_usd": "1.94", "fees_paid_usd": "0.06",
                         "gross_proceeds_usd": "3.60", "gross_buy_cost_usd": "1.60", "open_positions": []},
            "retained_settlements": []}


class FakeClient:
    def __init__(self, snapshot=None, failure=None):
        self.snapshot = copy.deepcopy(snapshot or integration_snapshot())
        self.calls = []
        self.failure = failure
        self.page_override = None
        self.observe = None
    def authenticate(self):
        self.calls.append(("/portfolio/balance", None))
        if self.failure:raise ReadOnlyError(self.failure)
    def get_json(self, route, query=None):
        self.calls.append((route, query))
        if self.observe:self.observe()
        if route == "/portfolio/subaccounts/netting":
            return {"netting_configs": [{"subaccount_number": 0, "exchange_index": 0, "enabled": True}]}
        if route == "/historical/cutoff":return copy.deepcopy(self.snapshot["historical_cutoff"])
        if self.page_override is not None:return copy.deepcopy(self.page_override)
        collection = next(value for value in self.snapshot["collections"].values() if value["endpoint"] == route)
        return copy.deepcopy(collection["pages"][0]["response"])


class PrivateReconciliationTests(unittest.TestCase):
    def run_with(self, client, root, evidence=None, mode="reconcile"):
        return execute(mode, root, KEY_ID, "SYNTHETIC-NOT-A-KEY", evidence or "",
                       client_factory=lambda *a: client, now=NOW)

    def test_auth_only_performs_no_record_reads_even_if_evidence_is_present(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(client, directory, "SENSITIVE_NOT_PARSED", mode="auth-only")
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(code, 0)
        self.assertEqual(report["authentication"], "passed")
        self.assertEqual(report["reconciliation"], "not_run")
        self.assertEqual(client.calls, [("/portfolio/balance", None)])

    def test_auth_failure_stops_before_evidence_or_transactions(self):
        client = FakeClient(failure="http_401")
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(client, directory, json.dumps(statement()))
        self.assertEqual(code, 2)
        self.assertEqual(report["authentication"], "failed")
        self.assertEqual(report["discrepancy_counts"], {"http_401": 1})
        self.assertEqual(len(client.calls), 1)

    def test_missing_evidence_blocks_reconciliation_after_authentication(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(client, directory)
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["authentication"], "passed")
        self.assertEqual(client.calls, [("/portfolio/balance", None)])

    def test_invalid_unreviewed_filtered_or_other_key_evidence_is_blocked(self):
        variants = [{"reviewed": False}, {"source_type": "same_api_response"}, {"api_key_id_sha256": "different-key"},
                    {"coverage": {"history_from_inception": False, "historical_records_reviewed": True}},
                    {"expected": {}}, {"cutoff_exclusive": "2027-01-01T00:00:00Z"}]
        for changes in variants:
            client = FakeClient()
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                report, code = self.run_with(client, directory, json.dumps(dict(statement(), **changes)))
            self.assertEqual(code, 2)
            self.assertEqual(report["discrepancy_counts"], {"independent_evidence_invalid": 1})
            self.assertEqual(len(client.calls), 1)

    def test_success_compares_independent_totals_without_publishing_them(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(client, directory, json.dumps(statement()))
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(code, 0)
        self.assertEqual(report["reconciliation"], "passed")
        self.assertEqual(sum(report["discrepancy_counts"].values()), 0)
        self.assertNotIn("1.94", json.dumps(report))
        self.assertEqual({path for path, query in client.calls}, {"/portfolio/balance", "/portfolio/subaccounts/netting", "/historical/cutoff",
            "/portfolio/fills", "/historical/fills", "/portfolio/settlements", "/portfolio/positions", "/historical/positions"})

    def test_statement_discrepancy_is_a_count_not_a_financial_value(self):
        evidence = statement()
        evidence["expected"]["realized_net_pnl_usd"] = "999.99"
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(FakeClient(), directory, json.dumps(evidence))
        self.assertEqual(code, 2)
        self.assertEqual(report["discrepancy_counts"]["realized_pnl"], 1)
        self.assertNotIn("999.99", json.dumps(report))
        self.assertNotIn("1.94", json.dumps(report))

    def test_missing_archive_settlement_fails_closed_and_cleans_private_files(self):
        snapshot = integration_snapshot()
        snapshot["collections"]["portfolio_settlements"]["pages"][0]["response"]["settlements"] = []
        positions = snapshot["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"]
        snapshot["collections"]["historical_positions"]["pages"][0]["response"]["market_positions"] = positions
        snapshot["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"] = []
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(FakeClient(snapshot), directory, json.dumps(statement()))
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(code, 2)
        self.assertEqual(report["discrepancy_counts"], {"settlement_evidence": 1})

    def test_fee_disagreement_fails_without_relabelling_source_values(self):
        snapshot = integration_snapshot()
        snapshot["collections"]["portfolio_settlements"]["pages"][0]["response"]["settlements"][0]["fee_cost"] = "0.07"
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(FakeClient(snapshot), directory, json.dumps(statement()))
        self.assertEqual(code, 2)
        self.assertEqual(report["discrepancy_counts"], {"fee_reconciliation": 1})

    def test_pagination_loop_fails_before_any_import(self):
        client = FakeClient()
        client.page_override = {"fills": [], "cursor": "repeat"}
        with tempfile.TemporaryDirectory() as directory:
            report, code = self.run_with(client, directory, json.dumps(statement()))
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(code, 2)
        self.assertEqual(report["discrepancy_counts"], {"historical_coverage": 1})

    def test_raw_files_are_owner_only_and_never_in_checkout(self):
        client, observed = FakeClient(), []
        with tempfile.TemporaryDirectory() as root:
            def observe():
                for directory in Path(root).iterdir():
                    observed.append(directory)
                    self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                    for file in directory.iterdir():
                        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            client.observe = observe
            report, code = self.run_with(client, root, json.dumps(statement()))
            self.assertTrue(observed)
            self.assertEqual(list(Path(root).iterdir()), [])
        self.assertEqual(code, 0)

    def test_sanitized_stdout_annotation_and_summary_never_contain_account_data(self):
        with tempfile.TemporaryDirectory() as root:
            report, _ = self.run_with(FakeClient(), root, json.dumps(statement()))
            output, error = StringIO(), StringIO()
            summary = Path(root) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(summary)}), redirect_stdout(output), redirect_stderr(error):
                emit(report)
            text = output.getvalue() + error.getvalue() + summary.read_text()
        for forbidden in (KEY_ID, "PRIVATE KEY", "SYNTHETIC", "1.94", "0.06", "1.60", "3.60", "balance", "market_ticker", "history_sha256"):
            with self.subTest(forbidden=forbidden):self.assertNotIn(forbidden, text)
        self.assertIn("M14 private validation status", text)

    def test_zero_and_tiny_open_basis_are_compared_exactly(self):
        for price, expected_basis in (("0.000000", "0"), ("0.000001", "0.00000001")):
            snapshot = rest_bundle(historical_fills=[rest_fill(count="0.01", yes=price, fee="0")],
                                   positions=[rest_position(quantity="0.01", fees="0")])
            events = normalize_snapshot(snapshot)["events"]
            evidence = statement()
            evidence["expected"] = {"realized_net_pnl_usd": "0", "fees_paid_usd": "0", "gross_proceeds_usd": "0",
                                    "gross_buy_cost_usd": expected_basis,
                                    "open_positions": [{"market_ticker": "SYNTHETIC-MARKET", "side": "YES", "quantity": "0.01", "basis_usd": expected_basis}]}
            self.assertFalse(any(compare(events, evidence).values()))

    def test_private_file_evidence_requires_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "statrally-m14-independent-evidence.json"
            path.write_text(json.dumps(statement()))
            path.chmod(0o600)
            self.assertEqual(json.loads(load_private_evidence(root))["source_type"], "independent_account_statement")
            path.chmod(0o644)
            with self.assertRaises(EvidenceError):load_private_evidence(root)

    def test_private_evidence_symlink_is_never_followed(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "other.json"
            target.write_text("SENSITIVE")
            (Path(root) / "statrally-m14-independent-evidence.json").symlink_to(target)
            with self.assertRaises(EvidenceError):load_private_evidence(root)

    def test_https_evidence_get_never_sends_kalshi_headers(self):
        requests = []
        class Response:
            status = 200
            def __enter__(self):return self
            def __exit__(self, *args):return None
            def read(self, size):return json.dumps(statement()).encode()
        def opener(request, timeout):
            requests.append(request)
            return Response()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"M14_RECONCILIATION_EVIDENCE_URL": "https://private.example.invalid/statement", "M14_EVIDENCE_ACCESS_TOKEN": "SYNTHETIC-ACCESS"}):
            load_private_evidence(root, opener=opener)
        self.assertEqual(requests[0].get_method(), "GET")
        self.assertIsNone(requests[0].get_header("Kalshi-access-key"))
        self.assertIsNone(requests[0].get_header("Kalshi-access-signature"))

    def test_insecure_evidence_sources_are_rejected_before_network(self):
        for url in ("http://example.invalid/statement", "https://user:pass@example.invalid/statement", "https://example.invalid:1234/statement"):
            with self.subTest(url=url), tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {"M14_RECONCILIATION_EVIDENCE_URL": url}):
                with self.assertRaises(EvidenceError):
                    load_private_evidence(root, opener=lambda *a, **k: self.fail("No request allowed"))

    def test_evidence_loader_runs_only_after_authentication_and_only_for_reconcile(self):
        with tempfile.TemporaryDirectory() as root:
            client = FakeClient()
            def load():
                self.assertEqual(client.calls, [("/portfolio/balance", None)])
                return json.dumps(statement())
            report, code = execute("auth-only", root, KEY_ID, "SYNTHETIC", client_factory=lambda *a: client,
                                   evidence_loader=lambda: self.fail("Auth-only must not read evidence"), has_evidence=True)
            self.assertEqual(code, 0)
            client.calls.clear()
            report, code = execute("reconcile", root, KEY_ID, "SYNTHETIC", client_factory=lambda *a: client,
                                   evidence_loader=load, has_evidence=True, now=NOW)
            self.assertEqual(code, 0)
