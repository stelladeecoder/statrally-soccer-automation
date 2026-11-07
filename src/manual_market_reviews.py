"""User-supplied review decisions, distinct from automatic market identity checks.

Only the five specific Nov 7 fixtures are authorized here. No claim that an
API verified a contract, and no fake market slug or price is generated.
"""
from prediction_ledger import MANUAL_MARKET

DECISIONS = {
    "a14f541b56b396c5e1698222fcb56293da4e1c051a854c2b0d38431babed3840": ("FC Dallas","Colorado Rapids","available"),
    "eaf4e013c8285524b885fc019f39ca0530dd5f09942b0a0e08ad28bc927dfd26": ("D.C. United","New York City FC","available"),
    "cc62645b469c06baaabd035b93b72b8df8009f1c0b0da4696027d1b115c111c4": ("Argentinos Juniors","Huracán","unavailable"),
    "28a8cee2c5310c614a88cc0c6534cfba5f2a30aa0e50de919bf68ceda34a983a": ("Boca Juniors","Defensa y Justicia","unavailable"),
    "8607af2c4df87928f86693e4cd894da2f0500fb3589fe144e28be53566e74f02": ("Rosario Central","Estudiantes de Río Cuarto","unavailable"),
}


def apply_reviews(ledger):
    records = {r["prediction"]["prediction_id"]:r for r in ledger.export()["records"]}
    if not set(DECISIONS).issubset(records):
        raise RuntimeError("Required Nov 7 forecasts missing from canonical ledger; no partial writes")
    for identity,(home,away,decision) in DECISIONS.items():
        p=records[identity]["prediction"]
        if (p["home_team"],p["away_team"],p["league"]) != (home,away,"mls" if decision == "available" else "primera_lpf"):
            raise RuntimeError("Manual review would apply to wrong match; no writes")
    applied=0
    for identity,(_,_,decision) in DECISIONS.items():
        row=records[identity]
        existing=ledger.events(row["issue_number"],MANUAL_MARKET)
        own=[e for e in existing if e.get("prediction_id")==identity]
        desired={"prediction_id":identity,"decision":decision,"source":"user_manual_check"}
        if own:
            if len(own)!=1 or own[0]!=desired:
                raise RuntimeError("Conflicting manual review history; stop for human reconciliation")
            continue
        ledger.append(row["issue_number"],MANUAL_MARKET,desired)
        applied+=1
    after={r["prediction"]["prediction_id"]:r for r in ledger.export()["records"]}
    for identity,(_,_,decision) in DECISIONS.items():
        if after[identity]["market"]["status"]!="manual_"+decision:
            raise RuntimeError("Manual market projection did not match persisted decision")
    return {"reviewed":len(DECISIONS),"new_events":applied,
            "manual_available":sum(v[2]=="available" for v in DECISIONS.values()),
            "manual_unavailable":sum(v[2]=="unavailable" for v in DECISIONS.values()),
            "trades_placed":0}
