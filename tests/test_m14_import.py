"""Synthetic SDK-response tests; no account access or HTTP requests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from m14_import import connect, import_snapshot, load_history, normalize_snapshot, read_json
from m14_samples import bundle, fill, page, settlement


class ImportTests(unittest.TestCase):
    def test_yes_settlement_with_fee_evidence(self):
        data = bundle([fill()], [settlement(fee="0.02")], {"synthetic-fill-1": "0.02"})
        result = normalize_snapshot(data)
        self.assertEqual([row["action"] for row in result["events"]], ["BUY", "SETTLE"])
        self.assertEqual(result["events"][0]["fee_usd"], "0.02")
        self.assertEqual(result["events"][1]["fee_usd"], "0")  # Never double-count cumulative fee_cost.
        self.assertEqual(len(result["sources"]), 3)

    def test_no_price_and_early_exit(self):
        data = bundle([fill(side="no"), fill("synthetic-exit", action="sell", side="no", yes="0.2000", no="0.8000", when="2026-11-02T12:00:00Z")])
        events = normalize_snapshot(data)["events"]
        self.assertEqual([row["price"] for row in events], ["0.6000", "0.8000"])
        self.assertEqual([row["action"] for row in events], ["BUY", "SELL"])

    def test_no_winning_settlement(self):
        data = bundle([fill(side="no")], [settlement(result="no", yes_count=0, no_count=2, yes_cost=0, no_cost=120)])
        events = normalize_snapshot(data)["events"]
        self.assertEqual(events[-1]["side"], "NO")
        self.assertEqual(events[-1]["price"], "1")

    def test_repeated_import_and_overlapping_duplicate_records(self):
        data = bundle([fill()], [settlement()])
        data["fills_pages"] = [page("fills", [fill()], cursor="next"), page("fills", [fill()], request_cursor="next")]
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            first = import_snapshot(db, data)
            second = import_snapshot(db, data)
            self.assertEqual(first["new_source_records"], 3)
            self.assertEqual(second["new_source_records"], 0)
            self.assertEqual(len(load_history(db)[0]), 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 3)

    def test_incremental_full_snapshot_and_atomic_conflict(self):
        first = bundle([fill()])
        second = bundle([fill()], [settlement()])
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            import_snapshot(db, first)
            self.assertEqual(import_snapshot(db, second)["new_source_records"], 1)
            changed = copy.deepcopy(second)
            changed["fill_fees"][0]["evidence_reference"] = "changed evidence"
            with self.assertRaises(ValueError):
                import_snapshot(db, changed)
            self.assertEqual(len(load_history(db)[0]), 2)
            with self.assertRaises(ValueError):
                import_snapshot(db, first)  # Dropping a prior settlement is not an incremental update.

    def test_cannot_mix_synthetic_and_live_store(self):
        data = bundle()
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "ledger.sqlite") as db:
            import_snapshot(db, data)
            data["data_kind"] = "live"
            with self.assertRaises(ValueError):
                import_snapshot(db, data)

    def test_empty_snapshot(self):
        self.assertEqual(normalize_snapshot(bundle())["events"], [])

    def test_bad_pagination(self):
        variants = [[], [page("fills", [], cursor="missing")],
                    [page("fills", [], request_cursor="not-first")],
                    [page("fills", []), page("fills", [])],
                    [page("fills", [], cursor="x"), page("fills", [], request_cursor="x", cursor="x")]]
        for value in variants:
            data = bundle()
            data["fills_pages"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_missing_fee_is_not_zero(self):
        data = bundle([fill()])
        data["fill_fees"] = []
        with self.assertRaises(ValueError):
            normalize_snapshot(data)

    def test_unknown_fee_and_conflicting_duplicate(self):
        data = bundle([fill()])
        data["fill_fees"].append({"fill_id": "unknown", "fee_usd": "0"})
        with self.assertRaises(ValueError):
            normalize_snapshot(data)
        data = bundle([fill(), fill(count=3)])
        with self.assertRaises(ValueError):
            normalize_snapshot(data)

    def test_missing_or_invalid_fill_fields(self):
        mutations = [{"fill_id": None}, {"ticker": ""}, {"count": True}, {"count": 0}, {"count": 1.5},
                     {"side": "other"}, {"action": "cancelled"}, {"trade_id": "conflict"},
                     {"yes_price_fixed": None}, {"no_price_fixed": "0.5"},
                     {"yes_price": 30}, {"created_time": "2026-11-01T12:00:00"}, {"ts": 0}]
        for changes in mutations:
            data = bundle([dict(fill(), **changes)])
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_legacy_timestamp_and_integer_cents(self):
        record = fill()
        del record["created_time"]
        record.update(ts=1793534400, yes_price=40, no_price=60)
        event = normalize_snapshot(bundle([record]))["events"][0]
        self.assertEqual(event["timestamp"], "2026-11-01T12:00:00+00:00")

    def test_partial_order_only_imports_executed_fill(self):
        data = bundle([fill(count=1)])
        data["orders"] = [{"status": "cancelled", "remaining_count": 99}]
        self.assertEqual(normalize_snapshot(data)["events"][0]["quantity"], 1)

    def test_missing_buy_oversell_and_ambiguous_order(self):
        for records in ([fill(action="sell")], [fill(), fill("exit", action="sell", count=3, when="2026-11-02T12:00:00Z")],
                        [fill(), fill("other")]):
            with self.subTest(records=records), self.assertRaises(ValueError):
                normalize_snapshot(bundle(records))

    def test_settlement_reconciliation_failures(self):
        for changes in ({"yes_count": 1}, {"yes_total_cost": 79}, {"revenue": 199},
                        {"fee_cost": "0.01"}, {"value": 0}, {"market_result": "scalar"},
                        {"market_result": "void"}, {"no_count": -1}):
            data = bundle([fill()], [dict(settlement(), **changes)])
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_snapshot(data)
        with self.assertRaises(ValueError):
            normalize_snapshot(bundle([], [settlement()]))

    def test_partial_sell_then_settlement_reconciles_remaining_basis(self):
        records = [fill(count=3), fill("exit", action="sell", count=1, when="2026-11-01T13:00:00Z")]
        events = normalize_snapshot(bundle(records, [settlement()]))["events"]
        self.assertEqual([e["quantity"] for e in events], [3, 1, 2])

    def test_opposite_side_netting_is_not_invented(self):
        records = [fill(), fill("opposite", side="no", when="2026-11-01T13:00:00Z")]
        with self.assertRaises(ValueError):
            normalize_snapshot(bundle(records))

    def test_late_trade_and_settlement_revision_are_rejected(self):
        records = [fill(), fill("late", when="2026-11-03T12:00:00Z")]
        with self.assertRaises(ValueError):
            normalize_snapshot(bundle(records, [settlement()]))
        with self.assertRaises(ValueError):
            normalize_snapshot(bundle([fill()], [settlement(), settlement(when="2026-11-03T12:00:00Z")]))

    def test_snapshot_inception_and_schema_required(self):
        for changes in ({"history_from_inception": False}, {"schema": "unknown"}, {"data_kind": None}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_snapshot(dict(bundle(), **changes))

    def test_private_state_paths_and_json_duplicate_keys(self):
        with self.assertRaises(ValueError):
            connect(Path(__file__).resolve().parents[1] / "personal.sqlite")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_text('{"schema":1,"schema":2}')
            with self.assertRaises(ValueError):
                read_json(path)
