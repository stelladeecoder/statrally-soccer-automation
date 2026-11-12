"""One-per-day idempotent Discord delivery for international research forecasts.

Metadata-only GitHub Issue reservations ensure ambiguous POSTs are never retried.
Do not export private forecasts or provider identifiers to public GitHub Issues.
"""
from datetime import datetime
from hashlib import sha256
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlsplit,urlunsplit,urlencode,parse_qsl
from zoneinfo import ZoneInfo

CENTRAL=ZoneInfo("America/Chicago")
PREFIX="statrally-intl-research-v1:"
BOT="github-actions[bot]"

def gh(method,repo,token,path,data=None):
    req=Request("https://api.github.com/repos/"+repo+path,
        data=(json.dumps(data).encode() if data is not None else None),
        method=method,headers={"Authorization":"Bearer "+token,
          "Accept":"application/vnd.github+json","Content-Type":"application/json",
          "X-GitHub-Api-Version":"2022-11-28","User-Agent":"StatRally-Research/1"})
    with urlopen(req,timeout=20) as response:
        raw=response.read()
        return json.loads(raw) if raw else None

def ledger(repo,token,day):
    title="StatRally international research | "+day
    for page in range(1,6):
        rows=gh("GET",repo,token,f"/issues?state=all&per_page=100&page={page}")
        matches=[row for row in rows if row.get("title")==title]
        if matches:
            if len(matches)!=1 or matches[0].get("user",{}).get("login")!=BOT:
                raise RuntimeError("Ambiguous international delivery reservation")
            return matches[0]["number"]
        if len(rows)<100:
            break
    else:
        raise RuntimeError("Issue ledger search bound exceeded")
    created=gh("POST",repo,token,"/issues",{"title":title,
        "body":PREFIX+json.dumps({"day":day,"kind":"experimental_research_only"})})
    if not created or not created.get("number"):
        raise RuntimeError("Daily delivery ledger reservation failed")
    return created["number"]

def comments(repo,token,number):
    out=[]
    for page in range(1,11):
        rows=gh("GET",repo,token,f"/issues/{number}/comments?per_page=100&page={page}")
        if not isinstance(rows,list):
            raise RuntimeError("Unusable delivery history")
        out.extend(rows)
        if len(rows)<100:
            return out
    raise RuntimeError("Delivery comment history exceeds safety bound")

def deliver(payloads,repo,token,webhook,*,now=None):
    now=now or datetime.now(CENTRAL)
    if now.tzinfo is None:
        raise ValueError("Aware clock required")
    if not isinstance(payloads,list):
        raise ValueError("Payload pages required")
    if not payloads:
        return {"status":"no_eligible_research_forecasts","confirmed":0,"reserved":0}
    if len(payloads)>10:
        raise ValueError("Too many page messages")
    parts=urlsplit(webhook)
    if (parts.scheme!="https" or parts.netloc!="discord.com" or
            not parts.path.startswith("/api/webhooks/")):
        raise ValueError("Discord webhook not configured for an expected destination")
    params=[(k,v) for k,v in parse_qsl(parts.query) if k!="wait"]
    endpoint=urlunsplit((parts.scheme,parts.netloc,parts.path,
                        urlencode(params+[("wait","true")]),""))
    number=ledger(repo,token,now.astimezone(CENTRAL).date().isoformat())
    seen=[r.get("body","") for r in comments(repo,token,number)
          if r.get("user",{}).get("login")==BOT]
    confirmed=0
    reserved=0
    for index,payload in enumerate(payloads,1):
        if (not isinstance(payload,dict) or
            set(payload)!={"content","allowed_mentions"} or
            payload.get("allowed_mentions")!={"parse":[]} or
            not isinstance(payload.get("content"),str) or
            not 1<=len(payload["content"])<=1900 or
            "Experimental, uncalibrated probabilities" not in payload["content"]):
            raise ValueError("Unsafe research-only Discord payload")
        # A posting slot is immutable across model reruns on this local day.
        slot=f"{PREFIX}page:{index}"
        if any(v.startswith(slot+":reserved") or v.startswith(slot+":confirmed") for v in seen):
            print("STATRALLY_INTL_NO_DUPLICATE_PAGE="+str(index))
            continue
        digest=sha256(payload["content"].encode()).hexdigest()[:16]
        reservation=slot+":reserved:"+digest
        row=gh("POST",repo,token,f"/issues/{number}/comments",{"body":reservation})
        if not row or not row.get("id"):
            raise RuntimeError("Could not reserve Discord page before sending")
        reserved+=1
        request=Request(endpoint,method="POST",data=json.dumps(payload).encode(),
                        headers={"Content-Type":"application/json",
                                 "User-Agent":"StatRally-Research/1"})
        with urlopen(request,timeout=15) as response:
            if response.status!=200:
                raise RuntimeError("Discord acknowledgement unavailable; do not retry")
            receipt=json.loads(response.read(65536))
        message_id=receipt.get("id") if isinstance(receipt,dict) else None
        if not isinstance(message_id,str) or not message_id.isdigit():
            raise RuntimeError("Discord receipt unavailable; do not retry")
        confirmed+=1
        gh("POST",repo,token,f"/issues/{number}/comments",
           {"body":slot+":confirmed:"+digest+":message_id:"+message_id})
        seen.append(slot+":confirmed:"+digest)
        print("STATRALLY_INTL_DISCORD_CONFIRMED_PAGE="+str(index))
    return {"status":"checked","confirmed":confirmed,"reserved":reserved,"pages":len(payloads)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",required=True,type=Path)
    args=parser.parse_args()
    source=json.loads(args.input.read_text())
    if source.get("trades_placed")!=0:
        raise SystemExit("Trading payload not permitted")
    result=deliver(source["payloads"],os.environ["GITHUB_REPOSITORY"],
                   os.environ["GH_TOKEN"],
                   os.environ["STATRALLY_PICKS_DISCORD_WEBHOOK"])
    print("STATRALLY_INTL_DISCORD_RESULT="+json.dumps(result,sort_keys=True))

if __name__=="__main__":
    main()
