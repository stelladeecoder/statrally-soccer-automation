"""Grade reserved paper signal Issues; write outcome comments once, never guess."""
import json,os
from datetime import datetime,timezone
from m13_beta_dispatch import github
from m13_beta_grading import grade,aggregate,fetch_scoreboard,LEAGUES

def run(repo,token):
    all_issues=[]
    page=1
    while page<=20:
        items=github("GET",f"/repos/{repo}/issues?state=all&per_page=100&page={page}",token)
        if not isinstance(items,list):raise ValueError("Issue pagination unavailable")
        all_issues.extend(items)
        if len(items)<100:break
        page+=1
    else:raise ValueError("Too many Issues; refusing incomplete evaluation")
    graded=[]
    for issue in all_issues:
        body=issue.get("body") or ""
        if "statrally-beta-data:" not in body or "pull_request" in issue:continue
        if "Discord delivery returned success." not in "\n".join(
           c.get("body","") for c in github("GET",f"/repos/{repo}/issues/{issue['number']}/comments?per_page=100",token)):
            continue
        try:
            signal=json.loads(body.split("statrally-beta-data:",1)[1].split("\n",1)[0])
            if signal.get("league") not in LEAGUES:continue
            kickoff=datetime.fromisoformat(signal["kickoff_utc"].replace("Z","+00:00"))
            if kickoff>=datetime.now(timezone.utc):continue
            result=grade(signal,fetch_scoreboard(signal["league"],kickoff.strftime("%Y%m%d")))
            if result["status"]!="graded":continue
            comments=github("GET",f"/repos/{repo}/issues/{issue['number']}/comments?per_page=100",token)
            if len(comments)>=100:raise ValueError("Incomplete comments")
            marker="statrally-beta-grade:"+signal["market_ticker"]+"|"+signal["side"]+"|"+signal["kickoff_utc"]
            if not any(marker in c.get("body","") for c in comments):
                github("POST",f"/repos/{repo}/issues/{issue['number']}/comments",token,{"body":marker+"\nPaper outcome: **"+result["result"]+"** | Final "+str(result["home_goals"])+"-"+str(result["away_goals"])+" | No trade."})
            graded.append(result)
        except (ValueError,KeyError,TypeError,OSError):
            # Ambiguous or unavailable source must not produce a grade.
            continue
    print(json.dumps({"status":"paper_performance_no_trades","snapshot":aggregate(graded),"note":"Stats only cover independently graded, delivered Issues inspected in this run."},sort_keys=True))

if __name__=="__main__":
    repo=os.environ["GITHUB_REPOSITORY"]
    token=os.environ["GH_TOKEN"]
    run(repo,token)
