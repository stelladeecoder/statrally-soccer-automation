"""M13 Discord formatter and guarded webhook delivery. Stdlib only."""
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

def render(scan):
    if not isinstance(scan, dict) or scan.get("status") != "research_only":
        raise ValueError("Verified research scan required")
    decisions = scan.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Missing scan decisions")
    if scan.get("trades_placed") != 0:
        raise ValueError("Unexpected trade activity")
    approved = [d for d in decisions if d.get("qualified_bet") is True]
    if approved:
        # M12 currently supplies no public-safe verified calibration/provenance
        # bundle; never publish an unsupported betting recommendation.
        return {"content": "StatRally BTTS research: No published selections. Candidate approval requires independent model and fixture verification."}
    return {"content": "StatRally BTTS scan complete. No qualified selections. Research only; no wagers placed."}

def render_watchlist(scan):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if not isinstance(scan,dict) or scan.get("status") not in ("fixture_schedule","partial_fixture_schedule"):
        raise ValueError("Daily fixture schedule required")
    fixtures=scan.get("fixtures")
    if not isinstance(fixtures,list):
        raise ValueError("Missing fixture list")
    groups={}
    for match in fixtures:
        home,away,kickoff,league=(match.get(k) for k in ("home_team","away_team","kickoff_utc","league"))
        if not all(isinstance(x,str) and x.strip() for x in (home,away,kickoff,league)):
            continue
        when=datetime.fromisoformat(kickoff.replace("Z","+00:00")).astimezone(ZoneInfo("America/Chicago"))
        groups.setdefault(league,[]).append((when,f"• {when.strftime('%-I:%M %p')} CT | {home} vs {away}"))
    if not groups and scan.get("status")=="fixture_schedule":
        return {"content":"**StatRally | Soccer Matches — "+str(scan.get("date_central",""))+"**\\nNo matches scheduled today."}
    if not groups:
        return None
    parts=["**StatRally | Soccer Matches — "+str(scan.get("date_central",""))+"**"]
    for league in sorted(groups):
        parts.append("**"+league+"**")
        parts.extend(line for _,line in sorted(groups[league]))
    failed=scan.get("failed_leagues",[])
    if failed:
        parts.append("Schedule incomplete: unavailable feeds for "+", ".join(failed))
    content="\\n".join(parts)
    if len(content)>2000:
        content=content[:1960].rsplit("\\n",1)[0]+"\\n(Additional fixtures omitted)"
    return {"content":content}

def render_picks(scan):
    """Fail closed: M12 has no exportable approved candidate evidence yet."""
    if not isinstance(scan, dict) or scan.get("status") != "research_only" or scan.get("trades_placed") != 0:
        raise ValueError("Verified research scan required")
    if not isinstance(scan.get("decisions"), list):
        raise ValueError("Missing decisions")
    return None


def publish(payload, webhook, opener=urlopen):
    if not webhook.startswith("https://discord.com/api/webhooks/") and not webhook.startswith("https://discordapp.com/api/webhooks/"):
        raise ValueError("Discord webhook URL required")
    data=json.dumps(payload).encode("utf-8")
    request=Request(webhook,data=data,headers={"Content-Type":"application/json","User-Agent":"StatRally/0.1"},method="POST")
    with opener(request,timeout=15) as response:
        if response.status not in (200,204):
            raise RuntimeError("Discord webhook failed")
    return True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,help="Private scanner JSON output")
    parser.add_argument("--send",action="store_true",help="Explicitly allow Discord delivery")
    parser.add_argument("--mode",choices=("summary","watchlist","picks"),default="summary")
    parser.add_argument("--suppress-no-bet",action="store_true",help="Avoid repeated routine No Bet posts")
    args=parser.parse_args()
    report=json.loads(Path(args.input).read_text(encoding="utf-8"))
    payload=render_watchlist(report) if args.mode=="watchlist" else render_picks(report) if args.mode=="picks" else render(report)
    if payload is None:
        print("DISCORD_SKIP_NO_VERIFIED_FIXTURES")
        return
    if args.suppress_no_bet and not any(d.get("qualified_bet") is True for d in report["decisions"]):
        print("DISCORD_SKIP_NO_QUALIFIED_SELECTIONS")
        return
    if not args.send:
        print(json.dumps({"status":"dry_run","payload":payload},sort_keys=True))
        return
    webhook=os.environ.get("STATRALLY_DISCORD_WEBHOOK","")
    if not webhook:
        parser.error("STATRALLY_DISCORD_WEBHOOK secret missing")
    publish(payload,webhook)
    print("DISCORD_MESSAGE_DELIVERED")

if __name__=="__main__":
    main()
