"""M13 Discord formatter and guarded webhook delivery. Stdlib only."""
import argparse
import json
import os
from m13_beta_signals import render_beta
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
    seen=set()
    for match in fixtures:
        home,away,kickoff,league=(match.get(k) for k in ("home_team","away_team","kickoff_utc","league"))
        if not all(isinstance(x,str) and x.strip() for x in (home,away,kickoff,league)):
            continue
        when=datetime.fromisoformat(kickoff.replace("Z","+00:00")).astimezone(ZoneInfo("America/Chicago"))
        identity=(league.strip().casefold(),home.strip().casefold(),away.strip().casefold(),when.isoformat())
        if identity in seen:
            continue
        seen.add(identity)
        groups.setdefault(league,[]).append((when,f"• {when.strftime('%-I:%M %p')} CT | {home} vs {away}"))
    if not groups and scan.get("status")=="fixture_schedule":
        return {"content":"**StatRally | Soccer Matches — "+str(scan.get("date_central",""))+"**\nNo matches scheduled today."}
    if not groups:
        return None
    parts=["**StatRally | Soccer Matches — "+str(scan.get("date_central",""))+"**"]
    for league in sorted(groups):
        parts.append("**"+league+"**")
        parts.extend(line for _,line in sorted(groups[league]))
    failed=scan.get("failed_leagues",[])
    if failed:
        parts.append("Schedule incomplete: unavailable feeds for "+", ".join(failed))
    content="\n".join(parts)
    if len(content)>2000:
        content=content[:1960].rsplit("\n",1)[0]+"\n(Additional fixtures omitted)"
    return {"content":content}

def render_picks(scan):
    """Fail closed: M12 has no exportable approved candidate evidence yet."""
    if not isinstance(scan, dict) or scan.get("status") != "research_only" or scan.get("trades_placed") != 0:
        raise ValueError("Verified research scan required")
    if not isinstance(scan.get("decisions"), list):
        raise ValueError("Missing decisions")
    # A research-only scanner output is never an approved selection envelope.
    return None


def render_approved_picks(envelope):
    """Format only separately approved, explicitly verified prediction envelopes."""
    if not isinstance(envelope,dict) or envelope.get("schema_version") != 1:
        raise ValueError("Approved-picks schema required")
    if envelope.get("approval") != "verified" or envelope.get("model_calibrated") is not True:
        raise ValueError("Verified calibrated model approval required")
    picks=envelope.get("picks")
    if not isinstance(picks,list) or not 1 <= len(picks) <= 3:
        raise ValueError("Between one and three approved picks required")
    lines=[]
    for pick in picks:
        if not isinstance(pick,dict) or pick.get("fixture_verified") is not True or pick.get("fee_verified") is not True:
            raise ValueError("Fixture and fee verification required")
        if pick.get("qualified_bet") is not True:
            raise ValueError("Unqualified selection rejected")
        fields=("home_team","away_team","side","market_ticker")
        if not all(isinstance(pick.get(k),str) and pick[k].strip() for k in fields):
            raise ValueError("Missing mandatory selection identity")
        if pick["side"] not in ("YES","NO"):
            raise ValueError("Invalid side")
        price,ev=pick.get("entry_price"),pick.get("net_ev_per_contract")
        if type(price) not in (float,int) or type(ev) not in (float,int) or not 0 < price < 1 or ev <= 0:
            raise ValueError("Invalid positive expected value or market entry")
        lines.append(f"• {pick['home_team']} vs {pick['away_team']} | BTTS {pick['side']} | entry ${price:.2f} | net EV ${ev:.3f} per contract")
    return {"content":"**StatRally | Verified Kalshi BTTS Picks**\n" + "\n".join(lines)}


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
    parser.add_argument("--mode",choices=("summary","watchlist","picks","approved-picks","beta"),default="summary")
    parser.add_argument("--suppress-no-bet",action="store_true",help="Avoid repeated routine No Bet posts")
    args=parser.parse_args()
    report=json.loads(Path(args.input).read_text(encoding="utf-8"))
    payload=(render_watchlist(report) if args.mode=="watchlist" else render_picks(report) if args.mode=="picks" else render_approved_picks(report) if args.mode=="approved-picks" else render_beta(report) if args.mode=="beta" else render(report))
    if payload is None:
        print("DISCORD_SKIP_NO_VERIFIED_FIXTURES")
        return
    if args.suppress_no_bet and args.mode=="summary" and not any(d.get("qualified_bet") is True for d in report["decisions"]):
        print("DISCORD_SKIP_NO_QUALIFIED_SELECTIONS")
        return
    if not args.send:
        print(json.dumps({"status":"dry_run","payload":payload},sort_keys=True))
        return
    webhook=os.environ.get("STATRALLY_PICKS_DISCORD_WEBHOOK" if args.mode in ("approved-picks","beta") else "STATRALLY_DISCORD_WEBHOOK","")
    if not webhook:
        parser.error("STATRALLY_DISCORD_WEBHOOK secret missing")
    publish(payload,webhook)
    print("DISCORD_MESSAGE_DELIVERED")

if __name__=="__main__":
    main()
