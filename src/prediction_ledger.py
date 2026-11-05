"""Append-only bot-authored daily Issues ledger, independent of Discord delivery.

Forecast comments cannot be edited through this API. GitHub server creation time,
unchanged comment timestamps and semantic hashes are checked on every read.
Administrative tampering fails closed; GitHub is not WORM storage.
"""
from datetime import datetime, timedelta, timezone
import json

from m13_beta_dispatch import github
from m13_beta_signals import parse_time
from m13_discord_embeds import CENTRAL
from prediction_schema import BASE, FORECAST, STATUSES, canonical, forecast_identity, validate

BOT = "github-actions[bot]"
LEDGER = "statrally-prediction-ledger-v1:"
PREDICTION = "statrally-prediction-v1:"
MARKET = "statrally-market-v1:"
GRADE = "statrally-grade-v1:"
DELIVERY = "statrally-prediction-delivery-v1:"
SCAN = "statrally-prediction-scan-v1:"
METRICS = "statrally-prediction-metrics-v1:"
QUARANTINE = "statrally-prediction-quarantine-v1:"
SELECTION = "statrally-selection-decision-v1:"


class Ledger:
    def __init__(self, repo, token, *, call=github):
        if repo != "stelladeecoder/statrally-soccer-automation":
            raise ValueError("Explicit public prediction repository required")
        self.repo, self.token, self.call = repo, token, call
        self.issues, self.comments, self.forecasts = [], {}, []

    def pages(self, path):
        result = []
        sep = "&" if "?" in path else "?"
        for page in range(1, 101):
            batch = self.call("GET", path+sep+f"per_page=100&page={page}", self.token)
            if not isinstance(batch, list) or any(not isinstance(x, dict) for x in batch):
                raise RuntimeError("Incomplete canonical ledger history")
            result.extend(batch)
            if len(batch) < 100:
                return result
        raise RuntimeError("Ledger pagination exhausted; no truncated output permitted")

    def load(self):
        self.issues = self.pages(f"/repos/{self.repo}/issues?state=all")
        self.comments, self.forecasts = {}, []
        days, identities = set(), set()
        for issue in self.issues:
            if issue.get("pull_request") or not (issue.get("body") or "").startswith(LEDGER):
                continue
            if issue.get("user", {}).get("login") != BOT:
                continue
            metadata = json.loads(issue["body"][len(LEDGER):])
            day = metadata["date_central"]
            if set(metadata) != {"schema_version", "date_central"} or metadata["schema_version"] != 1 or day in days:
                raise RuntimeError("Ambiguous canonical ledger day")
            days.add(day)
            rows = self.pages(f"/repos/{self.repo}/issues/{issue['number']}/comments")
            self.comments[issue["number"]] = rows
            for item in rows:
                if item.get("user", {}).get("login") != BOT or not (item.get("body") or "").startswith(PREDICTION):
                    continue
                record = validate(json.loads(item["body"][len(PREDICTION):]), stored=True)
                created, updated = parse_time(item["created_at"]), parse_time(item["updated_at"])
                kickoff = parse_time(record["kickoff_utc"])
                quarantined = any(e.get("prediction_id")==record["prediction_id"] and e.get("comment_id")==item["id"]
                                  and e.get("reason")=="not_issued_prematch" for e in self.events(issue["number"],QUARANTINE))
                if created+timedelta(seconds=1) >= kickoff and quarantined:
                    continue
                if (created != updated or not parse_time(record["created_at"]) <= created
                        or created+timedelta(seconds=1) >= kickoff or kickoff.astimezone(CENTRAL).date().isoformat() != day
                        or record["prediction_id"] in identities):
                    raise RuntimeError("Edited, duplicate or post-kickoff forecast; manual integrity review required")
                identities.add(record["prediction_id"])
                self.forecasts.append({"prediction": record, "issue_number": issue["number"],
                                       "comment_id": item["id"], "issued_at": item["created_at"]})
        return self

    def daily(self, day):
        for issue in self.issues:
            if issue.get("user", {}).get("login") == BOT and (issue.get("body") or "").startswith(LEDGER):
                if json.loads(issue["body"][len(LEDGER):])["date_central"] == day:
                    return issue["number"]
        body = LEDGER+canonical({"schema_version": 1, "date_central": day})
        result = self.call("POST", f"/repos/{self.repo}/issues", self.token,
                           {"title": "StatRally prediction ledger | "+day, "body": body})
        if not isinstance(result, dict) or type(result.get("number")) is not int or result["number"] <= 0:
            raise RuntimeError("Daily ledger reservation unconfirmed")
        self.issues.append(result)
        self.comments[result["number"]] = []
        return result["number"]

    def append(self, issue, prefix, value):
        body = prefix+canonical(value)
        if len(body.encode()) > 60000:
            raise RuntimeError("Ledger comment exceeds safe size")
        result = self.call("POST", f"/repos/{self.repo}/issues/{issue}/comments", self.token, {"body": body})
        if not isinstance(result, dict) or type(result.get("id")) is not int or result["id"] <= 0 or result.get("body") != body:
            raise RuntimeError("Durable append confirmation missing; no automatic resend")
        self.comments.setdefault(issue, []).append(result)
        return result

    def events(self, issue, prefix):
        result = []
        for item in self.comments.get(issue, []):
            if item.get("user", {}).get("login") != BOT or not (item.get("body") or "").startswith(prefix):
                continue
            if parse_time(item["created_at"]) != parse_time(item["updated_at"]):
                raise RuntimeError("Edited canonical ledger event; integrity review required")
            result.append(json.loads(item["body"][len(prefix):]))
        return result

    def issue_slate(self, slate, *, now=None):
        now = now or datetime.now(timezone.utc)
        if (not isinstance(slate, dict) or set(slate) != {"schema_version", "date_central", "generated_at", "trades_placed", "fixtures", "coverage"}
                or slate["schema_version"] != 1 or slate["trades_placed"] != 0 or slate["date_central"] != now.astimezone(CENTRAL).date().isoformat()
                or not isinstance(slate["fixtures"], list)):
            raise ValueError("Current-day independent no-trade slate required")
        # Validate the ENTIRE private export before any public write.
        for record in slate["fixtures"]:
            if record.get("prediction_status") == "predicted":
                validate(record)
            elif (set(record) != BASE | {"reason"} or record.get("prediction_status") not in STATUSES
                  or record.get("reason") not in STATUSES | {"conflicting_fixture_snapshots", "forecast_failed"}):
                raise ValueError("Unreviewed exclusion record")
        # Only finite, bounded, allowlisted coverage counters leave the runner.
        from m13_discord_embeds import COMPETITIONS
        if not isinstance(slate["coverage"], dict) or set(slate["coverage"]) != set(COMPETITIONS):
            raise ValueError("All 13 competition coverage statuses required")
        for value in slate["coverage"].values():
            if (not isinstance(value, dict) or set(value) != {"provider_status", "fixtures", "predicted", "excluded", "failed_queries"}
                    or value["provider_status"] not in {"complete", "incomplete"}
                    or any(type(value[k]) is not int or value[k] < 0 for k in ("fixtures", "predicted", "failed_queries"))
                    or not isinstance(value["excluded"], dict) or set(value["excluded"])-STATUSES
                    or any(type(v) is not int or v < 0 for v in value["excluded"].values())):
                raise ValueError("Invalid sanitized coverage")
        number = self.daily(slate["date_central"])
        issued = []
        for record in slate["fixtures"]:
            if record["prediction_status"] != "predicted":
                continue
            identity = forecast_identity(record)
            prior = next((r for r in self.forecasts if r["prediction"]["prediction_id"] == identity), None)
            if prior:
                issued.append(prior["prediction"])
                continue
            if parse_time(record["kickoff_utc"]) <= now+timedelta(seconds=2):
                continue
            revision = 1+max((r["prediction"]["revision"] for r in self.forecasts
                              if r["prediction"]["fixture_id"] == record["fixture_id"]), default=0)
            saved = dict(record, prediction_id=identity, revision=revision)
            comment = self.append(number, PREDICTION, saved)
            created = parse_time(comment["created_at"])
            if created+timedelta(seconds=1) >= parse_time(record["kickoff_utc"]) or created != parse_time(comment["updated_at"]):
                self.append(number,QUARANTINE,{"prediction_id":identity,"comment_id":comment["id"],"reason":"not_issued_prematch"})
                raise RuntimeError("Forecast not durably issued before kickoff; quarantine required")
            self.forecasts.append({"prediction": saved, "issue_number": number,
                                   "comment_id": comment["id"], "issued_at": comment["created_at"]})
            issued.append(saved)
        scan = {"date_central": slate["date_central"], "generated_at": slate["generated_at"],
                "coverage": slate["coverage"], "evaluated": [{k: r[k] for k in BASE | ({"reason"} if r["prediction_status"] != "predicted" else set())}
                                                           for r in slate["fixtures"]]}
        self.append(number, SCAN, scan)
        return {"schema_version": 1, "date_central": slate["date_central"], "predictions": issued}

    def export(self):
        output = []
        for item in self.forecasts:
            p, number = item["prediction"], item["issue_number"]
            identity = p["prediction_id"]
            events = lambda prefix: [e for e in self.events(number, prefix) if e.get("prediction_id") == identity]
            markets, grades = events(MARKET), events(GRADE)
            finals = [g for g in grades if g.get("status") == "graded"]
            if len(finals) > 1:
                raise RuntimeError("Conflicting repeated final grades")
            output.append({**item, "market": markets[-1] if markets else {"status": "provider_unavailable"},
                           "grade": finals[0] if finals else (grades[-1] if grades else {"status": "pending"}),
                           "deliveries": events(DELIVERY)})
        scans = [event for issue in self.comments for event in self.events(issue, SCAN)]
        return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                "records": output, "scans": scans, "trades_placed": 0}
