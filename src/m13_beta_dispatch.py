"""M13 paper signal dispatcher with durable GitHub Issue reservations.

Single scheduled writer via Actions concurrency. Public issues contain paper
predictions only, no private account data or credentials.
"""
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import quote
from m13_beta_signals import render_beta
from m13_discord_publish import publish

API="https://api.github.com"

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
    signals=envelope.get("signals",[])
    if not signals:
        print("BETA_NO_ELIGIBLE_SIGNALS")
        return 0
    # Validate every selected candidate before creating any public state.
    render_beta(envelope)
    existing=github("GET",f"/repos/{repo}/issues?state=all&per_page=100",token)
    if not isinstance(existing,list):
        raise RuntimeError("GitHub issue history unavailable; refusing delivery")
    if len(existing)>=100:
        raise RuntimeError("Issue history pagination required; refusing possible duplicate")
    done=0
    for signal in signals:
        identity=signal["market_ticker"]+"|"+signal["side"]+"|"+signal["kickoff_utc"]
        marker="statrally-beta-id:"+identity
        if any(marker in issue.get("body","") for issue in existing):
            print("BETA_ALREADY_RECORDED")
            continue
        item=dict(envelope,signals=[signal])
        payload=render_beta(item)
        body=("**StatRally beta PAPER signal** (experimental; no validated edge)\n"
              +marker+"\n"+"statrally-beta-data:"+json.dumps(signal,sort_keys=True,separators=(",",":"))+"\n\n" + payload["content"]
              +"\n\nState: reserved before Discord delivery. Outcome: pending; no trade.")
        issue=github("POST",f"/repos/{repo}/issues",token,
                     {"title":"BETA PAPER | "+signal["market_ticker"]+" | "+signal["side"],"body":body})
        # Issue reservation is durable: failed/ambiguous Discord POST is NOT retried.
        publish(payload,webhook)
        github("POST",f"/repos/{repo}/issues/{issue['number']}/comments",token,
               {"body":"Discord delivery returned success. Paper signal posted; outcome pending."})
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
