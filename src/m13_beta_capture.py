"""Observe the private beta engine's read-only calls without publishing its code.

Only provider counts/statuses enter public logs. Signal generation remains in the
private engine; this wrapper never creates a fallback pick or changes its gates.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError


class CaptureFailure(RuntimeError):
    def __init__(self, diagnostics):
        super().__init__("Beta source capture incomplete; refusing to claim zero eligible signals")
        self.diagnostics = diagnostics


def capture(mappings, *, discover_fn, export_fn, markets_fn, kalshi_fn,
            scoreboard_fn, reconcile_fn, evaluate_fn, now=None):
    if not isinstance(mappings, list):
        raise ValueError("Reviewed mapping manifest must be a list")
    # A scan-start timestamp is conservative: no later quote is stamped newer
    # than the exporter's eligibility clock. Posting rechecks actual wall time.
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("Aware scan clock required")
    sources = {name: {"requests": 0, "successful": 0, "failed": 0, "collection_failures": 0, "records_observed": 0,
                      "http_errors": {}} for name in ("kalshi", "espn")}
    evaluations = {"attempted": 0, "successful": 0, "rejected": 0, "transport_failures": 0}

    def request(provider, callback, *args, **kwargs):
        counters = sources[provider]
        counters["requests"] += 1
        try:
            data = callback(*args, **kwargs)
            if not isinstance(data, dict):
                raise ValueError("Provider object required")
            path = args[0]
            if provider == "espn":
                key, shape = "events", list
            elif path == "/markets":
                key, shape = "markets", list
            elif path.endswith("/orderbook"):
                key, shape = "orderbook_fp", dict
            else:
                key, shape = "market", dict
            if not isinstance(data.get(key), shape):
                raise ValueError("Provider schema changed")
            if shape is list and any(not isinstance(item, dict) for item in data[key]):
                raise ValueError("Malformed provider record")
        except Exception as error:
            counters["failed"] += 1
            if isinstance(error, HTTPError):
                status = str(error.code)
                counters["http_errors"][status] = counters["http_errors"].get(status, 0) + 1
            raise
        counters["successful"] += 1
        counters["records_observed"] += len(data[key]) if shape is list else 1
        return data

    def kalshi(path, params=None):
        return request("kalshi", kalshi_fn, path, params)

    def scoreboard(league, day):
        return request("espn", scoreboard_fn, league, day)

    def markets(series, max_pages):
        try:
            return markets_fn(series, fetch=kalshi, max_pages=max_pages)
        except Exception:
            sources["kalshi"]["collection_failures"] += 1
            raise

    def reconcile(market, mapping, observed_at):
        return reconcile_fn(market, mapping, observed_at, fetch=scoreboard)

    def evaluate(mapping):
        evaluations["attempted"] += 1
        try:
            result = evaluate_fn(mapping, fetch=kalshi, reconcile=reconcile,
                                 observed_at=clock.isoformat())
        except Exception as error:
            evaluations["rejected"] += 1
            if isinstance(error, OSError):
                evaluations["transport_failures"] += 1
            raise
        evaluations["successful"] += 1
        return result

    diagnostics = {"status": "real_provider_capture", "scan_started_at_utc": clock.isoformat(),
                   "sources": sources, "reviewed_mappings": len(mappings), "discovered_mappings": None,
                   "evaluations": evaluations, "eligible_signals": None}
    try:
        discovered = discover_fn(now=clock, markets_for=markets, scoreboard=scoreboard)
        if not isinstance(discovered, list):
            raise ValueError("Discovery mappings must be a list")
        diagnostics["discovered_mappings"] = len(discovered)
        seen = {item.get("market_ticker") for item in mappings if isinstance(item, dict)}
        combined = list(mappings) + [item for item in discovered if item.get("market_ticker") not in seen]
        envelope = export_fn(combined, evaluate=evaluate, now=clock)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("signals"), list):
            raise ValueError("Malformed export envelope")
        diagnostics["eligible_signals"] = len(envelope["signals"])
    except Exception:
        diagnostics["status"] = "engine_capture_failed"
        raise CaptureFailure(diagnostics) from None
    if any(not value["successful"] or value["failed"] or value["collection_failures"] for value in sources.values()) or evaluations["transport_failures"]:
        diagnostics["status"] = "source_capture_failed"
        raise CaptureFailure(diagnostics)
    return envelope, diagnostics


def write_diagnostics(diagnostics):
    # No raw URLs, response bodies, exception strings, model internals or secrets.
    print(json.dumps(diagnostics, sort_keys=True))
    # Structured source-health telemetry is also a normal Actions annotation,
    # accessible through the Checks API without exposing raw provider responses.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        notice = json.dumps(diagnostics, sort_keys=True).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        level = "notice" if diagnostics["status"] == "real_provider_capture" else "error"
        print(f"::{level} title=Beta read-only source diagnostics::{notice}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("### Read-only beta source capture\n\n")
            for name, source in diagnostics["sources"].items():
                stream.write(f"- {name}: {source['successful']} successful requests, {source['failed']} failed, {source['collection_failures']} collection errors; "
                             f"{source['records_observed']} raw records observed.\n")
            stream.write(f"- Eligible experimental signals: {diagnostics['eligible_signals']}\n")
            stream.write("- No account transactions or orders accessed.\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mappings", default="config/m12_reviewed_fixtures.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    # These imports resolve only in the private-engine checkout supplied by the
    # workflow. Nothing from that checkout is copied to the public repository.
    from m13_beta_auto_discovery import discover
    from m13_beta_export import export
    from kalshi_markets import fetch_json, list_open_markets
    from kalshi_espn_fixtures import fetch_scoreboard, reconcile_espn
    from m12_kalshi_decision_pipeline import evaluate_verified_market
    try:
        envelope, diagnostics = capture(json.loads(Path(args.mappings).read_text(encoding="utf-8")),
            discover_fn=discover, export_fn=export, markets_fn=list_open_markets,
            kalshi_fn=fetch_json, scoreboard_fn=fetch_scoreboard,
            reconcile_fn=reconcile_espn, evaluate_fn=evaluate_verified_market)
        write_diagnostics(diagnostics)
        Path(args.output).write_text(json.dumps(envelope, sort_keys=True), encoding="utf-8")
    except CaptureFailure as error:
        write_diagnostics(error.diagnostics)
        parser.exit(2, "Beta provider capture failed; no delivery input produced.\n")
    except (ValueError, OSError, KeyError, TypeError):
        parser.exit(2, "Beta capture rejected; inspect sanitized source diagnostics.\n")


if __name__ == "__main__":
    main()
