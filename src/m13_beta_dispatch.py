"""M13 paper signal dispatcher with durable GitHub Issue reservations.

Single scheduled writer via Actions concurrency. Public issues contain paper
predictions only, no private account data or credentials.
"""
import json
import os
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote
from m13_beta_signals import render_beta, signal_identity, signal_proof, parse_time
from m13_discord_publish import publish
from m13_discord_embeds import payload_text, CENTRAL

API="https://api.github.com"
DELIVERY_MESSAGE="Discord delivery returned success. Paper signal posted; outcome pending."

def github(method,path,token,data=None):
    request=Request(API+path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization":"Bearer "+token,"Accept":"application/vnd.github+json",
                 "X-GitHub-Api-Version":"2022-11-28","Content-Type":"application/json"},
        method=method)
    with urlopen(request,timeout=20) as response:
        raw=response.read()
    return json.loads(raw) if raw else None

DAILY_PAPER_LIMIT = 3

def reserved_today(issues, *, now):
    """Count durable bot paper reservations for the current Central calendar day.

    Both delivered and ambiguous/failed sends occupy a slot: never release a
    slot merely because Discord delivery or its receipt was uncertain.
    """
    day = now.astimezone(CENTRAL).date()
    count = 0
    for issue in issues:
        if "pull_request" in issue or issue.get("user", {}).get("login") != "github-actions[bot]":
            continue
        body = issue.get("body") or ""
        for line in body.splitlines():
            if not line.startswith("statrally-beta-data:"):
                continue
            try:
                record = json.loads(line.removeprefix("statrally-beta-data:"))
                kickoff = parse_time(record["kickoff_utc"])
            except (ValueError, TypeError, KeyError, AttributeError):
                raise RuntimeError("Unusable saved paper reservation; manual review required") from None
            if kickoff.astimezone(CENTRAL).date() == day:
                count += 1
            break
    return count

def process(envelope,repo,token,webhook,*,now=None):
    now = now or datetime.now(timezone.utc)
    render_beta(envelope, allow_empty=True, require_current_day=True,now=now)
    signals=envelope["signals"]
    if not signals:
        print("BETA_NO_ELIGIBLE_SIGNALS")
        return 0
    # Validate every selected candidate before creating any public state.
    render_beta(envelope, require_current_day=True,now=now)
    existing=[]
    for page in range(1,21):
        batch=github("GET",f"/repos/{repo}/issues?state=all&per_page=100&page={page}",token)
        if not isinstance(batch,list):
            raise RuntimeError("GitHub issue history unavailable; refusing delivery")
        existing.extend(batch)
        if len(batch)<100:
            break
    else:
        raise RuntimeError("Issue history exceeds checked pages; refusing possible duplicate")
    occupied = reserved_today(existing, now=now)
    done=0
    for signal in signals:
        identity=signal_identity(signal)
        proof=signal_proof(signal)
        marker="statrally-beta-id:"+identity
        def matches(issue):
            body=issue.get("body") or ""
            for line in body.splitlines():
                # A provider change is not a new prediction for the same
                # independently verified fixture, side and kickoff.
                if line.startswith("statrally-beta-data:"):
                    try:
                        prior=json.loads(line.removeprefix("statrally-beta-data:"))
                        if (isinstance(prior,dict)
                            and prior.get("espn_event_id")==signal.get("espn_event_id")
                            and prior.get("league")==signal.get("league")
                            and parse_time(prior.get("kickoff_utc"))==parse_time(signal.get("kickoff_utc"))):
                            return True
                    except (ValueError,TypeError,KeyError):
                        pass
                if line.startswith("statrally-beta-id:"):
                    try:
                        ticker,side,kickoff=line.removeprefix("statrally-beta-id:").split("|",2)
                        if ticker==signal["market_ticker"] and parse_time(kickoff)==parse_time(signal["kickoff_utc"]):
                            return True
                    except ValueError:
                        # An ambiguous matching ticker/side is a conservative
                        # duplicate block, never permission to send again.
                        if line.startswith("statrally-beta-id:"+signal["market_ticker"]+"|"+signal["side"]+"|"):
                            return True
            return False
        if any(matches(issue) for issue in existing):
            print("BETA_ALREADY_RECORDED")
            continue
        if occupied >= DAILY_PAPER_LIMIT:
            print("BETA_DAILY_LIMIT_REACHED")
            break
        item=dict(envelope,signals=[signal])
        payload=render_beta(item, require_current_day=True,now=now)
        body=("**StatRally beta PAPER signal** (experimental; no validated edge)\n"
              +marker+"\n"+"statrally-beta-data:"+json.dumps(signal,sort_keys=True,separators=(",",":"))+"\n\n" + payload_text(payload)
              +"\n\nState: reserved before Discord delivery. Outcome: pending; no trade.")
        issue=github("POST",f"/repos/{repo}/issues",token,
                     {"title":"BETA PAPER | "+signal["market_ticker"]+" | "+signal["side"],"body":body})
        if not isinstance(issue,dict) or type(issue.get("number")) is not int or issue["number"]<=0:
            raise RuntimeError("Durable reservation confirmation missing; refusing delivery")
        existing.append({"body":body, "user": {"login": "github-actions[bot]"}})
        occupied += 1
        # Issue reservation is durable: failed/ambiguous Discord POST is NOT retried.
        publish(render_beta(item, require_current_day=True,now=now),webhook)
        receipt=github("POST",f"/repos/{repo}/issues/{issue['number']}/comments",token,
                       {"body":DELIVERY_MESSAGE+"\nstatrally-beta-delivery-proof:"+proof})
        if not isinstance(receipt,dict) or type(receipt.get("id")) is not int or receipt["id"]<=0:
            raise RuntimeError("Discord accepted the post but durable receipt is unconfirmed; no automatic resend")
        done+=1
    print("BETA_DELIVERED_COUNT="+str(done))
    return done

def main():
    path=os.environ.get("BETA_INPUT_FILE")
    repo=os.environ.get("GITHUB_REPOSITORY","")
    token=os.environ.get("GH_TOKEN","")
    webhook=os.environ.get("STATRALLY_PICKS_DISCORD_WEBHOOK","")
    if not all((path,repo,token,webhook)):
        raise SystemExit("Missing beta dispatch configuration")
    try:
        with open(path,encoding="utf-8") as f:
            process(json.load(f),repo,token,webhook)
    except Exception:
        raise SystemExit("Beta dispatch failed; durable reservations retained. No automatic resend.") from None

if __name__=="__main__":main()
