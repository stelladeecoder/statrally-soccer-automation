"""Explicit live-data Discord tests. No simulated picks or graded reservations."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from m13_beta_signals import render_beta, parse_time
from m13_discord_publish import publish

LEAGUES = ("epl", "bundesliga", "laliga", "serie_a", "ligue_1", "eredivisie",
           "liga_portugal", "brasileirao", "mls", "liga_mx", "primera_lpf",
           "champions_league", "europa_league")
ZONE = ZoneInfo("America/Chicago")


def pages(lines):
    result, current = [], ""
    for line in lines:
        if len(line) > 1800:
            raise ValueError("Test report line too long")
        if len(current) + len(line) + 1 > 1900:
            result.append({"content": current, "allowed_mentions": {"parse": []}})
            current = "**StatRally | LIVE DATA TEST (continued)**"
        current += ("\n" if current else "") + line
    if current:
        result.append({"content": current, "allowed_mentions": {"parse": []}})
    return result


def watchlist_payloads(scan):
    if scan.get("status") not in ("fixture_schedule", "partial_fixture_schedule") or not isinstance(scan.get("fixtures"), list):
        raise ValueError("Observed fixture schedule required")
    day = scan["date_central"]
    lines = ["**StatRally | MATCH LIST — LIVE DATA TEST**", day + " | America/Chicago",
             "Real fixtures from 13 configured competition feeds. No betting selections."]
    seen = set()
    for fixture in scan["fixtures"]:
        kickoff = parse_time(fixture["kickoff_utc"]).astimezone(ZONE)
        if str(kickoff.date()) != day:
            raise ValueError("Fixture outside requested Central date")
        home, away, league = (fixture[k] for k in ("home_team", "away_team", "league"))
        if any(not isinstance(x, str) or not x.strip() for x in (home, away, league)):
            raise ValueError("Missing fixture identity")
        key = (home, away, league, kickoff)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"• {league} | {kickoff:%I:%M %p} CT | {home} vs {away}")
    failed = scan.get("failed_leagues", [])
    lines.append(f"Observed fixtures: {len(seen)}. Failed league feeds: {len(failed)}.")
    if failed:
        lines.append("Incomplete feeds: " + ", ".join(failed))
    elif not seen:
        lines.append("No matches returned for this date; all configured feed requests succeeded.")
    return pages(lines)


def picks_payloads(envelope, diagnostics):
    payload = render_beta(envelope, allow_empty=True)
    discovery = diagnostics.get("discovery")
    if not isinstance(discovery, dict) or set(discovery.get("leagues", {})) != set(LEAGUES):
        raise ValueError("All 13 league scan diagnostics required")
    lines = ["**StatRally | POLYMARKET US PICKS — LIVE DATA TEST**",
             datetime.now(ZONE).strftime("%Y-%m-%d %I:%M %p CT"),
             "Experimental paper estimates only. No trades. Test posts are not entered into the graded pick ledger.",
             "Scan window: " + discovery["window_start_utc"][:10] + " through " + discovery["window_end_utc"][:10] + " UTC."]
    if not discovery.get("scan_complete"):
        lines.append("COVERAGE INCOMPLETE: provider sampling limits or source failures remain; zero results do not prove no markets exist.")
    lines.append("Per league: upcoming ESPN fixtures / matched BTTS contracts / valid model-and-quote signals")
    for league in LEAGUES:
        stats = discovery["leagues"][league]
        evaluated = diagnostics.get("leagues", {}).get(league, {})
        valid = evaluated.get("validated", 0)
        failures = stats.get("feed_failures", 0)
        suffix = " | feed failures " + str(failures) if failures else ""
        excluded = evaluated.get("excluded", {})
        if excluded:
            # Fixed categories only: no provider exception text in Discord.
            reasons = []
            if any("histor" in reason.lower() for reason in excluded):
                reasons.append("model history unavailable")
            if any("quote" in reason.lower() or "liquidity" in reason.lower() or "depth" in reason.lower() for reason in excluded):
                reasons.append("selected-side quote unavailable")
            suffix += " | " + (", ".join(reasons) if reasons else "validation exclusions")
        lines.append(f"• {league}: {stats['fixtures']} / {stats['mapped']} / {valid}{suffix}")
    if payload:
        lines.append("Real observed candidate output (maximum 3; upcoming fixtures can be on later days):")
        lines.extend(payload["content"].splitlines())
    else:
        lines.append("No eligible paper picks passed the fixture, contract, quote and model checks in this scan. No pick was invented.")
    return pages(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("watchlist", "picks"), required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--diagnostics")
    args = parser.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.mode == "watchlist":
        payloads = watchlist_payloads(data)
        variable = "STATRALLY_DISCORD_WEBHOOK"
    else:
        diagnostics = json.loads(Path(args.diagnostics).read_text(encoding="utf-8"))
        payloads = picks_payloads(data, diagnostics)
        variable = "STATRALLY_PICKS_DISCORD_WEBHOOK"
    webhook = os.environ.get(variable)
    if not webhook:
        raise ValueError("Missing configured Discord webhook")
    for index, payload in enumerate(payloads, 1):
        publish(payload, webhook)
        print(f"DISCORD_{args.mode.upper()}_TEST_PAGE_DELIVERED={index}/{len(payloads)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not expose webhook URLs or credentials through a traceback.
        raise SystemExit("Discord live-data test failed: " + type(exc).__name__) from None
