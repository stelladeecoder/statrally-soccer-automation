"""End-to-end synthetic local CLI checks; no network or live financial data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from m14_samples import bundle, fill, settlement

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def invoke(self, module, *args, expect=0):
        result = subprocess.run([sys.executable, str(ROOT / "src" / (module + ".py")), *map(str, args)],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expect, result.stderr)
        return result

    def test_repeat_import_report_and_dry_run_for_all_periods(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            snapshot = path / "synthetic.json"
            database = path / "synthetic.sqlite"
            snapshot.write_text(json.dumps(bundle([fill()], [settlement()])))
            first = json.loads(self.invoke("m14_import", "--snapshot", snapshot, "--database", database).stdout)
            second = json.loads(self.invoke("m14_import", "--snapshot", snapshot, "--database", database).stdout)
            self.assertEqual(first["event_count"], 2)
            self.assertEqual(second["new_source_records"], 0)
            self.assertEqual(database.stat().st_mode & 0o777, 0o600)
            for period in ("daily", "weekly", "cumulative"):
                report = json.loads(self.invoke("m14_performance", "--database", database, "--period", period, "--through", "2026-11-02").stdout)
                self.assertEqual(report["data_kind"], "synthetic")
                self.assertEqual(report["verification"], "unverified")
                output = json.loads(self.invoke("m14_results_publish", "--database", database, "--period", period, "--through", "2026-11-02").stdout)
                self.assertEqual(output["status"], "dry_run")
                self.assertIn("TEST — SYNTHETIC", output["payload"]["content"])
            rejected = self.invoke("m14_results_publish", "--database", database, "--through", "2026-11-02", "--send", expect=2)
            self.assertNotIn("Traceback", rejected.stderr)
            self.assertNotIn("SYNTHETIC-MARKET", rejected.stderr)
            self.assertEqual(rejected.stdout, "")

    def test_malformed_import_failure_does_not_leak_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            source = path / "private.json"
            source.write_text('{"SENSITIVE_ACCOUNT": invalid}')
            result = self.invoke("m14_import", "--snapshot", source, "--database", path / "ledger.sqlite", expect=2)
            self.assertNotIn("SENSITIVE_ACCOUNT", result.stderr)
            self.assertNotIn(str(source), result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_help_for_all_entrypoints(self):
        for module in ("m14_position_ledger", "m14_import", "m14_performance", "m14_results_publish"):
            with self.subTest(module=module):
                self.assertIn("usage:", self.invoke(module, "--help").stdout)
