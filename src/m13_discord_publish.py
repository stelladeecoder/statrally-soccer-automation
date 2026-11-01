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
    if not isinstance(scan, dict) or scan.get("status") != "research_only" or scan.get("trades_placed") != 0:
        raise ValueError("Verified research scan required")
    decisions=scan.get("decisions")
    if not isinstance(decisions,list):
        raise ValueError("Missing decisions")
    lines=[]
    for d in decisions:
        if d.get("fixture_verified") is not True:
            continue
        home,away,kickoff=d.get("home_team"),d.get("away_team"),d.get("kickoff_utc")
        if not all(isinstance(v,str) and v.strip() for v in (home,away,kickoff)):
            continue
        if d.get("status") not in ("NO_BET","RESEARCH_ONLY"):
            continue
        lines.append(f"• {home} vs {away} | {kickoff} UTC | {d['status']} (research only)")
    if not lines:
        return None
    return {"content":"**StatRally | Verified BTTS watchlist**\n" + "\n".join(lines[:8]) + "\nNo betting selections are authorized."}

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
    parser.add_argument("--mode",choices=("summary","watchlist"),default="summary")
    parser.add_argument("--suppress-no-bet",action="store_true",help="Avoid repeated routine No Bet posts")
    args=parser.parse_args()
    report=json.loads(Path(args.input).read_text(encoding="utf-8"))
    payload=render_watchlist(report) if args.mode=="watchlist" else render(report)
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
