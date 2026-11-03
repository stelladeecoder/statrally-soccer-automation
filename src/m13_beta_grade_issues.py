"""Grade delivered paper Issues; persist reservations before any results POST."""
import json
import os
from datetime import datetime, timedelta, timezone

from m13_beta_dispatch import DELIVERY_MESSAGE, github
from m13_beta_signals import parse_time, render_beta, signal_identity, signal_proof
from m13_discord_publish import publish
from m13_discord_embeds import render_paper_result
from m13_beta_grading import grade, aggregate, fetch_scoreboard, LEAGUES

BOT = "github-actions[bot]"
DELIVERED = DELIVERY_MESSAGE


def records(path, token):
    result = []
    separator = "&" if "?" in path else "?"
    for page in range(1, 21):
        batch = github("GET", path + separator + f"per_page=100&page={page}", token)
        if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
            raise RuntimeError("Incomplete GitHub record history; refusing publication")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise RuntimeError("GitHub history exceeded checked pages; refusing publication")


def bot(record):
    return record.get("user", {}).get("login") == BOT


def has_marker(comment, prefix, identity):
    if not bot(comment):
        return False
    first = (comment.get("body") or "").splitlines()
    if not first or not first[0].startswith(prefix):
        return False
    try:
        ticker, side, kickoff = first[0].removeprefix(prefix).split("|", 2)
        return signal_identity({"market_ticker": ticker, "side": side, "kickoff_utc": kickoff}) == identity
    except ValueError:
        raise RuntimeError("Ambiguous durable paper marker requires review") from None


def delivered_record(issue, comments):
    if not bot(issue):
        return None
    body = issue.get("body") or ""
    if "statrally-test-only" in body:
        return None
    signal = json.loads(body.split("statrally-beta-data:", 1)[1].split("\n", 1)[0])
    created = parse_time(issue.get("created_at"))
    kickoff = parse_time(signal.get("kickoff_utc"))
    # GitHub timestamps have one-second precision. Validate at the end of that
    # recorded second and require it still to be strictly before kickoff.
    render_beta({"schema_version": 1, "status": "experimental_paper", "trades_placed": 0,
                 "signals": [signal]}, now=created + timedelta(seconds=1))
    identity = signal_identity(signal)
    marker = {"user": {"login": BOT}, "body": next((line for line in body.splitlines() if line.startswith("statrally-beta-id:")), "")}
    if not has_marker(marker, "statrally-beta-id:", identity):
        raise ValueError("Paper reservation does not match the saved signal")
    for comment in comments:
        expected = DELIVERED + "\nstatrally-beta-delivery-proof:" + signal_proof(signal)
        if bot(comment) and comment.get("body") == expected:
            delivered = parse_time(comment.get("created_at"))
            updated = parse_time(comment.get("updated_at"))
            if created <= delivered <= updated < kickoff:
                return signal
    return None


def comment(repo, number, token, body):
    saved = github("POST", f"/repos/{repo}/issues/{number}/comments", token, {"body": body})
    if not isinstance(saved, dict) or type(saved.get("id")) is not int or saved["id"] <= 0:
        raise RuntimeError("Durable comment reservation not confirmed; refusing delivery")
    return saved


def run(repo, token, *, now=None, webhook=None):
    now = now or datetime.now(timezone.utc)
    webhook = os.environ.get("STATRALLY_RESULTS_DISCORD_WEBHOOK", "") if webhook is None else webhook
    all_issues = records(f"/repos/{repo}/issues?state=all", token)
    outcomes, cache, seen, prepared = [], {}, {}, []
    counts = {"unconfirmed": 0, "invalid_records": 0, "source_failures": 0,
              "results_delivered": 0, "already_reserved": 0, "results_delivery_unconfirmed": 0,
              "duplicate_records": 0}
    for issue in all_issues:
        if "pull_request" in issue or "statrally-beta-data:" not in (issue.get("body") or ""):
            continue
        if not bot(issue):
            counts["invalid_records"] += 1
            continue
        comments = records(f"/repos/{repo}/issues/{issue['number']}/comments", token)
        try:
            signal = delivered_record(issue, comments)
            if signal is None:
                counts["unconfirmed"] += 1
                continue
            if signal.get("league") not in LEAGUES:
                raise ValueError("Unsupported verified fixture league")
            kickoff = parse_time(signal["kickoff_utc"])
            identity_key = (signal["league"], signal["espn_event_id"], kickoff)
            if identity_key in seen:
                if seen[identity_key] != signal_proof(signal):
                    raise RuntimeError("Conflicting delivered predictions for one fixture require review")
                counts["duplicate_records"] += 1
                continue
            seen[identity_key] = signal_proof(signal)
            prepared.append((issue, comments, signal))
        except (ValueError, KeyError, TypeError, OSError):
            counts["source_failures"] += 1
            outcomes.append({"status": "pending"})
    # Check every delivered reservation for a conflicting duplicate before
    # grading, writing outcome comments or sending any Discord result.
    for issue, comments, signal in prepared:
        try:
            kickoff = parse_time(signal["kickoff_utc"])
            if kickoff >= now:
                outcomes.append({"status": "pending"})
                continue
            key = (signal["league"], kickoff.strftime("%Y%m%d"))
            if key not in cache:
                cache[key] = fetch_scoreboard(*key)
            result = grade(signal, cache[key])
        except (ValueError, KeyError, TypeError, OSError):
            counts["source_failures"] += 1
            outcomes.append({"status": "pending"})
            continue
        if result["status"] != "graded":
            outcomes.append({"status": "pending"})
            continue
        payload = render_paper_result(signal, result)
        if payload is None:
            raise RuntimeError("Verified graded result presentation required")
        identity = signal_identity(signal)
        marker = "statrally-beta-grade:" + identity
        result_line = "Paper outcome: **" + result["result"] + "** | Final " + str(result["home_goals"]) + "-" + str(result["away_goals"]) + " | No trade."
        prior_grades = [item for item in comments if has_marker(item, "statrally-beta-grade:", identity)]
        if any((item.get("body") or "").splitlines()[1:] != [result_line] for item in prior_grades):
            raise RuntimeError("Previously recorded outcome differs from current verification; manual review required")
        if not prior_grades:
            comment(repo, issue["number"], token, marker + "\n" + result_line)
        reserved = "statrally-beta-results-reserved:" + identity
        prior_reservation = any(has_marker(item, "statrally-beta-results-reserved:", identity) for item in comments)
        confirmed_result = any(has_marker(item, "statrally-beta-results-delivered:", identity) for item in comments)
        if confirmed_result and not prior_reservation:
            raise RuntimeError("Results receipt exists without reservation; refusing another delivery")
        if prior_reservation:
            counts["already_reserved"] += 1
            if not confirmed_result:
                counts["results_delivery_unconfirmed"] += 1
        else:
            if not webhook:
                raise RuntimeError("Results webhook is missing; verified outcome retained without delivery")
            comment(repo, issue["number"], token, reserved)
            # These writes/sends deliberately sit OUTSIDE source-error handling.
            # A failure must fail the workflow, leaving the reservation intact.
            publish(payload, webhook)
            comment(repo, issue["number"], token, "statrally-beta-results-delivered:" + identity + "\nDiscord accepted the independently verified paper outcome. No financial result.")
            counts["results_delivered"] += 1
        outcomes.append(result)
    snapshot = aggregate(outcomes)
    incomplete = counts["source_failures"] or counts["results_delivery_unconfirmed"]
    report = {"status": "paper_performance_no_trades" if not incomplete else "paper_verification_incomplete",
              "snapshot": snapshot, "checks": counts,
              "note": "Only authenticated bot-reserved, pre-kickoff delivered paper signals are graded."}
    print(json.dumps(report, sort_keys=True))
    if incomplete:
        raise RuntimeError("Paper verification/delivery incomplete; previous dashboard retained; no automatic resend")
    if snapshot["graded"] or snapshot["pending"]:
        title = "StatRally BETA | experimental paper performance"
        dashboard = next((item for item in all_issues if item.get("title") == title and "pull_request" not in item and bot(item)), None)
        body = "\n".join([
            "**Experimental paper predictions only. No actual trades or verified edge.**",
            f"Graded: {snapshot['graded']} | Wins: {snapshot['wins']} | Losses: {snapshot['losses']} | Pending: {snapshot['pending']}",
            f"Hit rate: {snapshot['hit_rate']}", f"Brier score (where probabilities available): {snapshot['brier_score'] or 'N/A'}",
            "Includes independently graded, confirmed pre-kickoff Discord-delivered Issue signals.",
            "This does not represent realized ROI or monetary profit."])
        if dashboard:
            github("PATCH", f"/repos/{repo}/issues/{dashboard['number']}", token, {"body": body})
        else:
            github("POST", f"/repos/{repo}/issues", token, {"title": title, "body": body})
    return report


def main():
    repo, token, webhook = (os.environ.get(key, "") for key in ("GITHUB_REPOSITORY", "GH_TOKEN", "STATRALLY_RESULTS_DISCORD_WEBHOOK"))
    if not all((repo, token, webhook)):
        raise SystemExit("Missing beta grading configuration")
    try:
        run(repo, token, webhook=webhook)
    except Exception as error:
        raise SystemExit("Beta grading failed (" + type(error).__name__ + "); durable reservations retained. No automatic resend.") from None


if __name__ == "__main__":
    main()
