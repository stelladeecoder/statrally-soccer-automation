"""Canonical forecast tracking, verified grading and downstream delivery CLI."""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path

from m13_beta_grading import grade as verify_final, fetch_scoreboard, LEAGUES
from m13_beta_signals import parse_time
from m13_beta_dispatch import reserved_today
from m13_discord_publish import publish
from m13_discord_embeds import (CENTRAL, match_card, side_style, validate_payload, embed_units,
                                render_paper_result)
from prediction_ledger import Ledger, MARKET, GRADE, DELIVERY, METRICS
from prediction_schema import MARKETS, canonical, validate


def annotate(ledger, envelope):
    if not isinstance(envelope, dict) or set(envelope) != {"schema_version", "markets", "trades_placed"} or envelope["schema_version"] != 1 or envelope["trades_placed"] != 0:
        raise ValueError("Read-only market annotation envelope required")
    known = {r["prediction"]["prediction_id"]: r for r in ledger.forecasts}
    for value in envelope["markets"]:
        keys = {"prediction_id", "provider", "status", "checked_at"}
        if value.get("status") == "verified_available":
            keys |= {"event_slug", "market_slug"}
        if (not isinstance(value, dict) or set(value) != keys or value.get("prediction_id") not in known
                or value.get("provider") != "polymarket_us" or value.get("status") not in MARKETS):
            raise ValueError("Unreviewed market annotation")
        parse_time(value["checked_at"])
        for key in ("event_slug", "market_slug"):
            if key in value and (not isinstance(value[key], str) or not 1 <= len(value[key]) <= 200 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in value[key])):
                raise ValueError("Invalid public market identity")
    for value in envelope["markets"]:
        item = known[value["prediction_id"]]
        events = [e for e in ledger.events(item["issue_number"], MARKET) if e["prediction_id"] == value["prediction_id"]]
        if not events or {k:v for k,v in events[-1].items() if k!="checked_at"} != {k:v for k,v in value.items() if k!="checked_at"}:
            ledger.append(item["issue_number"], MARKET, value)


def verified_outcome(prediction, *, scoreboard=fetch_scoreboard, now=None):
    live = now is None
    now = now or datetime.now(timezone.utc)
    kickoff = parse_time(prediction["kickoff_utc"])
    if now <= kickoff:
        return {"status": "pending"}
    source_date = kickoff.astimezone(timezone.utc).date()
    had_failure = False
    for offset in (0, -1, 1):
        query = (source_date+timedelta(days=offset)).strftime("%Y%m%d")
        try:
            payload = scoreboard(prediction["league"], query)
            if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
                raise OSError("Incomplete score response")
            events = [e for e in payload["events"] if str(e.get("id")) == prediction["espn_event_id"]]
            if not events:
                continue
            if len(events) != 1:
                return {"status": "unconfirmed", "reason": "ambiguous_final_identity"}
            event = events[0]
            status = event.get("status", {}).get("type", {})
            # Reuse the established ID/role/kickoff/full-time grading safeguards.
            result = verify_final(dict(prediction, model_probability=prediction["confidence"]), payload)
            if result["status"] != "graded":
                special = {"STATUS_POSTPONED": "postponed", "STATUS_CANCELED": "canceled",
                           "STATUS_CANCELLED": "canceled", "STATUS_ABANDONED": "abandoned"}
                return {"status": special.get(status.get("name"), "pending")}
            observed = datetime.now(timezone.utc) if live else now
            return {"status": "graded", "btts_yes": result["btts_yes"], "correct": result["result"] == "WIN",
                    "result": result["result"], "home_goals": result["home_goals"], "away_goals": result["away_goals"],
                    "side": prediction["side"], "graded_at": observed.isoformat(), "source_observed_at": observed.isoformat(),
                    "source": "ESPN scoreboard", "source_url": f"https://site.api.espn.com/apis/site/v2/sports/soccer/{LEAGUES[prediction['league']]}/scoreboard?dates={query}"}
        except (OSError, TimeoutError):
            had_failure = True
        except (ValueError, KeyError, TypeError, IndexError):
            return {"status": "unconfirmed", "reason": "fixture_or_final_evidence_mismatch"}
    return {"status": "provider_unavailable" if had_failure else "unconfirmed", "reason": "final_score_not_verified"}


def grade_issued(ledger, *, scoreboard=fetch_scoreboard, now=None):
    live = now is None
    now = now or datetime.now(timezone.utc)
    cache, counts = {}, Counter()
    def cached(league, day):
        key = (league, day)
        if key not in cache:
            try:cache[key] = scoreboard(league, day)
            except OSError as exc:cache[key] = exc
        if isinstance(cache[key],OSError):raise cache[key]
        return cache[key]
    # Read every forecast from the ledger, including forecasts never sent to
    # Discord and forecasts for fixtures with no Polymarket market.
    for item in ledger.export()["records"]:
        prediction = item["prediction"]
        if item["grade"]["status"] == "graded":
            counts["already_graded"] += 1
            continue
        result = verified_outcome(prediction, scoreboard=cached, now=None if live else now)
        counts[result["status"]] += 1
        event = dict(result, prediction_id=prediction["prediction_id"])
        prior = [e for e in ledger.events(item["issue_number"], GRADE) if e["prediction_id"] == prediction["prediction_id"]]
        if not prior or prior[-1] != event:
            ledger.append(item["issue_number"], GRADE, event)
    return dict(counts)


def prediction_pages(items, title):
    pages, cards = [], []
    for item in items:
        prediction = item["prediction"]
        card, when = match_card(prediction, "Experimental paper prediction · Uncalibrated model estimate")
        card["description"] += " · "+when.strftime("%I:%M %p").lstrip("0")+" CT"
        status = item.get("market", {}).get("status", "provider_unavailable")
        if status not in MARKETS:
            raise ValueError("Unreviewed market display status")
        labels = {"verified_available":"Verified available", "not_found":"Not found", "identity_mismatch":"Identity unconfirmed",
                  "market_closed":"Closed", "provider_unavailable":"Provider unavailable"}
        card["fields"] = [{"name":"Prediction","value":side_style(prediction["side"])[1],"inline":True},
                          {"name":"Model estimate","value":format(Decimal(prediction["confidence"]),".1%"),"inline":True},
                          {"name":"Polymarket US","value":labels[status],"inline":True}]
        if cards and (len(cards) >= 8 or sum(embed_units(c) for c in cards)+embed_units(card) > 5700):
            pages.append(cards);cards=[]
        cards.append(card)
    if cards:
        pages.append(cards)
    return [validate_payload({"content":title+f" · {i}/{len(pages)} · No trades; no proven betting edge.",
                              "embeds":batch,"allowed_mentions":{"parse":[]}}) for i,batch in enumerate(pages,1)]


def deliver(ledger, items, *, kind, webhook, now, sender=publish, clock=None):
    existing = {e["prediction_id"] for issue in ledger.comments for e in ledger.events(issue, DELIVERY)
                if e.get("kind") == kind and e.get("state") in {"reserved", "accepted"}}
    fresh = [r for r in items if r["prediction"]["prediction_id"] not in existing]
    pages = prediction_pages(fresh, "Daily BTTS predictions" if kind == "daily" else "Top BTTS predictions")
    done, index = 0, 0
    for payload in pages:
        batch = fresh[index:index+len(payload["embeds"])];index += len(batch)
        # Recheck every fixture immediately before reserving and posting.
        if any(parse_time(r["prediction"]["kickoff_utc"]) <= (clock() if clock else now) for r in batch):
            raise RuntimeError("Prematch delivery deadline passed")
        for item in batch:
            ledger.append(item["issue_number"], DELIVERY, {"prediction_id": item["prediction"]["prediction_id"],
                "kind":kind,"state":"reserved","reserved_at":now.isoformat()})
        receipt = sender(payload, webhook, wait=True)
        for item in batch:
            ledger.append(item["issue_number"], DELIVERY, {"prediction_id": item["prediction"]["prediction_id"],
                "kind":kind,"state":"accepted","receipt":receipt})
        done += len(batch)
    return done


def publish_predictions(ledger, webhook, *, now=None, sender=publish):
    live = now is None
    now = now or datetime.now(timezone.utc)
    clock = (lambda:datetime.now(timezone.utc)) if live else (lambda:now)
    day = now.astimezone(CENTRAL).date()
    all_day = [r for r in ledger.export()["records"] if parse_time(r["prediction"]["kickoff_utc"]).astimezone(CENTRAL).date() == day]
    records = [r for r in all_day if parse_time(r["prediction"]["kickoff_utc"]) > now]
    latest = {}
    for record in records:
        key = record["prediction"]["fixture_id"]
        if key not in latest or record["prediction"]["revision"] > latest[key]["prediction"]["revision"]:
            latest[key] = record
    items = sorted(latest.values(), key=lambda r:(r["prediction"]["kickoff_utc"],r["prediction"]["fixture_id"]))
    # Top reservations remain occupied after ambiguous sends. Legacy official
    # paper reservations share the same three-per-day cap during migration.
    top_ids = {e["prediction_id"] for issue in ledger.comments for e in ledger.events(issue, DELIVERY)
               if e.get("kind") == "top" and e.get("state") == "reserved"}
    occupied = sum(r["prediction"]["prediction_id"] in top_ids for r in all_day)
    occupied += reserved_today(ledger.issues, now=now)
    top_fixtures = {r["prediction"]["fixture_id"] for r in all_day if r["prediction"]["prediction_id"] in top_ids}
    ranked = sorted((r for r in items if r["prediction"]["fixture_id"] not in top_fixtures),
                    key=lambda r:(-Decimal(r["prediction"]["confidence"]),r["prediction"]["fixture_id"]))
    counts = {"daily":deliver(ledger,items,kind="daily",webhook=webhook,now=now,sender=sender,clock=clock)}
    counts["top"] = deliver(ledger,ranked[:max(0,3-occupied)],kind="top",webhook=webhook,now=now,sender=sender,clock=clock)
    return counts


def publish_results(ledger, webhook, *, sender=publish):
    items = ledger.export()["records"]
    reserved = {e["prediction_id"] for issue in ledger.comments for e in ledger.events(issue, DELIVERY)
                if e.get("kind") == "result" and e.get("state") in {"reserved","accepted"}}
    count = 0
    for item in items:
        p, grade = item["prediction"], item["grade"]
        if grade["status"] != "graded" or p["prediction_id"] in reserved:
            continue
        ledger.append(item["issue_number"], DELIVERY, {"prediction_id":p["prediction_id"],"kind":"result","state":"reserved"})
        receipt = sender(render_paper_result(p,grade),webhook,wait=True)
        ledger.append(item["issue_number"], DELIVERY, {"prediction_id":p["prediction_id"],"kind":"result","state":"accepted","receipt":receipt})
        count += 1
    return count


def report_provider_outage(ledger, *, now=None):
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(CENTRAL).date()
    records = [r for r in ledger.export()["records"] if parse_time(r["prediction"]["kickoff_utc"]).astimezone(CENTRAL).date() == day]
    failures = sum(r["market"]["status"] == "provider_unavailable" for r in records)
    if not failures:
        return False
    from m18_admin_monitor import state, alert
    webhook = os.environ.get("STATRALLY_ADMIN_DISCORD_WEBHOOK", "")
    if not webhook:
        raise RuntimeError("Market outage recorded; admin webhook configuration unavailable")
    number, data = state(ledger.repo, ledger.issues)
    return alert(ledger.repo,number,data,"independent-prediction-market-outage",
        f"StatRally: Polymarket US verification unavailable for {failures} issued forecasts. Independent predictions remain saved and gradeable. No trades.",
        webhook,now=now,cooldown=timedelta(hours=1))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=("issue","annotate","grade","export","publish","results","metrics","alert"))
    parser.add_argument("--input",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    ledger=Ledger(os.environ.get("GITHUB_REPOSITORY",""),os.environ.get("GH_TOKEN","")).load()
    result={}
    if args.mode=="issue":result=ledger.issue_slate(json.loads(args.input.read_text()))
    elif args.mode=="annotate":annotate(ledger,json.loads(args.input.read_text()))
    elif args.mode=="grade":result=grade_issued(ledger)
    elif args.mode=="export":result=ledger.export()
    elif args.mode=="publish":result=publish_predictions(ledger,os.environ.get("STATRALLY_PICKS_DISCORD_WEBHOOK",""))
    elif args.mode=="results":result={"results_delivered":publish_results(ledger,os.environ.get("STATRALLY_RESULTS_DISCORD_WEBHOOK",""))}
    elif args.mode=="alert":result={"alert_sent":report_provider_outage(ledger)}
    elif args.mode=="metrics":
        # An explicit allowlist serializer below guards the public derived view.
        from prediction_public_export import public_metrics
        report=public_metrics(json.loads(args.input.read_text()))
        number=ledger.daily(datetime.now(timezone.utc).astimezone(CENTRAL).date().isoformat())
        ledger.append(number,METRICS,report)
    if args.output:args.output.write_text(json.dumps(result,sort_keys=True,allow_nan=False))
    print("STATRALLY_PLATFORM="+json.dumps({"mode":args.mode,"records":len(ledger.forecasts),
                                         "result_counts":result if args.mode in {"grade","publish","results","alert"} else {},"trades_placed":0},sort_keys=True))


if __name__=="__main__":
    try:main()
    except Exception as error:
        raise SystemExit("Prediction platform failed ("+type(error).__name__+"); immutable records/reservations retained. No blind resend.") from None
