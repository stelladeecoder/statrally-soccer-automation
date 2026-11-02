"""Current-schema synthetic regressions; no authenticated/live data requests."""
import copy
from decimal import Decimal, Inexact, ROUND_UP, localcontext
from pathlib import Path
import tempfile
import unittest

from m14_import import connect, import_snapshot, load_history, normalize_snapshot
from m14_performance import build_report
from m14_position_ledger import summarize
from m14_rest_samples import (add_open_fill, integration_snapshot, rest_bundle, rest_fill,
                              rest_page, rest_position, rest_settlement)


class CurrentRESTTests(unittest.TestCase):
    def test_source_fee_and_dollar_settlement_without_external_fee_map(self):
        normalized = normalize_snapshot(integration_snapshot())
        report = summarize(normalized["events"])
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("1.94"))
        self.assertEqual(Decimal(report["total_fees_usd"]), Decimal("0.06"))
        self.assertEqual([event["action"] for event in normalized["events"]], ["BUY", "SELL", "SETTLE"])
        self.assertEqual(normalized["events"][-1]["fee_usd"], "0")

    def test_fractional_yes_win_and_no_loss_settlements(self):
        for direction, result, payout in (("yes", "yes", "1.48"), ("no", "yes", "-1.52")):
            buy = rest_fill(direction=direction, count="2.50")
            settled = rest_settlement(yes_count="2.50" if direction == "yes" else "0.00", no_count="2.50" if direction == "no" else "0.00",
                                      yes_cost="1.000000" if direction == "yes" else "0.000000", no_cost="1.500000" if direction == "no" else "0.000000",
                                      result=result, revenue=250 if direction == "yes" else 0)
            data = rest_bundle(historical_fills=[buy], settlements=[settled],
                               positions=[rest_position(quantity="0.00", exposure="0", when="2026-11-03T12:00:00Z")])
            with self.subTest(direction=direction):
                events = normalize_snapshot(data)["events"]
                self.assertEqual(events[0]["quantity"], "2.50")
                self.assertEqual(Decimal(summarize(events)["total_realized_pnl_usd"]), Decimal(payout))

    def test_fractional_partial_exit_and_roi(self):
        data = rest_bundle(historical_fills=[rest_fill(count="2.50", fee="0.025000")],
                           fills=[rest_fill("exit", direction="no", count="0.50", yes="0.600000", fee="0.005000", when="2026-11-02T12:00:00Z")],
                           positions=[rest_position(quantity="2.00", fees="0.030000")])
        events = normalize_snapshot(data)["events"]
        report = build_report(events, "synthetic", "daily", "2026-11-02")
        self.assertEqual(Decimal(report["metrics"]["realized_net_pnl_usd"]), Decimal("0.09"))
        self.assertEqual(Decimal(report["metrics"]["closed_entry_cost_usd"]), Decimal("0.205"))
        self.assertEqual(report["metrics"]["early_exit_contracts"], "0.50")
        self.assertEqual(report["metrics"]["completed_positions"], 0)
        self.assertEqual(report["open_positions"][0]["quantity"], 2)
        self.assertEqual(Decimal(report["open_positions"][0]["basis_usd"]), Decimal("0.82"))

    def test_netting_flip_splits_fee_and_uses_correct_leg_prices(self):
        data = rest_bundle(historical_fills=[rest_fill(count="1.00", fee="0.010000")],
                           fills=[rest_fill("flip", direction="no", count="2.50", yes="0.600000", fee="0.025000", when="2026-11-02T12:00:00Z")],
                           positions=[rest_position(quantity="-1.50", fees="0.035000")])
        events = normalize_snapshot(data)["events"]
        self.assertEqual([(e["action"], e["side"], e["quantity"]) for e in events], [("BUY", "YES", 1), ("SELL", "YES", 1), ("BUY", "NO", "1.50")])
        self.assertEqual([Decimal(e["fee_usd"]) for e in events], [Decimal("0.01"), Decimal("0.01"), Decimal("0.015")])
        self.assertEqual([Decimal(e["price"]) for e in events], [Decimal("0.4"), Decimal("0.6"), Decimal("0.4")])
        self.assertEqual(Decimal(summarize(events)["total_realized_pnl_usd"]), Decimal("0.18"))

    def test_legacy_direction_must_agree_with_current_direction(self):
        for side, action, direction in (("yes", "buy", "yes"), ("no", "sell", "yes"), ("no", "buy", "no"), ("yes", "sell", "no")):
            buy = dict(rest_fill(direction=direction), side=side, action=action)
            data = rest_bundle(historical_fills=[buy], positions=[rest_position(quantity="2.00" if direction == "yes" else "-2.00")])
            with self.subTest(side=side, action=action):
                normalize_snapshot(data)
                buy["action"] = "sell" if action == "buy" else "buy"
                with self.assertRaises(ValueError):
                    normalize_snapshot(data)

    def test_subcent_prices_stay_decimal(self):
        buy = rest_fill(count="0.25", yes="0.123400", fee="0.000100")
        data = rest_bundle(historical_fills=[buy], positions=[rest_position(quantity="0.25", fees="0.000100")])
        p = summarize(normalize_snapshot(data)["events"])["positions"][0]
        self.assertEqual(Decimal(p["open_total_basis_usd"]), Decimal("0.03095"))

    def test_live_historical_overlap_deduplicates_and_repeat_imports(self):
        data = integration_snapshot()
        data["collections"]["portfolio_fills"]["pages"][0]["response"]["fills"].insert(0, copy.deepcopy(data["collections"]["historical_fills"]["pages"][0]["response"]["fills"][0]))
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "rest.sqlite") as db:
            self.assertEqual(import_snapshot(db, data)["event_count"], 3)
            self.assertEqual(import_snapshot(db, data)["new_source_records"], 0)
            events, kind = load_history(db)
            self.assertEqual(len(events), 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rest_snapshots").fetchone()[0], 1)
            self.assertEqual(kind, "synthetic")

    def test_archived_position_never_becomes_a_fabricated_settlement(self):
        buy = rest_fill()
        archived = rest_position(quantity="0.00", exposure="0", when="2026-11-03T12:00:00Z")
        data = rest_bundle(historical_fills=[buy], archived=[archived])
        with self.assertRaisesRegex(ValueError, "retained reviewed closure"):
            normalize_snapshot(data)
        data["retained_settlements"] = [{"record": rest_settlement(), "reviewed": True, "evidence_reference": "SYNTHETIC-RETAINED-SETTLEMENT"}]
        events = normalize_snapshot(data)["events"]
        self.assertEqual([e["action"] for e in events], ["BUY", "SETTLE"])
        self.assertEqual(events[-1]["timestamp"], "2026-11-03T12:00:00+00:00")
        data["retained_settlements"][0]["reviewed"] = False
        with self.assertRaises(ValueError):
            normalize_snapshot(data)

    def test_cutoff_horizon_is_not_an_archive_partition(self):
        data = integration_snapshot()
        data["historical_cutoff"]["market_positions_last_updated_ts"] = "2026-11-04T00:00:00Z"
        # Settled record older than backfill horizon can STILL be in the live
        # collection during whole-event handoff; do not invent an archive gap.
        self.assertEqual(len(normalize_snapshot(data)["events"]), 3)

    def test_archival_handoff_preserves_previously_observed_sources(self):
        first = integration_snapshot()
        next_snapshot = copy.deepcopy(first)
        record = next_snapshot["collections"]["portfolio_settlements"]["pages"][0]["response"]["settlements"].pop()
        next_snapshot["retained_settlements"] = [{"record": record, "reviewed": True, "evidence_reference": "SYNTHETIC-RETAINED"}]
        pos = next_snapshot["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"].pop()
        next_snapshot["collections"]["historical_positions"]["pages"][0]["response"]["market_positions"].append(pos)
        next_snapshot["captured_at"] = "2026-11-06T12:00:00Z"
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "rest.sqlite") as db:
            import_snapshot(db, first)
            self.assertEqual(import_snapshot(db, next_snapshot)["new_source_records"], 0)
            self.assertEqual(len(load_history(db)[0]), 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rest_snapshots").fetchone()[0], 2)

    def test_missing_collections_and_filtered_histories_are_rejected(self):
        for name in integration_snapshot()["collections"]:
            data = integration_snapshot()
            del data["collections"][name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                normalize_snapshot(data)
        for key, value in (("min_ts", 1), ("ticker", "SYNTHETIC-MARKET"), ("count_filter", "position")):
            data = integration_snapshot()
            data["collections"]["portfolio_positions"]["query"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_paginated_current_responses_and_cursor_failures(self):
        data = integration_snapshot()
        collection = data["collections"]["historical_fills"]
        record = collection["pages"][0]["response"]["fills"][0]
        collection["pages"] = [rest_page("fills", [record], cursor="next"), rest_page("fills", [record], request="next")]
        self.assertEqual(len(normalize_snapshot(data)["events"]), 3)
        for pages in ([rest_page("fills", [record], cursor="missing")],
                      [rest_page("fills", [record], request="crossed")],
                      [rest_page("fills", [record], cursor="loop"), rest_page("fills", [], request="loop", cursor="loop")]):
            collection["pages"] = pages
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_scope_conflicts_are_rejected(self):
        for field, value in (("subaccount_number", 1), ("subaccount_number", None), ("exchange_index", 1), ("book_side", "ask")):
            data = integration_snapshot()
            data["collections"]["historical_fills"]["pages"][0]["response"]["fills"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_snapshot(data)
        data = integration_snapshot()
        data["scope"]["netting_mode"] = "unknown"
        with self.assertRaises(ValueError):
            normalize_snapshot(data)

    def test_missing_fees_invalid_fixed_point_and_unknown_schema_fields(self):
        for field, value in (("fee_cost", None), ("fee_cost", "-0.01"), ("fee_cost", 0.02), ("count_fp", "2.001"),
                             ("count_fp", "0.00"), ("count_fp", 2), ("yes_price_dollars", "0.4e0"),
                             ("no_price_dollars", "0.500000"), ("unreviewed_field", "new schema")):
            data = integration_snapshot()
            data["collections"]["historical_fills"]["pages"][0]["response"]["fills"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_settlement_amount_count_fee_and_scalar_failures(self):
        for field, value in (("revenue", 299), ("revenue", "300"), ("yes_count_fp", "2.99"), ("yes_total_cost_dollars", "1.19"),
                             ("fee_cost", "0.07"), ("market_result", "scalar"), ("value", 0)):
            data = integration_snapshot()
            data["collections"]["portfolio_settlements"]["pages"][0]["response"]["settlements"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_missing_fill_market_inventory_and_fee_evidence(self):
        data = integration_snapshot()
        data["collections"]["historical_fills"]["pages"][0]["response"]["fills"] = []
        with self.assertRaises(ValueError):
            normalize_snapshot(data)
        for field, value in (("position_fp", "1.00"), ("fees_paid_dollars", "0.07")):
            data = integration_snapshot()
            data["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                normalize_snapshot(data)
        with self.assertRaises(ValueError):
            normalize_snapshot(rest_bundle(positions=[rest_position(quantity="0.00")]))

    def test_old_fill_only_in_live_collection_cannot_supply_archive_coverage(self):
        with self.assertRaises(ValueError):
            normalize_snapshot(rest_bundle(fills=[rest_fill()], positions=[rest_position()]))

    def test_conflicting_duplicates_and_changed_scope_do_not_mutate_store(self):
        data = integration_snapshot()
        conflicting = copy.deepcopy(data["collections"]["historical_fills"]["pages"][0]["response"]["fills"][0])
        conflicting["fee_cost"] = "0.050000"
        data["collections"]["portfolio_fills"]["pages"][0]["response"]["fills"].append(conflicting)
        with self.assertRaises(ValueError):
            normalize_snapshot(data)
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "rest.sqlite") as db:
            import_snapshot(db, integration_snapshot())
            changed = integration_snapshot()
            changed["scope"]["account_ref"] = "SYNTHETIC-OTHER-ACCOUNT"
            with self.assertRaises(ValueError):
                import_snapshot(db, changed)
            self.assertEqual(len(load_history(db)[0]), 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rest_snapshots").fetchone()[0], 1)

    def test_empty_history_needs_all_empty_collections(self):
        self.assertEqual(normalize_snapshot(rest_bundle())["events"], [])

    def test_missing_position_coverage_and_stale_components_are_rejected(self):
        for change in ("missing_positions", "stale_position", "future_fill", "future_cutoff"):
            data = integration_snapshot()
            if change == "missing_positions":
                data["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"] = []
            elif change == "stale_position":
                data["collections"]["portfolio_positions"]["pages"][0]["response"]["market_positions"][0]["last_updated_ts"] = "2026-11-01T00:00:00Z"
            elif change == "future_fill":
                data["collections"]["historical_fills"]["pages"][0]["response"]["fills"][0]["created_time"] = "2026-11-06T00:00:00Z"
            else:
                data["historical_cutoff"]["trades_created_ts"] = "2026-11-06T00:00:00Z"
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize_snapshot(data)

    def test_independently_optional_deprecated_direction_fields(self):
        for optional in ({"side": "no"}, {"action": "sell"}):
            data = rest_bundle(historical_fills=[dict(rest_fill(), **optional)], positions=[rest_position()])
            # Neither optional field alone overrides canonical direction.
            self.assertEqual(normalize_snapshot(data)["events"][0]["side"], "YES")

    def test_snapshot_integrity_and_legacy_store_separation(self):
        from m14_samples import bundle
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "rest.sqlite") as db:
            import_snapshot(db, integration_snapshot())
            with self.assertRaises(ValueError):
                import_snapshot(db, bundle())
            with db:
                db.execute("UPDATE rest_snapshots SET record='{}'")
            with self.assertRaises(ValueError):
                load_history(db)

    def test_source_changes_do_not_commit_a_new_snapshot(self):
        with tempfile.TemporaryDirectory() as directory, connect(Path(directory) / "rest.sqlite") as db:
            data = integration_snapshot()
            import_snapshot(db, data)
            # Economic values are unchanged but a previously retained raw source
            # changes; source immutability must reject and roll back metadata.
            data["collections"]["historical_fills"]["pages"][0]["response"]["fills"][0]["order_id"] = "SYNTHETIC-CHANGED-ORDER"
            with self.assertRaises(ValueError):
                import_snapshot(db, data)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM rest_snapshots").fetchone()[0], 1)
            self.assertEqual(len(load_history(db)[0]), 3)

    def test_current_adapter_is_independent_of_decimal_context(self):
        from m14_kalshi_rest import normalize_current
        data = integration_snapshot()
        expected = normalize_snapshot(data)
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_UP
            context.traps[Inexact] = True
            self.assertEqual(normalize_snapshot(data), expected)
            self.assertEqual(normalize_current(data), expected)

    def test_archived_early_exit_has_no_fabricated_settlement(self):
        buy = rest_fill(count="1.00", fee="0.010000")
        sell = rest_fill("early-exit", direction="no", count="1.00", yes="0.300000", fee="0.010000", when="2026-11-01T13:00:00Z")
        archived = rest_position(quantity="0.00", fees="0.020000", exposure="0", traded="0.700000", pnl="-0.120000")
        data = rest_bundle(historical_fills=[buy, sell], archived=[archived])
        events = normalize_snapshot(data)["events"]
        self.assertEqual([event["action"] for event in events], ["BUY", "SELL"])
        self.assertEqual(Decimal(summarize(events)["total_realized_pnl_usd"]), Decimal("-0.12"))

    def test_fractional_fifo_multiple_entries_and_partial_settlement(self):
        # Direct ledger regression: current fill normalization must not require
        # integer quantities or charge fees from the still-open fractional lot.
        from m14_samples import event
        events = [event("one", "BUY", "1.50", "0.2", "2026-11-01T12:00:00Z", "0.015"),
                  event("two", "BUY", "1.00", "0.4", "2026-11-01T13:00:00Z", "0.01"),
                  event("exit", "SELL", "1.75", "0.6", "2026-11-02T12:00:00Z", "0.0175"),
                  event("partial", "SETTLE", "0.25", "1", "2026-11-03T12:00:00Z")]
        report = summarize(events)
        self.assertEqual(report["positions"][0]["open_contracts"], "0.50")
        self.assertEqual(report["completed_positions"], [])
        self.assertEqual(Decimal(report["positions"][0]["open_total_basis_usd"]), Decimal("0.205"))
        self.assertEqual(Decimal(report["total_realized_pnl_usd"]), Decimal("0.7625"))
