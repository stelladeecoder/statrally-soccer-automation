"""Strict aggregate-only projection of private monitoring output."""
import math
from m13_discord_embeds import COMPETITIONS

SCORES = {"n","accuracy","balanced_accuracy","brier","log_loss","ece","yes_precision","no_precision","yes_recall","no_recall",
          "yes_f1","no_f1","accuracy_wilson_95","confusion","total_predictions","graded_predictions","pending_predictions",
          "ungradable_predictions","correct_predictions","incorrect_predictions","yes_accuracy","no_accuracy",
          "baseline_same_fixtures","model_baseline_matched","evaluated_prematch_fixtures","prediction_coverage"}


def public_metrics(report):
    if (not isinstance(report,dict) or set(report)!={"schema_version","status","revision_policy","overall","by_league","by_model_version",
            "by_confidence","by_month","coverage","no_model_promoted","trades_placed","note"}
            or report["schema_version"]!=1 or report["trades_placed"]!=0 or report["no_model_promoted"] is not True
            or report["status"]!="forward_recorded_experimental_no_trades"):
        raise ValueError("Sanitized forward monitoring schema required")
    def numeric(value):
        if value is None:return None
        if type(value) not in (float,int) or not math.isfinite(value):raise ValueError("Only finite aggregate metrics allowed")
        return value
    def score(value):
        if not isinstance(value,dict) or set(value)-SCORES:raise ValueError("Private/unreviewed metric fields")
        out={}
        for key,val in value.items():
            if key in {"baseline_same_fixtures","model_baseline_matched"}:out[key]=score(val)
            elif key=="confusion":
                if not isinstance(val,dict) or set(val)!={"tn","fp","fn","tp"}:raise ValueError("Invalid confusion matrix")
                out[key]={k:numeric(v) for k,v in val.items()}
            elif key=="accuracy_wilson_95":
                if val is not None and (not isinstance(val,list) or len(val)!=2):raise ValueError("Invalid confidence interval")
                out[key]=None if val is None else [numeric(v) for v in val]
            else:out[key]=numeric(val)
        return out
    result=dict(report,overall=score(report["overall"]))
    if set(report["by_league"])-set(COMPETITIONS):raise ValueError("Unknown competition")
    import re
    for key, pattern in (("by_league",r"[a-z0-9_]+"),("by_model_version",r"[A-Za-z0-9_.-]{1,100}"),("by_month",r"\d{4}-\d{2}")):
        if not isinstance(report[key],dict) or any(not re.fullmatch(pattern,k) for k in report[key]):raise ValueError("Unreviewed aggregate group")
        result[key]={k:score(v) for k,v in report[key].items()}
    result["by_confidence"]={}
    allowed={"0.50-0.55","0.55-0.60","0.60-0.65","0.65-0.70","0.70-0.75","0.75-1.01"}
    if set(report["by_confidence"])!=allowed:raise ValueError("Declared confidence ranges required")
    for key,value in report["by_confidence"].items():
        if set(value)!={"all","YES","NO"}:raise ValueError("Both prediction sides required")
        result["by_confidence"][key]={k:score(v) for k,v in value.items()}
    cov=report["coverage"]
    if not isinstance(cov,dict) or set(cov)!={"predicted_fixtures","evaluated_prematch_fixtures","fraction"}:raise ValueError("Invalid coverage")
    result["coverage"]={k:numeric(v) for k,v in cov.items()}
    # Never echo free text supplied by the private process.
    result["revision_policy"]="First issued forecast per fixture; first per fixture/model version in model groups."
    result["note"]="Experimental uncalibrated estimates. Small samples do not establish reliable confidence or a betting edge."
    return result
