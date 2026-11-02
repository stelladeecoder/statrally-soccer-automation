"""Grade only delivered, verified ESPN full-time beta paper predictions."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from urllib.request import Request, urlopen

LEAGUES={"epl":"eng.1","mls":"usa.1","liga_mx":"mex.1"}

def fetch_scoreboard(league, day):
    code=LEAGUES[league]
    url=f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={day}"
    with urlopen(Request(url,headers={"User-Agent":"StatRally-Beta/0.1"}),timeout=15) as response:
        return json.load(response)

def grade(signal, response):
    """A missing or mismatched final score remains pending, never a loss."""
    if signal.get("league") not in LEAGUES or not str(signal.get("espn_event_id","")).isdigit():
        raise ValueError("Missing supported ESPN event identity")
    events=[x for x in response.get("events",[]) if str(x.get("id"))==str(signal["espn_event_id"])]
    if len(events)!=1: raise ValueError("Missing or ambiguous event ID")
    event=events[0]
    competitions=event.get("competitions",[])
    if len(competitions)!=1: raise ValueError("Ambiguous competition")
    opponents=competitions[0].get("competitors",[])
    home=[x for x in opponents if x.get("homeAway")=="home"]
    away=[x for x in opponents if x.get("homeAway")=="away"]
    if len(home)!=1 or len(away)!=1: raise ValueError("Missing home/away roles")
    if home[0].get("team",{}).get("displayName")!=signal["home_team"] or away[0].get("team",{}).get("displayName")!=signal["away_team"]:
        raise ValueError("Team identity mismatch")
    if datetime.fromisoformat(event["date"].replace("Z","+00:00")) != datetime.fromisoformat(signal["kickoff_utc"].replace("Z","+00:00")):
        raise ValueError("Kickoff changed; require review")
    if event.get("status",{}).get("type",{}).get("completed") is not True:
        return {"status":"pending"}
    for record in (home[0],away[0]):
        if not str(record.get("score","")).isdigit():
            raise ValueError("Invalid final score")
    hg,ag=int(home[0]["score"]),int(away[0]["score"])
    yes=hg>0 and ag>0
    if signal.get("side") not in ("YES","NO"):raise ValueError("Invalid prediction")
    return {"status":"graded","result":"WIN" if (signal["side"]=="YES")==yes else "LOSS",
            "btts_yes":yes,"side":signal["side"],"home_goals":hg,"away_goals":ag,
            "model_probability":signal.get("model_probability"),"market_price":signal.get("market_price")}

def aggregate(graded):
    wins=sum(x["result"]=="WIN" for x in graded if x.get("status")=="graded")
    losses=sum(x["result"]=="LOSS" for x in graded if x.get("status")=="graded")
    total=wins+losses
    scored=[x for x in graded if x.get("status")=="graded" and x.get("btts_yes") in (True,False) and x.get("model_probability") is not None]
    brier=None
    if scored:
        try:
            errors=[]
            for item in scored:
                p=Decimal(str(item["model_probability"]))
                if not p.is_finite() or p<0 or p>1:raise ValueError("Invalid probability")
                p_yes=p if item.get("side","YES")=="YES" else 1-p
                errors.append((p_yes-Decimal(int(item["btts_yes"])))**2)
            brier=str(sum(errors,Decimal(0))/len(errors))
        except (ValueError,TypeError):
            brier=None
    return {"graded":total,"wins":wins,"losses":losses,
            "brier_score":brier,
            "hit_rate":round(wins/total,4) if total else None,
            "pending":sum(x.get("status")=="pending" for x in graded)}
