"""Private Discord operational alerts using public, nonsensitive dedup checkpoints.

This monitor never auto-retries uncertain Discord deliveries or public picks.
"""
import json
import os
import sys
from datetime import datetime, timedelta, time, timezone, date
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
PREFIX = "statrally-admin-monitor-v1:"
SCHEDULER = "statrally-scheduler.yml"
SLOT_TIMES = {"watchlist": [(4, 17)], "picks": [(5, 23), (8, 23), (14, 23)],
              "grading": [(23, 55)]}
BOT = "github-actions[bot]"


def api(method, repo, path, data=None):
    url = "https://api.github.com/repos/" + repo + path
    request = Request(url, data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"}, method=method)
    with urlopen(request, timeout=25) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def issues(repo, call=api):
    for page in range(1, 21):
        rows = call("GET", repo, f"/issues?state=all&per_page=100&page={page}")
        if not isinstance(rows, list):
            raise RuntimeError("Cannot audit issue receipts")
        for row in rows:
            if "pull_request" not in row:
                yield row
        if len(rows) < 100:
            return
    raise RuntimeError("Issue history exceeds audit limit")


def state(repo, rows, call=api):
    matches = [r for r in rows if (r.get("body") or "").startswith(PREFIX)]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous admin monitor state; refusing duplicate alerts")
    if matches:
        row = matches[0]
        if row.get("user", {}).get("login") != BOT:
            raise RuntimeError("Untrusted admin monitor state")
        data = json.loads(row["body"][len(PREFIX):])
        if not isinstance(data, dict) or not isinstance(data.get("alerts", {}), dict):
            raise RuntimeError("Malformed admin monitor state")
        return row["number"], data
    # Only operational timestamps and fingerprints: this GitHub Issue is public.
    data = {"alerts": {}, "report_day": ""}
    result = call("POST", repo, "/issues", {"title": "StatRally monitoring checkpoint",
        "body": PREFIX + json.dumps(data, sort_keys=True)})
    if not isinstance(result, dict) or not result.get("number"):
        raise RuntimeError("Monitoring state reservation failed")
    call("PATCH", repo, f"/issues/{result['number']}", {"state": "closed"})
    return result["number"], data


def save(repo, number, value, call=api):
    response = call("PATCH", repo, f"/issues/{number}",
        {"body": PREFIX + json.dumps(value, sort_keys=True, separators=(",", ":"))})
    if not isinstance(response, dict) or response.get("number") != number:
        raise RuntimeError("Monitoring alert reservation not confirmed")


def send(webhook, content):
    if not webhook.startswith("https://discord.com/api/webhooks/"):
        raise RuntimeError("STATRALLY_ADMIN_DISCORD_WEBHOOK is not a Discord webhook URL")
    parts = urlsplit(webhook)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "wait"]
    url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                      urlencode(query + [("wait", "true")]), ""))
    payload = json.dumps({"content": content[:1900], "allowed_mentions": {"parse": []}}).encode()
    req = Request(url, data=payload, method="POST",
                  headers={"Content-Type": "application/json", "User-Agent": "StatRally-Monitor/1"})
    with urlopen(req, timeout=15) as response:
        if response.status != 200:
            raise RuntimeError("Admin Discord delivery not confirmed; do not blindly retry")
        receipt = json.loads(response.read(65536))
    if not isinstance(receipt.get("id"), str) or not receipt["id"].isdigit():
        raise RuntimeError("Admin Discord receipt missing; do not blindly retry")
    print("STATRALLY_ADMIN_ALERT_CONFIRMED")


def alert(repo, number, data, key, text, webhook, *, now, cooldown=None, call=api, sender=send):
    previous = data.setdefault("alerts", {}).get(key)
    if previous:
        prior = datetime.fromisoformat(previous)
        if cooldown is None or now - prior < cooldown:
            print("STATRALLY_ADMIN_SILENT_DUPLICATE", key)
            return False
    # Reserve before sending; uncertain webhook delivery must not cause repeats.
    data["alerts"][key] = now.isoformat()
    # Bound public operational state size.
    cutoff = now - timedelta(days=10)
    data["alerts"] = {k: v for k, v in data["alerts"].items()
                      if datetime.fromisoformat(v) >= cutoff}
    save(repo, number, data, call)
    sender(webhook, text)
    return True


def scheduler_runs(repo, *, since=None, call=api):
    runs = []
    for page in range(1, 11):
        result = call("GET", repo, f"/actions/workflows/{SCHEDULER}/runs?per_page=100&page={page}")
        batch = result.get("workflow_runs") if isinstance(result, dict) else None
        if not isinstance(batch, list):
            raise RuntimeError("Scheduler run history unavailable")
        runs.extend(r for r in batch if r.get("head_branch") == "main")
        if len(batch) < 100 or (since and batch and
             datetime.fromisoformat(batch[-1]["created_at"].replace("Z", "+00:00")) < since):
            break
    return runs


def receipt_slots(rows):
    checkpoints = {}
    prefix = "statrally-scheduler-checkpoint-v1:"
    for row in rows:
        body = row.get("body") or ""
        if not body.startswith(prefix):
            continue
        if row.get("user", {}).get("login") != BOT:
            raise RuntimeError("Untrusted scheduler receipt")
        record = json.loads(body[len(prefix):])
        task = record.get("task")
        if task not in SLOT_TIMES or task in checkpoints:
            raise RuntimeError("Ambiguous scheduler receipt")
        checkpoints[task] = datetime.fromisoformat(record["completed_slot"])
    return checkpoints


def due_slots(now):
    local = now.astimezone(CENTRAL)
    result = []
    for task, times in SLOT_TIMES.items():
        dates = [local.date()]
        if task == "grading":
            dates.append(local.date() - timedelta(days=1))
        for day in dates:
            for hour, minute in times:
                slot = datetime.combine(day, time(hour, minute), CENTRAL)
                if slot + timedelta(minutes=20) <= local:
                    result.append((task, slot))
    return result



def expected_windows(day):
    """All Central-time posting windows on one calendar day."""
    return [(task, datetime.combine(day, time(hour, minute), CENTRAL))
            for task, times in SLOT_TIMES.items() for hour, minute in times]


def completed_window_audit(repo, rows, call=api):
    """Read durable completion comments; never treat an absent record as success."""
    prefix = "statrally-scheduler-checkpoint-v1:"
    comment_prefix = "statrally-scheduler-slot-v1:"
    recorded = set()
    for issue in rows:
        body = issue.get("body") or ""
        if not body.startswith(prefix):
            continue
        if issue.get("user", {}).get("login") != BOT:
            raise RuntimeError("Untrusted scheduler checkpoint")
        latest = json.loads(body[len(prefix):])
        recorded.add((latest["task"], datetime.fromisoformat(latest["completed_slot"])))
        for page in range(1, 11):
            comments = call("GET", repo,
                f"/issues/{issue['number']}/comments?per_page=100&page={page}")
            if not isinstance(comments, list):
                raise RuntimeError("Scheduler completion history unavailable")
            for comment in comments:
                content = comment.get("body") or ""
                if not content.startswith(comment_prefix):
                    continue
                if comment.get("user", {}).get("login") != BOT:
                    raise RuntimeError("Untrusted scheduler completion comment")
                item = json.loads(content[len(comment_prefix):])
                if item.get("task") not in SLOT_TIMES:
                    raise RuntimeError("Malformed scheduler completion comment")
                recorded.add((item["task"], datetime.fromisoformat(item["completed_slot"])))
            if len(comments) < 100:
                break
        else:
            raise RuntimeError("Scheduler completion history exceeds checked pages")
    return recorded


def window_status_lines(day, completed, *, audit_start=date(2026, 11, 4)):
    """Avoid labeling pre-rollout historical windows as misses."""
    windows = expected_windows(day)
    verified = [(task, when) for task, when in windows if (task, when) in completed]
    missing = [(task, when) for task, when in windows if (task, when) not in completed]
    def format_slot(task, when):
        return f"{when.strftime('%I:%M %p').lstrip('0')} {task}"
    lines = ["Posting windows (Central):"]
    for task, when in windows:
        status = ("complete" if (task, when) in completed else
                  "historical / not verified" if day < audit_start else "missed / no receipt")
        lines.append(f"- {format_slot(task, when)}: {status}")
    if day < audit_start:
        lines.append(f"Verified windows: {len(verified)}/{len(windows)} | "
                     "Unverified historical windows: " + str(len(missing)))
    else:
        lines.append(f"Verified windows: {len(verified)}/{len(windows)} | "
                     "Missed/unconfirmed windows: " + str(len(missing)))
    return lines

def recent_failure_details(repo, run_id, call=api):
    result = call("GET", repo, f"/actions/runs/{int(run_id)}/jobs?per_page=100")
    jobs = result.get("jobs", []) if isinstance(result, dict) else []
    lines = []
    for job in jobs:
        if job.get("conclusion") not in ("failure", "timed_out", "cancelled"):
            continue
        steps = [s.get("name", "") for s in job.get("steps", [])
                 if s.get("conclusion") == "failure"]
        name = job.get("name", "Unknown job")
        if any("Export independently mapped Polymarket" in s for s in steps):
            meaning = "Polymarket US export/data pipeline failed; API cause not yet confirmed"
        elif any("Report schedule and BTTS market eligibility" in s for s in steps):
            meaning = "Polymarket US source incomplete or API error reported; inspect diagnostics"
        elif any("Persist Polymarket US paper log" in s for s in steps):
            meaning = "Paper-pick dispatch failed; Discord delivery may be unconfirmed. Do not auto-resend"
        elif "watchlist" in name.lower():
            meaning = "Watchlist or Discord dispatch failed"
        elif "grading" in name.lower():
            meaning = "Grading or result-posting failed"
        elif "next-check" in name.lower():
            meaning = "Scheduler self-restart failed"
        else:
            meaning = "Scheduled job failed; inspect steps"
        lines.append(f"- {name}: {meaning}")
    return lines or ["- Scheduler run did not finish successfully; inspect its jobs"]


def watch(repo, webhook, *, now, paused=False, call=api, sender=send):
    rows = list(issues(repo, call))
    number, data = state(repo, rows, call)
    runs = scheduler_runs(repo, since=now-timedelta(days=2), call=call)
    if not paused:
        fresh = [r for r in runs if r.get("status") != "queued"]
        last = max((datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                    for r in fresh), default=None)
        if last is None or now - last > timedelta(minutes=20):
            alert(repo, number, data, "heartbeat", "**StatRally Admin | Scheduler heartbeat missing**\n"
                  "No scheduler run confirmed in the previous 20 minutes. Check GitHub Actions.\n"
                  f"https://github.com/{repo}/actions/workflows/{SCHEDULER}",
                  webhook, now=now, cooldown=timedelta(hours=1), call=call, sender=sender)
        checkpoints = receipt_slots(rows)
        for task, slot in due_slots(now):
            if checkpoints.get(task, datetime.min.replace(tzinfo=timezone.utc)) >= slot:
                continue
            alert(repo, number, data, "slot:" + task + ":" + slot.isoformat(),
                f"**StatRally Admin | Unconfirmed scheduled {task}**\n"
                f"Expected: {slot.strftime('%Y-%m-%d %I:%M %p')} Central; no successful receipt "
                "after 20 minutes. A delayed run may still finish.\n"
                f"https://github.com/{repo}/actions/workflows/{SCHEDULER}",
                webhook, now=now, call=call, sender=sender)
    local = now.astimezone(CENTRAL)
    # One report each day after 07:15 Central, covering the previous Central day.
    if local.time() >= time(7, 15):
        day = local.date() - timedelta(days=1)
        if data.get("report_day") != day.isoformat():
            start = datetime.combine(day, time.min, CENTRAL).astimezone(timezone.utc)
            end = datetime.combine(day+timedelta(days=1), time.min, CENTRAL).astimezone(timezone.utc)
            daily = [r for r in runs if start <=
                     datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < end]
            successes = sum(r.get("conclusion") == "success" for r in daily)
            failures = sum(r.get("conclusion") in ("failure", "timed_out", "cancelled") for r in daily)
            paper = [r for r in rows if r.get("title", "").startswith("BETA PAPER | ")
                     and r.get("user", {}).get("login") == BOT
                     and start <= datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < end]
            # Issues are reservations, not proof of Discord delivery.
            delivered = 0
            for issue in paper:
                comments = call("GET", repo, f"/issues/{issue['number']}/comments?per_page=100")
                if any((c.get("body") or "").startswith("Discord delivery returned success.")
                       and c.get("user", {}).get("login") == BOT for c in comments):
                    delivered += 1
            verified_windows = completed_window_audit(repo, rows, call)
            window_lines = window_status_lines(day, verified_windows)
            data["report_day"] = day.isoformat()
            save(repo, number, data, call)
            sender(webhook,
                   f"**StatRally Admin | Daily health report — {day.isoformat()} CT**\n"
                   + "\n".join(window_lines) + "\n"
                   + f"Scheduler executions: {len(daily)} | successful: {successes} | failed/cancelled: {failures}\n"
                   + f"Discord paper signals confirmed delivered: {delivered}\n"
                   + f"Paper reservations: {len(paper)}\n"
                   + "Silent: no new picks, duplicates, successful routine checks. "
                   + "A completed window does not necessarily mean a new pick was posted.\n"
                   + f"https://github.com/{repo}/actions")
            print("STATRALLY_DAILY_REPORT_SENT", day.isoformat())


def failure(repo, webhook, run_id, *, now, call=api, sender=send):
    run = call("GET", repo, f"/actions/runs/{int(run_id)}")
    if run.get("head_branch") != "main" or run.get("conclusion") == "success":
        print("STATRALLY_ADMIN_SILENT_SUCCESS_OR_NONMAIN")
        return
    if run.get("conclusion") not in ("failure", "timed_out", "cancelled", "action_required"):
        print("STATRALLY_ADMIN_SILENT_UNFINISHED")
        return
    rows = list(issues(repo, call))
    number, data = state(repo, rows, call)
    details = recent_failure_details(repo, run_id, call)
    alert(repo, number, data, "run:" + str(run_id),
        "**StatRally Admin | Scheduled workflow failure**\n"
        + "\n".join(details[:5]) + "\n"
        + f"https://github.com/{repo}/actions/runs/{int(run_id)}",
        webhook, now=now, call=call, sender=sender)


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    webhook = os.environ["STATRALLY_ADMIN_DISCORD_WEBHOOK"]
    if not webhook:
        raise SystemExit("Missing STATRALLY_ADMIN_DISCORD_WEBHOOK secret")
    now = datetime.now(timezone.utc)
    if sys.argv[1] == "watch":
        watch(repo, webhook, now=now,
              paused=os.environ.get("STATRALLY_SCHEDULER_PAUSED", "").lower() == "true")
    elif sys.argv[1] == "failure":
        failure(repo, webhook, os.environ["FAILED_RUN_ID"], now=now)
    else:
        raise SystemExit("Unknown monitor command")


if __name__ == "__main__":
    main()
