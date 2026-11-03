"""Explicit fictional design previews. No engine, Issue writes or grading calls."""
import argparse
from datetime import datetime, timezone
import json
import os
from urllib.request import Request, build_opener

from m13_beta_signals import render_beta
from m13_discord_embeds import render_paper_result, validate_payload
from m13_discord_publish import NoRedirect, publish, render_watchlist_pages

LABEL = "DESIGN TEST · FICTIONAL DATA"
ROLES = {"watchlist": "STATRALLY_DISCORD_WEBHOOK", "picks": "STATRALLY_PICKS_DISCORD_WEBHOOK",
         "results": "STATRALLY_RESULTS_DISCORD_WEBHOOK"}


def previews():
    # A fixed fictional formatting clock, never an actual observation/record.
    now = datetime(2026, 11, 4, 18, tzinfo=timezone.utc)
    pairs = (("Northbridge", "Riverside", "YES", "2026-11-04T20:00:00Z", "0.61", "0.55"),
             ("Westhaven", "Eastport", "NO", "2026-11-04T21:15:00Z", "0.58", "0.51"))
    signals = [{"home_team":h,"away_team":a,"side":side,"kickoff_utc":kickoff,"league":"epl",
                "espn_event_id":str(900000000+i),"market_ticker":"astatc-FICTIONAL-DESIGN-"+str(i),
                "model_probability":p,"market_price":q,"observed_at_utc":now.isoformat(),
                "fixture_verified":True,"quote_verified":True}
               for i,(h,a,side,kickoff,p,q) in enumerate(pairs)]
    picks = render_beta({"schema_version":1,"status":"experimental_paper","trades_placed":0,"signals":signals},now=now)
    watchlist = render_watchlist_pages({"status":"fixture_schedule","date_central":"2026-11-04",
        "fixtures":[{"home_team":s["home_team"],"away_team":s["away_team"],"kickoff_utc":s["kickoff_utc"],"league":"Sample League A"} for s in signals]
          +[{"home_team":"Oakfield","away_team":"Lakeside","kickoff_utc":"2026-11-04T22:00:00Z","league":"Sample League B"}]})[0]
    results = {"embeds":[],"allowed_mentions":{"parse":[]}}
    for signal,outcome,hg,ag in ((signals[0],"WIN",2,1),(signals[1],"LOSS",1,1),
                                (signals[0],"LOSS",0,2),(signals[1],"WIN",0,0)):
        results["embeds"].extend(render_paper_result(signal,{"status":"graded","result":outcome,"home_goals":hg,"away_goals":ag})["embeds"])
    output = {"watchlist":watchlist,"picks":picks,"results":results}
    for payload in output.values():
        payload["content"] = "**"+LABEL+"**\nPreview only. Not an official pick, result, or performance record."
        for embed in payload["embeds"]:
            embed["description"] = embed["description"].replace("Premier League", "Sample League A")
            embed["footer"]["text"] = LABEL + " · " + embed["footer"]["text"]
        validate_payload(payload)
    return output


def deliver(payloads, bindings, *, sender=publish, opener=None):
    """Exactly one attempted message per role; no POST retries or official log."""
    if set(payloads) != set(ROLES) or set(bindings) != set(ROLES):
        raise ValueError("Three explicitly configured design destinations required")
    routes = {}
    open_request = opener or build_opener(NoRedirect()).open
    for role in ROLES:
        payload = payloads[role]
        validate_payload(payload)
        if not payload.get("content", "").startswith("**"+LABEL+"**") or any(LABEL not in e["footer"]["text"] for e in payload["embeds"]):
            raise ValueError("Fictional design labels required")
        webhook = bindings[role]
        if not webhook.startswith("https://discord.com/api/webhooks/"):
            raise ValueError("Configured Discord webhook required")
        with open_request(Request(webhook,headers={"User-Agent":"StatRally-Design-Test/1.0"},method="GET"),timeout=15) as response:
            if response.status != 200:
                raise ValueError("Webhook route unavailable")
            raw=response.read(65537)
        if len(raw)>65536:
            raise ValueError("Invalid webhook metadata")
        route=json.loads(raw)
        if any(not isinstance(route.get(k),str) or not route[k].isascii() or not route[k].isdigit() for k in ("guild_id","channel_id")):
            raise ValueError("Invalid webhook route")
        routes[role] = {k:route[k] for k in ("guild_id","channel_id")}
    if len({r["channel_id"] for r in routes.values()})!=3 or len({r["guild_id"] for r in routes.values()})!=1:
        raise ValueError("Design destinations must be three distinct channels in one server")
    receipts = []
    for role in ROLES:
        receipt = sender(payloads[role], bindings[role], wait=True)
        if receipt["channel_id"] != routes[role]["channel_id"]:
            raise RuntimeError("Delivery route differs from preflight; do not retry")
        link = "https://discord.com/channels/"+routes[role]["guild_id"]+"/"+receipt["channel_id"]+"/"+receipt["message_id"]
        saved = {"role":role,"message_id":receipt["message_id"],"url":link,"fictional":True}
        receipts.append(saved)
        print(json.dumps(saved,sort_keys=True))
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as stream:
                stream.write(f"- {LABEL}: [{role}]({link}), message `{receipt['message_id']}`\n")
    return receipts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send",action="store_true")
    args=parser.parse_args()
    try:
        payloads=previews()
        if not args.send:
            print(json.dumps(payloads,ensure_ascii=False,indent=2))
            return
        if os.environ.get("GITHUB_RUN_ATTEMPT","1")!="1":
            raise RuntimeError("Design messages must not be automatically rerun")
        deliver(payloads,{role:os.environ.get(name,"") for role,name in ROLES.items()})
    except Exception as error:
        raise SystemExit("Design preview failed ("+type(error).__name__+"); inspect accepted receipts, no automatic resend.") from None


if __name__=="__main__":
    main()
