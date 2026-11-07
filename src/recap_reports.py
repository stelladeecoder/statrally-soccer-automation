"""StatRally recap formatting from verified, first-issued forward forecasts.

Weekly reports are Sunday-Saturday America/Chicago. Monthly reports use a
Pikkit-style rendered PNG calendar; the calendar uses green/red/gray only.
No fictional data, wagers, historical backtests, or invented model scores.
"""
import calendar
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import json
import math
from uuid import uuid4
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener

from daily_results import rows_for_day, performance, percent
from m13_beta_signals import parse_time
from m13_discord_embeds import CENTRAL, validate_payload
from m13_discord_publish import publish, NoRedirect
from prediction_ledger import Ledger

BLUE = 0x3498DB
ORANGE = 0xF97316
PREFIXES = {
    "weekly": "statrally-weekly-recap-v1:",
    "monthly": "statrally-monthly-recap-v1:",
    "model": "statrally-model-performance-v1:",
}
IMAGE_NAME = "statrally-monthly-calendar.png"


def sunday_start(day):
    return day - timedelta(days=(day.weekday() + 1) % 7)


def weekly_bounds(day):
    start = sunday_start(day)
    return start, start + timedelta(days=6)


def month_bounds(day):
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    return first, last


def period_rows(ledger, start, end):
    # Reuse daily first-issued semantics to avoid inflating multiple revisions.
    out = []
    day = start
    while day <= end:
        out.extend(rows_for_day(ledger, day))
        day += timedelta(days=1)
    return out


def highlighted_fixtures(ledger, start, end):
    ids = set()
    for row in ledger.export()["records"]:
        p = row["prediction"]
        day = parse_time(p["kickoff_utc"]).astimezone(CENTRAL).date()
        if start <= day <= end and any(
            x.get("kind") == "top" and x.get("state") in ("reserved", "accepted")
            for x in row["deliveries"]
        ):
            ids.add(p["fixture_id"])
    return ids


def summary(ledger, start, end):
    rows = period_rows(ledger, start, end)
    top_ids = highlighted_fixtures(ledger, start, end)
    selected = [row for row in rows if row["prediction"]["fixture_id"] in top_ids]
    dates = {}
    day = start
    while day <= end:
        dates[day.isoformat()] = performance([row for row in rows if
            parse_time(row["prediction"]["kickoff_utc"]).astimezone(CENTRAL).date() == day])["ALL"]
        day += timedelta(days=1)
    return {"start": start.isoformat(), "end": end.isoformat(),
            "overall": performance(rows), "top": performance(selected)["ALL"],
            "top_total": len(selected), "days": dates, "records": rows}


def _field(name, value, inline=True):
    return {"name": name, "value": value, "inline": inline}


def _side_fields(data):
    return [_field("BTTS YES", _line(data["overall"]["YES"])),
            _field("BTTS NO", _line(data["overall"]["NO"]))]


def _line(p):
    return f'{percent(p)} | {p["correct"]}W–{p["incorrect"]}L | {p["graded"]} graded'


def _top_line(data):
    p = data["top"]
    if not data["top_total"]:
        return "No recorded highlighted picks"
    return f'{percent(p)} | {p["correct"]}/{p["graded"]} correct | {p["pending"]} ungraded'


def _payload(title, description, fields, footer):
    return validate_payload({
        "embeds": [{
            "title": title, "description": description, "color": BLUE,
            "fields": fields, "footer": {"text": footer},
        }],
        "allowed_mentions": {"parse": []},
    })


def weekly_payload(data):
    start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    a = data["overall"]["ALL"]
    fields = [_field("Overall Accuracy", _line(a), False)]
    fields += _side_fields(data)
    fields.append(_field("⭐ Top 3 highlights", _top_line(data), False))
    fields.append(_field("Daily breakdown (Sunday–Saturday)",
                         "\n".join(f'{(start + timedelta(days=i)):%a %b %d}: '
                         + _line(data["days"][(start + timedelta(days=i)).isoformat()])
                         for i in range(7)), False))
    fields.append(_field("Unfinished", f'{a["pending"]} ungraded predictions', False))
    return _payload("StatRally | Weekly Recap",
                    f'{start:%b %d, %Y} – {end:%b %d, %Y} · Sunday–Saturday',
                    fields,
                    "Final verified results only · Experimental Poisson · No financial P&L")


def monthly_payload(data):
    first = date.fromisoformat(data["start"])
    a = data["overall"]["ALL"]
    active = sum(p["graded"] > 0 for p in data["days"].values())
    fields = [
        _field("Overall Accuracy", _line(a), False),
        _field("Active graded days", str(active)),
        _field("Average graded picks / active day", f'{a["graded"]/active:.1f}' if active else "N/A"),
        _field("⭐ Top 3 Accuracy", _top_line(data), False),
        _field("Pending results", str(a["pending"])),
    ] + _side_fields(data)
    return _payload("StatRally | Monthly Recap",
                    f'{first:%B %Y} · Accuracy calendar (Sunday–Saturday)\n'
                    "Green ≥70% · Red <70% · Gray: no graded results. "
                    "Colors are descriptive, not model-quality thresholds.",
                    fields,
                    "Calendar percentage and correct/graded shown per day · No financial P&L")


def calendar_png(data):
    """Render an actual image for Discord, not a screenshot of fabricated results."""
    from PIL import Image, ImageDraw, ImageFont
    first = date.fromisoformat(data["start"])
    n_days = calendar.monthrange(first.year, first.month)[1]
    offset = (first.weekday() + 1) % 7
    rows = (offset + n_days + 6) // 7
    width, height = 980, 310 + rows * 114 + 112
    im = Image.new("RGB", (width, height), "#071527")
    d = ImageDraw.Draw(im)
    def font(size, bold=False):
        try:
            return ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
        except OSError:
            return ImageFont.load_default()
    white, muted = "#F3F7FD", "#A8BBD1"
    d.text((44, 35), "StatRally | Monthly Accuracy", font=font(34, True), fill=white)
    d.text((44, 86), first.strftime("%B %Y") + "   |   Verified predictions", font=font(23), fill=muted)
    a = data["overall"]["ALL"]
    score = percent(a)
    d.text((44, 140), score, font=font(60, True), fill="#F3F7FD")
    d.text((350, 169), f'{a["correct"]}/{a["graded"]} correct  •  {a["pending"]} pending', font=font(22), fill=muted)
    left, top, gap = 42, 282, 9
    cellw = (width - 84 - 6 * gap) // 7
    for col, name in enumerate(("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")):
        d.text((left + col * (cellw + gap) + 12, 237), name, font=font(19, True), fill="#A8BBD1")
    for dayn in range(1, n_days + 1):
        dt = first.replace(day=dayn)
        ix = offset + dayn - 1
        col, row = ix % 7, ix // 7
        x, y = left + col * (cellw + gap), top + row * 114
        p = data["days"][dt.isoformat()]
        # No yellow or orange anywhere in the calendar grid.
        bg = ("#0D784A" if p["accuracy"] >= 70 else "#9B2945") if p["graded"] else "#26354A"
        d.rounded_rectangle((x, y, x+cellw, y+103), radius=13, fill=bg)
        d.text((x+11, y+8), str(dayn), font=font(20, True), fill=white)
        if p["graded"]:
            d.text((x+11, y+37), f'{p["accuracy"]:.0f}%', font=font(27, True), fill=white)
            d.text((x+11, y+75), f'{p["correct"]}/{p["graded"]}', font=font(17), fill=white)
        else:
            d.text((x+11, y+53), "—", font=font(23), fill=muted)
    bottom = top + rows * 114 + 20
    for x, color, text in ((45, "#0D784A", ">=70%"), (284, "#9B2945", "<70%"), (510, "#26354A", "No graded data")):
        d.rounded_rectangle((x, bottom, x+24, bottom+24), radius=5, fill=color)
        d.text((x+36, bottom-1), text, font=font(21), fill=muted)
    d.text((45, bottom+45), "Each day shows accuracy and correct/graded. Small samples can mislead.",
           font=font(17), fill=muted)
    out = BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()


def model_summary(ledger):
    # A single canonical export avoids rescanning every day in history.
    first = {}
    for row in sorted(ledger.export()["records"], key=lambda x: (parse_time(x["issued_at"]), x["comment_id"])):
        first.setdefault(row["prediction"]["fixture_id"], row)
    rows = list(first.values())
    # Group by original model version; do not pool model changes as one algorithm.
    groups = {}
    for row in rows:
        groups.setdefault(row["prediction"]["model_version"], []).append(row)
    versions = {}
    for version, group in sorted(groups.items()):
        perf = performance(group)
        graded = [r for r in group if r["grade"]["status"] == "graded"]
        brier, loss, baseline, base_n = [], [], [], 0
        confusion = Counter()
        for r in graded:
            pred, grade = r["prediction"], r["grade"]
            if type(grade.get("btts_yes")) is not bool:
                # Result alone can be used for actual side classification only if validated.
                actual = (grade["result"] == "WIN") == (pred["side"] == "YES")
            else:
                actual = grade["btts_yes"]
                if actual != ((grade["result"] == "WIN") == (pred["side"] == "YES")):
                    raise RuntimeError("Contradictory actual BTTS label")
            probability = float(Decimal(pred["p_yes"]))
            if not math.isfinite(probability) or probability <= 0 or probability >= 1:
                raise RuntimeError("Non-finite model probability")
            y = int(actual)
            brier.append((probability - y)**2)
            loss.append(-math.log(probability if y else 1-probability))
            confusion[("YES" if actual else "NO", pred["side"])] += 1
            baseline_p = pred.get("baseline_yes_probability")
            if baseline_p is not None:
                q = float(Decimal(str(baseline_p)))
                if not math.isfinite(q) or not 0 <= q <= 1:
                    raise RuntimeError("Invalid stored baseline probability")
                baseline.append(int((q >= .5) == actual))
                base_n += 1
        tp, fp = confusion[("YES", "YES")], confusion[("NO", "YES")]
        tn, fn = confusion[("NO", "NO")], confusion[("YES", "NO")]
        def ratio(num, denom):
            return 100*num/denom if denom else None
        class_quality = {
            "yes_precision": ratio(tp,tp+fp), "yes_recall": ratio(tp,tp+fn),
            "no_precision": ratio(tn,tn+fn), "no_recall": ratio(tn,tn+fp),
        }
        versions[version] = {
            "classification": class_quality,
            "performance": perf, "brier": sum(brier)/len(brier) if brier else None,
            "log_loss": sum(loss)/len(loss) if loss else None,
            "baseline_accuracy": 100*sum(baseline)/base_n if base_n == len(graded) and base_n else None,
            "baseline_n": base_n, "confusion": dict((f"{x[0]}:{x[1]}", v) for x,v in confusion.items()),
        }
    return {"versions": versions, "graded_total": sum(v["performance"]["ALL"]["graded"] for v in versions.values())}


def model_payload(data):
    fields = []
    if not data["versions"]:
        fields.append(_field("Status", "No verified forward model forecasts yet", False))
    for version, item in data["versions"].items():
        p = item["performance"]
        all_ = p["ALL"]
        def fmt(x):
            return f"{x:.4f}" if x is not None else "N/A"
        fields += [
            _field("Model version", version + " · Experimental", False),
            _field("Observed accuracy", _line(all_), False),
            _field("BTTS YES", _line(p["YES"])),
            _field("BTTS NO", _line(p["NO"])),
            _field("YES precision / recall", 
                   " / ".join(f"{item['classification'][k]:.1f}%" if item["classification"][k] is not None else "N/A"
                            for k in ("yes_precision", "yes_recall"))),
            _field("NO precision / recall",
                   " / ".join(f"{item['classification'][k]:.1f}%" if item["classification"][k] is not None else "N/A"
                            for k in ("no_precision", "no_recall"))),
            _field("Brier score ↓", fmt(item["brier"])),
            _field("Log loss ↓", fmt(item["log_loss"])),
            _field("Baseline accuracy (matched fixtures)",
                   f'{item["baseline_accuracy"]:.1f}% ({item["baseline_n"]} graded)' if item["baseline_accuracy"] is not None
                   else "Unavailable; no matched baseline evidence", False),
            _field("Calibration", "Not validated; small forward sample" if all_["graded"] < 200
                   else "Requires a separate reliability assessment", False),
        ]
    # Discord caps fields at 25; limit grouped versions and refuse silent truncation.
    if len(fields) > 25:
        raise RuntimeError("Too many model versions for one Discord embed; add pagination")
    return _payload("StatRally | Model Performance",
                    "Verified forward predictions only · Not a proven betting edge.",
                    fields, "Accuracy is descriptive · Brier/log loss lower is better · No financial P&L")


def _valid_webhook(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in ("discord.com", "discordapp.com")
            or not parsed.path.startswith("/api/webhooks/") or parsed.username or parsed.password):
        raise ValueError("Discord webhook URL required")
    return parsed


def _multi(payload, png):
    # The image is referenced via attachment:// and uploaded using multipart/form-data.
    # validate_payload only accepts supported text fields, so validate before adding image.
    validate_payload(payload)
    message = json.loads(json.dumps(payload))
    message["embeds"][0]["image"] = {"url": "attachment://" + IMAGE_NAME}
    message["attachments"] = [{"id": 0, "filename": IMAGE_NAME,
                               "description": "StatRally monthly calendar showing date, accuracy and correct/graded; green, red or gray only"}]
    boundary = "StatRally" + uuid4().hex
    payload_bytes = json.dumps(message).encode("utf-8")
    parts = [
        b"--"+boundary.encode()+b"\r\nContent-Disposition: form-data; name=\"payload_json\"\r\nContent-Type: application/json\r\n\r\n"
        +payload_bytes+b"\r\n",
        b"--"+boundary.encode()+b'\r\nContent-Disposition: form-data; name="files[0]"; filename="'+IMAGE_NAME.encode()
        +b'"\r\nContent-Type: image/png\r\n\r\n'+png+b"\r\n",
        b"--"+boundary.encode()+b"--\r\n",
    ]
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def month_send(payload, webhook, png, *, opener=None, message_id=None):
    parsed = _valid_webhook(webhook)
    path = parsed.path.rstrip("/")
    if message_id:
        if not isinstance(message_id, str) or not message_id.isascii() or not message_id.isdigit():
            raise ValueError("Confirmed message id required")
        path += "/messages/" + message_id
    query = "" if message_id else urlencode([(k,v) for k,v in parse_qsl(parsed.query) if k!="wait"] + [("wait","true")])
    url = urlunsplit((parsed.scheme,parsed.netloc,path,query,""))
    body, content_type = _multi(payload,png)
    req = Request(url, data=body, headers={"Content-Type":content_type,"User-Agent":"StatRally/0.1"},
                  method="PATCH" if message_id else "POST")
    with (opener or build_opener(NoRedirect()).open)(req,timeout=20) as response:
        if response.status != 200:
            raise RuntimeError("Discord image delivery missing confirmation")
        raw = response.read(65537)
        if len(raw)>65536: raise RuntimeError("Discord receipt too large")
        info = json.loads(raw)
        if not all(isinstance(info.get(k),str) and info[k].isascii() and info[k].isdigit()
                   for k in ("id","channel_id")):
            raise RuntimeError("Invalid Discord message receipt")
        if message_id and info["id"] != message_id:
            raise RuntimeError("Discord edit returned different message")
        return {"message_id":info["id"],"channel_id":info["channel_id"]}


def publish_period(ledger, *, kind, period_id, issue_day, data, payload, webhook, png=None,
                   sender=publish, editor=None):
    if not webhook:
        return "missing_webhook"
    _valid_webhook(webhook)
    if data is None:
        return "no_data"
    current = json.dumps(data, sort_keys=True, separators=(",",":"))
    number = ledger.daily(issue_day.isoformat())
    prefix = PREFIXES[kind]
    events = [e for e in ledger.events(number,prefix) if e.get("period_id")==period_id]
    if events and events[-1].get("state") in ("reserved","update_reserved"):
        raise RuntimeError("Ambiguous existing recap delivery; manual review required")
    accepted = [e for e in events if e.get("state")=="accepted"]
    if len(accepted)>1:
        raise RuntimeError("Duplicate recap acceptance records")
    if not accepted:
        ledger.append(number,prefix,{"period_id":period_id,"state":"reserved"})
        receipt = month_send(payload,webhook,png) if png is not None else sender(payload,webhook,wait=True)
        if not isinstance(receipt,dict) or not all(isinstance(receipt.get(k),str) and receipt[k].isdigit()
                   for k in ("message_id","channel_id")):
            raise RuntimeError("Recap delivery receipt missing")
        ledger.append(number,prefix,{"period_id":period_id,"state":"accepted",
                                      "receipt":receipt,"snapshot":current})
        return "posted"
    latest = [e for e in events if e.get("state") in ("accepted","updated")]
    if not latest or (events and events[-1].get("state") not in ("accepted","updated")):
        raise RuntimeError("Unexpected recap history")
    if latest[-1]["snapshot"]==current:
        return "unchanged"
    receipt = accepted[0]["receipt"]
    ledger.append(number,prefix,{"period_id":period_id,"state":"update_reserved","snapshot":current})
    if png is not None:
        month_send(payload,webhook,png,message_id=receipt["message_id"])
    elif editor is not None:
        editor(payload,webhook,receipt)
    else:
        from daily_results import edit_message
        edit_message(payload,webhook,receipt)
    ledger.append(number,prefix,{"period_id":period_id,"state":"updated","snapshot":current})
    return "updated"


def run(ledger, today, hooks, *, weekly=True, monthly=True, model=True, test_senders=None):
    outcomes = {}
    if weekly:
        # Reconcile the four most recent COMPLETE weeks so late finals can update
        # the original post rather than silently changing historical accuracy.
        recent_end = sunday_start(today)-timedelta(days=1)
        for weeks_ago in range(4):
            end = recent_end-timedelta(days=7*weeks_ago)
            start = end-timedelta(days=6)
            data=summary(ledger,start,end)
            key = "weekly" if weeks_ago == 0 else "weekly_backfill:"+start.isoformat()
            if data["overall"]["ALL"]["graded"]:
                kwargs=(test_senders or {}).get("weekly",{})
                outcomes[key]=publish_period(ledger,kind="weekly",period_id=start.isoformat(),
                    issue_day=end,data={k:v for k,v in data.items() if k!="records"},payload=weekly_payload(data),
                    webhook=hooks.get("weekly",""),**kwargs)
            elif weeks_ago == 0:
                outcomes[key]="no_verified_results"
    if monthly:
        # Revisit last month during the first week, but never populate dates
        # with forecasts that have not been graded.
        starts = [today.replace(day=1)]
        if today.day <= 7:
            starts.append(today.replace(day=1)-timedelta(days=1))
        for ix, target in enumerate(starts):
            start,end=month_bounds(target)
            data=summary(ledger,start,end)
            key = "monthly" if ix == 0 else "monthly_previous"
            if data["overall"]["ALL"]["graded"]:
                kwargs=(test_senders or {}).get("monthly",{})
                outcomes[key]=publish_period(ledger,kind="monthly",period_id=start.strftime("%Y-%m"),
                    issue_day=start,data={k:v for k,v in data.items() if k!="records"},payload=monthly_payload(data),
                    webhook=hooks.get("monthly",""),png=calendar_png(data),**kwargs)
            elif ix == 0:
                outcomes[key]="no_verified_results"
    if model:
        data=model_summary(ledger)
        if data["graded_total"]:
            kwargs=(test_senders or {}).get("model",{})
            outcomes["model"]=publish_period(ledger,kind="model",period_id="all-forward-v1",
                issue_day=date(2026,11,1),data=data,payload=model_payload(data),
                webhook=hooks.get("model",""),**kwargs)
        else:
            outcomes["model"]="no_verified_results"
    return outcomes


def main():
    import os
    ledger=Ledger(os.environ.get("GITHUB_REPOSITORY",""),os.environ.get("GH_TOKEN","")).load()
    now=datetime.now(timezone.utc).astimezone(CENTRAL)
    hooks={"weekly":os.environ.get("STATRALLY_WEEKLY_RECAP_DISCORD_WEBHOOK",""),
           "monthly":os.environ.get("STATRALLY_MONTHLY_RECAP_DISCORD_WEBHOOK",""),
           "model":os.environ.get("STATRALLY_MODEL_PERFORMANCE_DISCORD_WEBHOOK","")}
    result=run(ledger,now.date(),hooks)
    print("STATRALLY_RECAPS="+json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
