"""M13 paper signal dispatcher with durable GitHub Issue reservations.

Single scheduled writer via Actions concurrency. Public issues contain paper
predictions only, no private account data or credentials.
"""
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import quote
from m13_beta_signals import render_beta, signal_identity, signal_proof, parse_time
from m13_discord_publish import publish

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

def process(envelope,repo,token,webhook):
    render_beta(envelope, allow_empty=True)
    signals=envelope["signals"]
    if not signals:
        print("BETA_NO_ELIGIBLE_SIGNALS")
        return 0
    # Validate every selected candidate before creating any public state.
    render_beta(envelope)
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
                            and prior.get("side")==signal.get("side")
                            and parse_time(prior.get("kickoff_utc"))==parse_time(signal.get("kickoff_utc"))):
                            return True
                    except (ValueError,TypeError,KeyError):
                        pass
                if line.startswith("statrally-beta-id:"):
                    try:
                        ticker,side,kickoff=line.removeprefix("statrally-beta-id:").split("|",2)
                        if signal_identity({"market_ticker":ticker,"side":side,"kickoff_utc":kickoff})==identity:
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
        item=dict(envelope,signals=[signal])
        payload=render_beta(item)
        body=("**StatRally beta PAPER signal** (experimental; no validated edge)\n"
              +marker+"\n"+"statrally-beta-data:"+json.dumps(signal,sort_keys=True,separators=(",",":"))+"\n\n" + payload["content"]
              +"\n\nState: reserved before Discord delivery. Outcome: pending; no trade.")
        issue=github("POST",f"/repos/{repo}/issues",token,
                     {"title":"BETA PAPER | "+signal["market_ticker"]+" | "+signal["side"],"body":body})
        if not isinstance(issue,dict) or type(issue.get("number")) is not int or issue["number"]<=0:
            raise RuntimeError("Durable reservation confirmation missing; refusing delivery")
        existing.append({"body":body})
        # Issue reservation is durable: failed/ambiguous Discord POST is NOT retried.
        publish(render_beta(item),webhook)
        github("POST",f"/repos/{repo}/issues/{issue['number']}/comments",token,
               {"body":DELIVERY_MESSAGE+"\nstatrally-beta-delivery-proof:"+proof})
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
    with open(path,encoding="utf-8") as f:
        process(json.load(f),repo,token,webhook)

if __name__=="__main__":main()
