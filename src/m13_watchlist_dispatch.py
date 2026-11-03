"""Durable daily watchlist reservations; never retry uncertain Discord delivery."""
import hashlib
import json
import os

from m13_beta_dispatch import github
from m13_beta_grade_issues import records
from m13_discord_publish import publish, render_watchlist_pages


def process(scan, repo, token, webhook):
    pages = render_watchlist_pages(scan)
    if not pages:
        raise RuntimeError("No verified fixtures and incomplete feeds; refusing an empty-day claim")
    marker = "statrally-watchlist-day:" + scan["date_central"]
    history = records(f"/repos/{repo}/issues?state=all", token)
    prior=[item for item in history if marker in (item.get("body") or "").splitlines()]
    if prior:
        if len(prior)!=1:
            raise RuntimeError("Ambiguous watchlist reservation history; manual review required")
        saved=prior[0]
        lines=(saved.get("body") or "").splitlines()
        try:
            count=int(next(line.removeprefix("Pages: ") for line in lines if line.startswith("Pages: ")))
            proof=next(line for line in lines if line.startswith("Payload SHA256: "))
            if count<1:raise ValueError()
        except (StopIteration,ValueError):
            raise RuntimeError("Watchlist reservation lacks complete delivery evidence; no automatic resend") from None
        receipts=records(f"/repos/{repo}/issues/{saved['number']}/comments",token)
        confirmed={item.get("body") for item in receipts if item.get("user",{}).get("login")=="github-actions[bot]"}
        if any(f"statrally-watchlist-page-delivered:{index}/{count}\nDiscord accepted this page. "+proof not in confirmed for index in range(1,count+1)):
            raise RuntimeError("Watchlist delivery uncertain; reservation retained; no automatic resend")
        print('{"status":"watchlist_already_reserved","messages_sent":0}')
        return 0
    proof = hashlib.sha256(json.dumps(pages, sort_keys=True).encode()).hexdigest()
    issue = github("POST", f"/repos/{repo}/issues", token, {
        "title": "StatRally watchlist | " + scan["date_central"],
        "body": marker + "\nPayload SHA256: " + proof + f"\nPages: {len(pages)}\nReserved before Discord delivery. No automatic resend after uncertain delivery."})
    if not isinstance(issue, dict) or type(issue.get("number")) is not int or issue["number"] <= 0:
        raise RuntimeError("Durable watchlist reservation not confirmed")
    for index, payload in enumerate(pages, 1):
        publish(payload, webhook)
        receipt = github("POST", f"/repos/{repo}/issues/{issue['number']}/comments", token, {
            "body": f"statrally-watchlist-page-delivered:{index}/{len(pages)}\nDiscord accepted this page. Payload SHA256: " + proof})
        if not isinstance(receipt, dict) or type(receipt.get("id")) is not int or receipt["id"] <= 0:
            raise RuntimeError("Watchlist accepted but durable receipt unconfirmed; no automatic resend")
    print(json.dumps({"status": "watchlist_delivered", "messages_sent": len(pages),
                      "source_complete": scan["status"] == "fixture_schedule"}))
    if scan["status"] != "fixture_schedule":
        raise RuntimeError("Partial watchlist delivered with explicit source failures; reservation retained")
    return len(pages)


def main():
    try:
        path, repo, token, webhook = (os.environ.get(name, "") for name in
            ("WATCHLIST_INPUT_FILE", "GITHUB_REPOSITORY", "GH_TOKEN", "STATRALLY_DISCORD_WEBHOOK"))
        if not all((path, repo, token, webhook)):
            raise ValueError("Missing configuration")
        with open(path, encoding="utf-8") as stream:
            process(json.load(stream), repo, token, webhook)
    except Exception:
        raise SystemExit("Watchlist delivery failed; durable reservations retained. No automatic resend.") from None


if __name__ == "__main__":
    main()
