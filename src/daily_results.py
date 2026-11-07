"""Daily read-only Discord results from canonical verified grades."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from urllib.request import Request, build_opener
from urllib.parse import urlsplit

from m13_discord_embeds import CENTRAL, validate_payload
from m13_discord_publish import NoRedirect, publish
from m13_beta_signals import parse_time
from paper_roi import gross_paper_performance, paper_line
from prediction_quality import is_starred_probability

DAILY_REPORT = "statrally-daily-report-v1:"
BLUE = 0x3498DB


def rows_for_day(ledger, day):
    first = {}
    for row in sorted(ledger.export()["records"], key=lambda x: (parse_time(x["issued_at"]), x["comment_id"])):
        p = row["prediction"]
        if parse_time(p["kickoff_utc"]).astimezone(CENTRAL).date() != day or row["market"]["status"] != "verified_available":
            continue
        first.setdefault(p["fixture_id"], row)
    return list(first.values())


def performance(rows):
    result = {}
    for side in ("YES", "NO", "ALL"):
        group = [r for r in rows if side == "ALL" or r["prediction"]["side"] == side]
        grades = [r for r in group if r["grade"]["status"] == "graded"]
        for row in grades:
            grade = row["grade"]
            if grade.get("result") not in ("WIN", "LOSS") or grade.get("correct") is not (grade["result"] == "WIN"):
                raise RuntimeError("Inconsistent canonical result")
        won = sum(r["grade"]["result"] == "WIN" for r in grades)
        result[side] = {"correct": won, "incorrect": len(grades) - won,
                        "graded": len(grades), "pending": len(group) - len(grades),
                        "accuracy": (100 * won / len(grades)) if grades else None}
    return result


def report(ledger, day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    rows = rows_for_day(ledger, day)
    if not rows:
        return None
    # Starred group is derived from the first issued forecast, not a legacy
    # Top 3 delivery reservation or an unverified current market price.
    top = [r for r in rows if is_starred_probability(r["prediction"])]
    return {"date": day.isoformat(), "overall": performance(rows),
            "top": performance(top)["ALL"], "total": len(rows), "top_total": len(top),
            "paper_overall": gross_paper_performance(rows), "paper_top": gross_paper_performance(top)}


def percent(part):
    return "N/A" if part["accuracy"] is None else f'{part["accuracy"]:.1f}%'


def result_embed(data):
    all_ = data["overall"]["ALL"]
    fields = []
    for side in ("ALL", "YES", "NO"):
        p = data["overall"][side]
        label = {"ALL": "Overall", "YES": "BTTS YES", "NO": "BTTS NO"}[side]
        fields.append({"name": label, "value": f'{percent(p)} | {p["correct"]}W–{p["incorrect"]}L | {p["graded"]} graded', "inline": True})
    top = data["top"]
    fields.append({"name": "⭐ 70%+ Model Picks accuracy (included in Overall)",
                   "value": (f'{percent(top)} | {top["correct"]}W–{top["incorrect"]}L | {top["graded"]}/{data["top_total"]} graded'
                             if data["top_total"] else "No 70%+ model predictions"),
                   "inline": False})
    fields.append({"name": "$10 flat-stake · Overall gross paper ROI",
                   "value": paper_line(data["paper_overall"]), "inline": False})
    fields.append({"name": "$10 flat-stake · 70%+ Model Picks gross paper ROI (subset)",
                   "value": paper_line(data["paper_top"]), "inline": False})
    fields.append({"name": "Outstanding",
                   "value": f'{all_["pending"]} ungraded overall; {top["pending"]} starred ungraded',
                   "inline": False})
    # Discord embeds do not support HTML/CSS progress bars.
    if all_["graded"]:
        bar = "🟩" * min(10, round(10 * all_["correct"] / all_["graded"])) + "🟥" * (10 - min(10, round(10 * all_["correct"] / all_["graded"])))
    else:
        bar = "No verified finals yet"
    payload = {"content": "",
               "embeds": [{"title": "StatRally | Daily Results • " + data["date"],
                           "description": bar + "\nOverall includes ⭐ 70%+ Model Picks exactly once. Stars describe model probability, not validated reliability or additional picks.\nVerified paper predictions only. Gross hypothetical P&L is not realized or fee-adjusted profit.",
                           "color": BLUE, "fields": fields,
                           "footer": {"text": "First issued forecast per fixture · America/Chicago · Experimental model"}}],
               "allowed_mentions": {"parse": []}}
    return validate_payload(payload)


def snapshot(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def edit_message(payload, webhook, receipt, *, opener=None):
    validate_payload(payload)
    parts = urlsplit(webhook)
    if (parts.scheme != "https" or parts.hostname not in ("discord.com", "discordapp.com")
            or not parts.path.startswith("/api/webhooks/") or parts.username or parts.password):
        raise ValueError("Validated Discord webhook required")
    message_id = receipt.get("message_id")
    if not isinstance(message_id, str) or not message_id.isascii() or not message_id.isdigit():
        raise ValueError("Confirmed Discord message id required")
    path = parts.path.rstrip("/") + "/messages/" + message_id
    url = parts._replace(path=path, query="", fragment="").geturl()
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json",
                     "User-Agent": "StatRally/0.1"}, method="PATCH")
    with (opener or build_opener(NoRedirect()).open)(request, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("Discord daily report edit was not confirmed")


def publish_report(ledger, day, webhook, *, sender=publish, editor=edit_message):
    data = report(ledger, day)
    if data is None or data["overall"]["ALL"]["graded"] == 0:
        return "no_verified_results"
    if not webhook:
        raise RuntimeError("STATRALLY_DAILY_RESULTS_DISCORD_WEBHOOK is not configured")
    number = ledger.daily(data["date"])
    events = ledger.events(number, DAILY_REPORT)
    current = snapshot(data)
    reserved = [e for e in events if e.get("state") == "reserved"]
    accepted = [e for e in events if e.get("state") == "accepted"]
    if len(reserved) > 1 or len(accepted) > 1:
        raise RuntimeError("Ambiguous daily report history")
    if not reserved:
        # A possible lost receipt must not cause a second public message.
        ledger.append(number, DAILY_REPORT, {"state": "reserved", "day": data["date"]})
        receipt = sender(result_embed(data), webhook, wait=True)
        if not isinstance(receipt, dict) or not all(k in receipt for k in ("message_id", "channel_id")):
            raise RuntimeError("No confirmed Discord delivery receipt")
        ledger.append(number, DAILY_REPORT, {"state": "accepted", "day": data["date"],
                                               "receipt": receipt, "snapshot": current})
        return "posted"
    if not accepted:
        raise RuntimeError("Unresolved daily report reservation: manual review required")
    last = [e for e in events if e.get("state") in ("accepted", "updated")]
    if last[-1].get("snapshot") == current:
        return "unchanged"
    # A failed or ambiguous edit cannot be retried blindly.
    if any(e.get("state") == "update_reserved" for e in events) and (not last or events[-1].get("state") != "updated"):
        raise RuntimeError("Unresolved daily edit: manual review required")
    ledger.append(number, DAILY_REPORT, {"state": "update_reserved", "day": data["date"], "snapshot": current})
    editor(result_embed(data), webhook, accepted[0]["receipt"])
    ledger.append(number, DAILY_REPORT, {"state": "updated", "day": data["date"], "snapshot": current})
    return "updated"


def main():
    import os
    from prediction_ledger import Ledger
    ledger = Ledger(os.environ.get("GITHUB_REPOSITORY", ""),
                    os.environ.get("GH_TOKEN", "")).load()
    today = datetime.now(timezone.utc).astimezone(CENTRAL).date()
    results = {}
    # Also reconcile corrected scores and late finals for the preceding week.
    for days_ago in range(7, 0, -1):
        day = today - timedelta(days=days_ago)
        results[day.isoformat()] = publish_report(
            ledger, day, os.environ.get("STATRALLY_DAILY_RESULTS_DISCORD_WEBHOOK", ""))
    print("STATRALLY_DAILY_RESULTS=" + json.dumps(results, sort_keys=True))


if __name__ == "__main__":
    main()
