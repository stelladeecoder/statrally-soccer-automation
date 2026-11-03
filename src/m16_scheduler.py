"""Central-time posting slots, checked by a UTC heartbeat with durable receipts."""
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
TIMES = {"watchlist": [(4, 17)], "picks": [(5, 23), (8, 23), (14, 23)],
         "grading": [(23, 55)]}
MARKER = "statrally-scheduler-checkpoint-v1:"


def due_slots(now):
    if now.tzinfo is None:
        raise ValueError("An aware time is required")
    local = now.astimezone(CENTRAL)
    result = {}
    for task, hours in TIMES.items():
        candidates = [datetime.combine(local.date(), time(h, m), CENTRAL)
                      for h, m in hours]
        if task == "grading":
            candidates.append(datetime.combine(local.date() - timedelta(days=1),
                                               time(23, 55), CENTRAL))
        eligible = [value for value in candidates if value <= local]
        result[task] = max(eligible).isoformat() if eligible else ""
    return result


def api(method, path, data=None):
    request = Request("https://api.github.com" + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"}, method=method)
    with urlopen(request, timeout=25) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


def checkpoints(repo, call=api):
    found = {}
    for page in range(1, 21):
        rows = call("GET", f"/repos/{repo}/issues?state=all&per_page=100&page={page}")
        if not isinstance(rows, list):
            raise RuntimeError("Checkpoint history unavailable")
        for row in rows:
            body = row.get("body") or ""
            if not body.startswith(MARKER):
                continue
            data = json.loads(body[len(MARKER):])
            task = data["task"]
            if (task not in TIMES or task in found or
                row.get("user", {}).get("login") != "github-actions[bot]"):
                raise RuntimeError("Ambiguous or untrusted scheduler checkpoint")
            stamp = datetime.fromisoformat(data["completed_slot"])
            if stamp.tzinfo is None or not row.get("number"):
                raise RuntimeError("Malformed scheduler checkpoint")
            found[task] = dict(data, number=row["number"])
        if len(rows) < 100:
            return found
    raise RuntimeError("Checkpoint history exceeds checked pages")


def plan(now, saved):
    slots = due_slots(now)
    return {task: slot if slot and (task not in saved or
            datetime.fromisoformat(saved[task]["completed_slot"]) <
            datetime.fromisoformat(slot)) else ""
            for task, slot in slots.items()}


def complete(repo, slots, results, run_url, call=api):
    saved = checkpoints(repo, call)
    audit_marker = "statrally-scheduler-slot-v1:"
    for task, slot in slots.items():
        if not slot or results.get(task) != "success":
            continue
        if task not in TIMES or slot != due_slots(datetime.fromisoformat(slot))[task]:
            raise ValueError("Invalid scheduler slot")
        if task in saved and datetime.fromisoformat(saved[task]["completed_slot"]) >= datetime.fromisoformat(slot):
            continue
        record = {"task": task, "completed_slot": slot, "run_url": run_url}
        data = {"title": "StatRally scheduler checkpoint | " + task,
                "body": MARKER + json.dumps(record, sort_keys=True), "state": "closed"}
        if task in saved:
            issue_number = saved[task]["number"]
        else:
            data.pop("state")
            created = call("POST", f"/repos/{repo}/issues", data)
            if not isinstance(created, dict) or not created.get("number"):
                raise RuntimeError("Scheduler receipt was not confirmed")
            issue_number = created["number"]

        # Append a per-slot audit before advancing the latest checkpoint. If the
        # subsequent PATCH fails, the next scheduler attempt can safely resume.
        comments = []
        for page in range(1, 11):
            batch = call("GET", f"/repos/{repo}/issues/{issue_number}/comments?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise RuntimeError("Slot audit comments unavailable")
            comments.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise RuntimeError("Slot audit comments exceed checked pages")
        for comment in comments:
            body = comment.get("body") or ""
            if not body.startswith(audit_marker):
                continue
            if comment.get("user", {}).get("login") != "github-actions[bot]":
                raise RuntimeError("Untrusted slot audit comment")
            previous = json.loads(body[len(audit_marker):])
            if previous.get("task") == task and previous.get("completed_slot") == slot:
                break
        else:
            logged = call("POST", f"/repos/{repo}/issues/{issue_number}/comments",
                          {"body": audit_marker + json.dumps(record, sort_keys=True)})
            if not isinstance(logged, dict) or not logged.get("id"):
                raise RuntimeError("Slot audit receipt was not confirmed")

        if task in saved:
            updated = call("PATCH", f"/repos/{repo}/issues/{issue_number}", data)
            if not isinstance(updated, dict) or updated.get("number") != issue_number:
                raise RuntimeError("Latest scheduler checkpoint not confirmed")
        print("Completed slot:", task, slot)

def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    if sys.argv[1] == "gate":
        slots = plan(datetime.now(timezone.utc), checkpoints(repo))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write("slots=" + json.dumps(slots, separators=(",", ":")) + "\n")
            for task, slot in slots.items():
                stream.write(f"{task}={'true' if slot else 'false'}\n")
        print("Due slots:", json.dumps(slots))
    elif sys.argv[1] == "complete":
        complete(repo, json.loads(os.environ["SLOTS"]), json.loads(os.environ["RESULTS"]),
                 os.environ["GITHUB_SERVER_URL"] + "/" + repo + "/actions/runs/" + os.environ["GITHUB_RUN_ID"])
    elif sys.argv[1] == "resume":
        api("POST", f"/repos/{repo}/actions/workflows/statrally-scheduler.yml/dispatches", {"ref": "main"})
        print("GitHub accepted the next automatic scheduler check")
    else:
        raise ValueError("Unknown scheduler command")


if __name__ == "__main__":
    main()
