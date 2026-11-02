"""Synthetic accounting edge cases for the existing M14 FIFO ledger."""
from decimal import Decimal
import random
import unittest

from m14_position_ledger import summarize
from m14_samples import event

BUY_TIME = "2026-11-01T12:00:00Z"
EXIT_TIME = "2026-11-02T12:00:00Z"


class AccountingTests(unittest.TestCase):
    def test_partial_exit_allocates_only_matched_entry_fees(self):
        report = summarize([event("a", "BUY", 4, "0.40", BUY_TIME, "0.04"),
                            event("b", "SELL", 1, "0.60", EXIT_TIME, "0.02")])
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("0.17"))
        self.assertEqual(Decimal(report["positions"][0]["open_total_basis_usd"]), Decimal("1.23"))
        self.assertEqual(report["completed_positions"], [])

    def test_fifo_multiple_lots_preserves_open_basis(self):
        report = summarize([event("a", "BUY", 2, "0.20", BUY_TIME, "0.02"),
                            event("b", "BUY", 3, "0.50", EXIT_TIME, "0.06"),
                            event("c", "SELL", 3, "0.70", EXIT_TIME, "0.03")])
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("1.13"))
        self.assertEqual(Decimal(report["positions"][0]["open_total_basis_usd"]), Decimal("1.04"))

    def test_partial_settlements_and_no_win(self):
        events = [event("a", "BUY", 3, "0.60", BUY_TIME, "0.03", side="NO"),
                  event("b", "SETTLE", 1, "1", EXIT_TIME, side="NO"),
                  event("c", "SETTLE", 2, "1", EXIT_TIME, side="NO")]
        self.assertEqual(summarize(events[:2])["completed_positions"], [])
        report = summarize(events)
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("1.17"))
        self.assertEqual(len(report["completed_positions"]), 1)

    def test_no_losing_settlement(self):
        report = summarize([event("a", "BUY", 2, "0.60", BUY_TIME, side="NO"),
                            event("b", "SETTLE", 2, "0", EXIT_TIME, side="NO")])
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("-1.20"))

    def test_exit_fee_and_reopened_cycles(self):
        report = summarize([event("a", "BUY", 1, "0.4", BUY_TIME, "0.01"),
                            event("b", "SELL", 1, "0.6", EXIT_TIME, "0.02"),
                            event("c", "BUY", 1, "0.7", EXIT_TIME),
                            event("d", "SELL", 1, "0.6", EXIT_TIME)])
        self.assertEqual(len(report["completed_positions"]), 2)
        self.assertEqual([Decimal(row["realized_pnl_usd"]) for row in report["completed_positions"]],
                         [Decimal("0.17"), Decimal("-0.1")])

    def test_subcent_prices_preserved(self):
        report = summarize([event("a", "BUY", 3, "0.1234", BUY_TIME, "0.0003"),
                            event("b", "SELL", 3, "0.1235", EXIT_TIME)])
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("0"))

    def test_fee_remainder_conserved_across_partial_exits(self):
        events = [event("a", "BUY", 3, "0.4", BUY_TIME, "0.01")]
        events += [event(str(i), "SELL", 1, "0.6", EXIT_TIME) for i in range(3)]
        report = summarize(events)
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("0.59"))
        self.assertEqual(sum(Decimal(row["entry_fee_usd"]) for row in report["closures"]), Decimal("0.01"))

    def test_invalid_quantities(self):
        for value in (0, -1, 1.5, True, "2", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize([event("a", "BUY", value, "0.5", BUY_TIME)])

    def test_nonfinite_and_float_money(self):
        for value in ("NaN", "Infinity", "-Infinity", True, 0.1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize([event("a", "BUY", 1, value, BUY_TIME)])

    def test_event_order_and_timestamp_validation(self):
        for times in ((EXIT_TIME, BUY_TIME), (BUY_TIME, "2026-11-02T12:00:00")):
            with self.subTest(times=times), self.assertRaises(ValueError):
                summarize([event("a", "BUY", 1, "0.5", times[0]), event("b", "SELL", 1, "0.6", times[1])])
        row = event("b", "SELL", 1, "0.6", EXIT_TIME)
        del row["timestamp"]
        with self.assertRaises(ValueError):
            summarize([event("a", "BUY", 1, "0.5", BUY_TIME), row])

    def test_contradictory_settlement_and_trading_after_settlement(self):
        base = [event("a", "BUY", 1, "0.4", BUY_TIME), event("b", "BUY", 1, "0.6", BUY_TIME, side="NO"),
                event("c", "SETTLE", 1, "1", EXIT_TIME)]
        for last in (event("d", "SETTLE", 1, "1", EXIT_TIME, side="NO"),
                     event("d", "BUY", 1, "0.4", EXIT_TIME)):
            with self.subTest(last=last), self.assertRaises(ValueError):
                summarize(base + [last])

    def test_empty_history(self):
        report = summarize([])
        self.assertEqual(report["positions"], [])
        self.assertEqual(report["completed_positions"], [])
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), 0)

    def test_cash_and_open_basis_conservation(self):
        rng = random.Random(14)
        for trial in range(50):
            events = []
            held = 0
            cash = Decimal("0")
            for index in range(20):
                buy = not held or rng.choice((True, False))
                quantity = rng.randint(1, 5) if buy else rng.randint(1, held)
                price = Decimal(rng.randint(1, 99)) / 100
                fee = Decimal(rng.randint(0, 5)) / 100
                events.append(event(str(index), "BUY" if buy else "SELL", quantity, str(price), BUY_TIME, str(fee)))
                held += quantity if buy else -quantity
                cash += (-quantity * price if buy else quantity * price) - fee
            report = summarize(events)
            with self.subTest(trial=trial):
                self.assertEqual(report["positions"][0]["open_contracts"], held)
                self.assertEqual(Decimal(report["total_realized_pnl_usd"]),
                                 cash + Decimal(report["positions"][0]["open_total_basis_usd"]))

    def test_out_of_range_precision_is_rejected(self):
        for quantity, price, fee in ((2**63, "0.5", "0"), (1, "0.1234567890123456789", "0"),
                                     (1, "0.5", "1e18")):
            with self.subTest(quantity=quantity, price=price, fee=fee), self.assertRaises(ValueError):
                summarize([event("a", "BUY", quantity, price, BUY_TIME, fee)])
