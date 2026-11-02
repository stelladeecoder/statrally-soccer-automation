"""Synthetic metric and independent-reconciliation regression tests."""
import copy
from decimal import Decimal
import unittest

from m14_performance import build_report
from m14_samples import event


def history():
    return [event("a", "BUY", 4, "0.40", "2026-11-01T12:00:00Z", "0.04"),
            event("b", "SELL", 1, "0.60", "2026-11-02T12:00:00Z", "0.02"),
            event("c", "SETTLE", 3, "1", "2026-11-03T12:00:00Z")]


def attestation(report):
    # Synthetic test helper only. Production evidence must be independent, never
    # populated by copying computed totals as this intentionally synthetic test does.
    return {"schema_version": 1, "reviewed": True, "data_kind": "live",
            "history_sha256": report["history_sha256"], "cutoff_exclusive": report["cutoff_exclusive"],
            "evidence_reference": "SYNTHETIC TEST REVIEW ONLY", "expected": copy.deepcopy(report["reconciliation_values"])}


class PerformanceTests(unittest.TestCase):
    def report(self, events=None, period="daily", through="2026-11-02"):
        return build_report(history() if events is None else events, "synthetic", period, through)

    def test_partial_close_roi_and_unresolved_positions(self):
        report = self.report()
        m = report["metrics"]
        self.assertEqual(Decimal(m["realized_net_pnl_usd"]), Decimal("0.17"))
        self.assertEqual(Decimal(m["closed_entry_cost_usd"]), Decimal("0.41"))
        self.assertAlmostEqual(Decimal(m["roi"]), Decimal("0.17") / Decimal("0.41"), delta=Decimal("1e-27"))
        self.assertEqual(m["completed_positions"], 0)
        self.assertIsNone(m["win_rate"])
        self.assertEqual(report["open_positions"][0]["quantity"], 3)
        self.assertEqual(Decimal(m["fees_paid_usd"]), Decimal("0.02"))
        self.assertEqual(Decimal(m["recognized_fees_usd"]), Decimal("0.03"))
        self.assertEqual(m["early_exit_contracts"], 1)
        self.assertIsNone(report["unrealized_pnl_usd"])

    def test_settlement_completion_and_period_definitions(self):
        report = self.report(through="2026-11-03")
        self.assertEqual(report["metrics"]["wins"], 1)
        self.assertEqual(report["metrics"]["completed_positions"], 1)
        self.assertEqual(Decimal(report["metrics"]["realized_net_pnl_usd"]), Decimal("1.77"))
        self.assertEqual(Decimal(report["metrics"]["completed_position_pnl_usd"]), Decimal("1.94"))
        self.assertEqual(Decimal(report["cumulative"]["realized_net_pnl_usd"]), Decimal("1.94"))
        self.assertEqual(report["open_positions"], [])

    def test_win_loss_breakeven_denominator_and_no_side(self):
        events = []
        for index, (price, payout, side) in enumerate((("0.4", "1", "YES"), ("0.6", "0", "NO"), ("1", "1", "YES"))):
            ticker = "SYNTHETIC-" + str(index)
            events.append(event("buy" + str(index), "BUY", 1, price, "2026-11-01T12:00:00Z", side=side, ticker=ticker))
        for index, (_, payout, side) in enumerate((("0.4", "1", "YES"), ("0.6", "0", "NO"), ("1", "1", "YES"))):
            events.append(event("close" + str(index), "SETTLE", 1, payout, "2026-11-02T12:00:00Z", side=side, ticker="SYNTHETIC-" + str(index)))
        m = self.report(events)["metrics"]
        self.assertEqual((m["wins"], m["losses"], m["breakeven"], m["completed_positions"]), (1, 1, 1, 3))
        self.assertAlmostEqual(Decimal(m["win_rate"]), Decimal(1) / 3, delta=Decimal("1e-27"))
        self.assertAlmostEqual(Decimal(m["loss_rate"]), Decimal(1) / 3, delta=Decimal("1e-27"))
        self.assertEqual(Decimal(m["roi"]), 0)

    def test_empty_and_zero_cost_denominators(self):
        m = self.report([])["metrics"]
        self.assertEqual(m["completed_positions"], 0)
        self.assertIsNone(m["roi"])
        self.assertIsNone(m["loss_rate"])
        events = [event("a", "BUY", 1, "0", "2026-11-01T12:00:00Z"), event("b", "SELL", 1, "1", "2026-11-02T12:00:00Z")]
        self.assertIsNone(self.report(events)["metrics"]["roi"])

    def test_open_only_has_fees_but_no_realized_outcome(self):
        report = self.report(history()[:1], period="cumulative")
        self.assertEqual(Decimal(report["metrics"]["realized_net_pnl_usd"]), 0)
        self.assertEqual(Decimal(report["metrics"]["fees_paid_usd"]), Decimal("0.04"))
        self.assertEqual(report["metrics"]["completed_positions"], 0)

    def test_weekly_and_cumulative_series(self):
        weekly = self.report(period="weekly", through="2026-11-03")
        self.assertTrue(weekly["start_inclusive"].startswith("2026-11-02"))
        self.assertEqual(Decimal(weekly["metrics"]["fees_paid_usd"]), Decimal("0.02"))
        cumulative = self.report(period="cumulative", through="2026-11-03")
        self.assertEqual([row["date"] for row in cumulative["performance_over_time"]], ["2026-11-01", "2026-11-02", "2026-11-03"])
        self.assertEqual(Decimal(cumulative["performance_over_time"][-1]["cumulative_realized_net_pnl_usd"]), Decimal("1.94"))
        self.assertIn("SYNTHETIC-MARKET", cumulative["metrics"]["profit_by_market_usd"])

    def test_chicago_dst_and_exclusive_cutoff(self):
        events = [event("a", "BUY", 1, "0.4", "2026-11-01T06:30:00Z"),
                  event("b", "SELL", 1, "0.5", "2026-11-01T07:30:00Z"),
                  event("c", "BUY", 1, "0.4", "2026-11-02T06:00:00Z")]
        report = self.report(events, through="2026-11-01")
        self.assertEqual(report["start_inclusive"], "2026-11-01T00:00:00-05:00")
        self.assertEqual(report["cutoff_exclusive"], "2026-11-02T00:00:00-06:00")
        self.assertEqual(report["open_positions"], [])
        self.assertEqual(report["metrics"]["completed_positions"], 1)

    def test_calendar_report_rejects_untimed_and_missing_buy(self):
        row = history()[0]
        del row["timestamp"]
        with self.assertRaises(ValueError):
            self.report([row])
        with self.assertRaises(ValueError):
            self.report(history()[1:])

    def test_independent_reconciliation_gate(self):
        base = build_report(history(), "live", "daily", "2026-11-02")
        self.assertEqual(base["verification"], "unverified")
        review = attestation(base)
        verified = build_report(history(), "live", "daily", "2026-11-02", review)
        self.assertEqual(verified["verification"], "operator_reconciled")
        for changes in ({"history_sha256": "stale"}, {"reviewed": False}, {"cutoff_exclusive": "wrong"},
                        {"data_kind": "synthetic"}, {"evidence_reference": ""}, {"expected": {}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_report(history(), "live", "daily", "2026-11-02", dict(review, **changes))

    def test_reconciliation_totals_and_open_inventory_must_match(self):
        base = build_report(history(), "live", "daily", "2026-11-02")
        for field in ("fees_paid_usd", "realized_net_pnl_usd", "gross_buy_cost_usd", "gross_proceeds_usd"):
            review = attestation(base)
            review["expected"][field] = "999"
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_report(history(), "live", "daily", "2026-11-02", review)
        review = attestation(base)
        review["expected"]["open_positions"][0]["quantity"] = 4
        with self.assertRaises(ValueError):
            build_report(history(), "live", "daily", "2026-11-02", review)

    def test_synthetic_cannot_be_marked_live_verified(self):
        base = self.report()
        with self.assertRaises(ValueError):
            build_report(history(), "synthetic", "daily", "2026-11-02", attestation(base))
