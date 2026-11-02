"""Synthetic source/engine callbacks; no real network calls or research model."""
from datetime import datetime, timezone
import unittest
from urllib.error import HTTPError

from m13_beta_capture import CaptureFailure, capture

NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


class CaptureTests(unittest.TestCase):
    def arguments(self):
        def markets(series, *, fetch, max_pages):
            return fetch("/markets", {"series_ticker": series})["markets"]
        def discover(*, now, markets_for, scoreboard):
            markets_for("SYNTHETIC-SERIES", 2)
            scoreboard("epl", "20261102")
            return []
        def export(mappings, *, evaluate, now):
            return {"schema_version": 1, "status": "experimental_paper", "trades_placed": 0,
                    "signals": [evaluate(item) for item in mappings]}
        return {"discover_fn": discover, "export_fn": export, "markets_fn": markets,
                "kalshi_fn": lambda *a: {"markets": []}, "scoreboard_fn": lambda *a: {"events": []},
                "reconcile_fn": lambda *a, **kw: {}, "evaluate_fn": lambda *a, **kw: {}, "now": NOW}

    def test_empty_real_responses_are_not_a_source_failure(self):
        envelope, diagnostics = capture([], **self.arguments())
        self.assertEqual(envelope["signals"], [])
        self.assertEqual(diagnostics["sources"]["kalshi"]["successful"], 1)
        self.assertEqual(diagnostics["sources"]["espn"]["successful"], 1)
        self.assertEqual(diagnostics["eligible_signals"], 0)

    def test_scan_and_evaluation_share_a_conservative_clock(self):
        args = self.arguments()
        def evaluate(mapping, **kwargs):
            # Original live exporter rejected observations made AFTER its own
            # starting clock. Integration must supply a consistent observation.
            self.assertEqual(kwargs["observed_at"], NOW.isoformat())
            return {"observed_at_utc": kwargs["observed_at"]}
        def export(mappings, *, evaluate, now):
            item = evaluate(mappings[0])
            self.assertLessEqual(datetime.fromisoformat(item["observed_at_utc"]), now)
            return {"signals": [item]}
        args.update(evaluate_fn=evaluate, export_fn=export)
        _, diagnostics = capture([{"market_ticker": "SYNTHETIC"}], **args)
        self.assertEqual(diagnostics["evaluations"]["successful"], 1)

    def test_suppressed_provider_error_cannot_become_zero_signals(self):
        args = self.arguments()
        def fail(*args):
            raise HTTPError("https://example.invalid/PRIVATE", 503, "unavailable", {}, None)
        def discover(*, now, markets_for, scoreboard):
            try:
                markets_for("SYNTHETIC", 2)
            except OSError:
                pass  # Simulates the private engine's conservative rejection.
            scoreboard("epl", "20261102")
            return []
        args.update(kalshi_fn=fail, discover_fn=discover)
        with self.assertRaises(CaptureFailure) as error:
            capture([], **args)
        self.assertEqual(error.exception.diagnostics["sources"]["kalshi"]["http_errors"], {"503": 1})
        self.assertNotIn("PRIVATE", str(error.exception.diagnostics))

    def test_malformed_response_is_not_an_empty_market_list(self):
        args = self.arguments()
        args["kalshi_fn"] = lambda *a: {"error": "bad shape"}
        with self.assertRaises(CaptureFailure):
            capture([], **args)

    def test_incomplete_market_pagination_cannot_look_successful(self):
        args = self.arguments()
        def markets(series, *, fetch, max_pages):
            fetch("/markets", {})
            raise RuntimeError("pagination incomplete")
        def discover(*, now, markets_for, scoreboard):
            try:
                markets_for("SYNTHETIC", 2)
            except RuntimeError:
                pass
            scoreboard("epl", "20261102")
            return []
        args.update(markets_fn=markets, discover_fn=discover)
        with self.assertRaises(CaptureFailure) as error:
            capture([], **args)
        self.assertEqual(error.exception.diagnostics["sources"]["kalshi"]["collection_failures"], 1)

    def test_both_providers_must_be_observed(self):
        args = self.arguments()
        args["discover_fn"] = lambda **kwargs: []
        with self.assertRaises(CaptureFailure):
            capture([], **args)

    def test_evaluation_io_failure_is_not_a_successful_no_pick(self):
        args = self.arguments()
        def evaluate(*a, **kw):
            raise OSError("private file/endpoint unavailable")
        def export(mappings, *, evaluate, now):
            try:
                evaluate(mappings[0])
            except OSError:
                pass
            return {"signals": []}
        args.update(evaluate_fn=evaluate, export_fn=export)
        with self.assertRaises(CaptureFailure):
            capture([{"market_ticker": "SYNTHETIC"}], **args)
