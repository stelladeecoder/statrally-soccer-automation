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
from prediction_ledger import Ledger, MARKET, GRADE, DELIVERY, METRICS, SELECTION, ENTRY_QUOTE
from prediction_schema import MARKETS, canonical, validate
from prediction_quality import classify, is_starred_probability, load_policy, policy_digest


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
        # A fresh empty search is not proof that an earlier credible
        # identity conflict disappeared. Preserve its unresolved status until
        # an independently verified contract resolves the ambiguity.
        if (events and events[-1]["status"] == "identity_mismatch" and
                value["status"] != "verified_available"):
            # Only a verified market, or a separate explicitly authorized
            # manual review, may resolve an unresolved identity.
            continue
        if not events or {k:v for k,v in events[-1].items() if k!="checked_at"} != {k:v for k,v in value.items() if k!="checked_at"}:
            ledger.append(item["issue_number"], MARKET, value)



def verified_quote_map(report):
    """Allowlist a read-only snapshot, never infer an executable quote."""
    if (not isinstance(report,dict) or set(report)!={"schema_version","source","trades_placed","quotes"}
        or report["schema_version"]!=1 or report["source"]!="polymarket_us"
        or report["trades_placed"]!=0 or not isinstance(report["quotes"],list)):
        raise ValueError("Invalid read-only quote report")
    indexed={}
    for row in report["quotes"]:
        if not isinstance(row,dict) or row.get("status") not in {"verified","unavailable"}:
            raise ValueError("Invalid quote status")
        keys = ({"prediction_id","side","status","market_slug","price_dollars","observed_at"}
                if row["status"]=="verified" else {"prediction_id","side","status"})
        if set(row)!=keys or row["side"] not in ("YES","NO") or not isinstance(row["prediction_id"],str) or row["prediction_id"] in indexed:
            raise ValueError("Unreviewed or duplicate quote")
        if row["status"]=="verified":
            if not isinstance(row["market_slug"],str) or not row["market_slug"]:
                raise ValueError("Missing quote market identity")
            p=Decimal(row["price_dollars"])
            if not p.is_finite() or not 0<p<1:
                raise ValueError("Invalid executable quote")
            parse_time(row["observed_at"])
        indexed[row["prediction_id"]]=row
    return indexed


def safe_quote_for(item, quotes, now):
    """Only present a matching side/market and fresh quote taken before kickoff."""
    p=item["prediction"]
    row=quotes.get(p.get("prediction_id"))
    market=item.get("market",{})
    if not row or row.get("status")!="verified" or market.get("status")!="verified_available":
        return None
    if row["side"]!=p["side"] or row["market_slug"]!=market.get("market_slug"):
        return None
    observed=parse_time(row["observed_at"])
    if not (timedelta(0) <= now-observed <= timedelta(minutes=5)
            and observed < parse_time(p["kickoff_utc"]) and now < parse_time(p["kickoff_utc"])):
        return None
    return row



def save_original_quotes(ledger, report, *, now=None):
    """Persist only the first verified, fresh, side-matched prematch quote.

    No historical backfill. Unknown prices stay unavailable; the reference is
    independent of later quote movements. Source snapshot is not a fill.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Timezone-aware clock required")
    quotes = verified_quote_map(report)
    records = ledger.export()["records"]
    known = {r["prediction"]["prediction_id"]: r for r in records}
    if any(key not in known for key in quotes):
        raise ValueError("Unknown quote prediction")
    count = 0
    for key, row in quotes.items():
        item = known[key]
        if item.get("entry_quote") is not None or row["status"] != "verified":
            continue
        fresh = safe_quote_for(item, quotes, now)
        if fresh is None:
            continue
        event = {
            "prediction_id": key, "provider": "polymarket_us", "side": row["side"],
            "market_slug": row["market_slug"], "price_dollars": row["price_dollars"],
            "observed_at": row["observed_at"], "reference_type": "indicative_buy_quote",
            "fees_verified": False,
        }
        ledger.append(item["issue_number"], ENTRY_QUOTE, event)
        count += 1
    return count


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


def prediction_pages(items, title, *, policy=None, highlighted=False, quotes=None, now=None):
    pages, cards = [], []
    now = now or datetime.now(timezone.utc)
    quotes = quotes or {}
    for item in items:
        prediction = item["prediction"]
        quality = classify(prediction,policy)
        starred = is_starred_probability(prediction)
        card, when = match_card(prediction, "Experimental paper prediction · Uncalibrated model estimate")
        card["description"] += " · "+when.strftime("%I:%M %p").lstrip("0")+" CT"
        status = item.get("market", {}).get("status", "provider_unavailable")
        if status not in MARKETS:
            raise ValueError("Unreviewed market display status")
        labels = {"verified_available":"Verified available", "not_found":"Not found", "identity_mismatch":"Identity unconfirmed",
                  "market_closed":"Closed", "provider_unavailable":"Provider unavailable"}
        card["fields"] = [{"name":"Prediction","value":side_style(prediction["side"])[1],"inline":True},
                          {"name":"YES / NO","value":format(Decimal(prediction["p_yes"]),".1%")+" / "+format(Decimal(prediction["p_no"]),".1%"),"inline":True},
                          {"name":"Selected-side estimate","value":format(Decimal(prediction["confidence"]),".1%"),"inline":True},
                          {"name":"Probability category","value":("⭐ 🟨 **VERY HIGH MODEL PROBABILITY · 70%+**" if starred else quality["probability_category"])+" · descriptive only, not validated reliability","inline":False},
                          {"name":"Model / calibration","value":prediction["model_version"]+" · "+quality["calibration_status"],"inline":False},
                          {"name":"Data quality","value":prediction["data_quality_status"].replace("_"," "),"inline":True},
                          {"name":"Selection status","value":"Validated policy eligible" if quality["selection_eligible"] else "Experimental forecast · Not an approved selection","inline":False},
                          {"name":"Polymarket US","value":labels[status]+(" · Manual review required; availability not verified" if status == "identity_mismatch" else ""),"inline":True}]
        # All predictions share the blue #btts-picks presentation. The star is descriptive.
        verified=safe_quote_for(item,quotes,now)
        if verified:
            price=Decimal(verified["price_dollars"])
            # Pure $1-settlement illustration; excludes fees, liquidity and slippage.
            gross=(Decimal("10")/price)-Decimal("10")
            card["fields"] += [
                {"name":"Market ask at posting","value":"$"+format(price,".4f"),"inline":True},
                {"name":"Quote observed","value":verified["observed_at"]+" · snapshot","inline":False},
                {"name":"Illustrative $10 gross profit","value":"$"+format(gross,".2f")+" if correct; before fees","inline":False}]
        else:
            card["fields"].append({"name":"Market price","value":"Unavailable · no verified current quote","inline":False})
        card["footer"]={"text":("⭐ 70%+ model probability · " if starred else "")+"Experimental paper prediction · Quote not guaranteed fill · No trades"}
        if cards and (len(cards) >= 8 or sum(embed_units(c) for c in cards)+embed_units(card) > 5700):
            pages.append(cards);cards=[]
        cards.append(card)
    if cards:
        pages.append(cards)
    return [validate_payload({"content":title+f" · {i}/{len(pages)} · No trades; no proven betting edge.",
                              "embeds":batch,"allowed_mentions":{"parse":[]}}) for i,batch in enumerate(pages,1)]


def deliver(ledger, items, *, kind, webhook, now, sender=publish, clock=None, policy=None, quotes=None):
    existing = {e["prediction_id"] for issue in ledger.comments for e in ledger.events(issue, DELIVERY)
                if e.get("kind") == kind and e.get("state") in {"reserved", "accepted"}}
    fresh = [r for r in items if r["prediction"]["prediction_id"] not in existing]
    pages = prediction_pages(fresh, "BTTS model picks · verified and identity-unconfirmed markets",policy=policy,quotes=quotes,now=now)
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


def publish_predictions(ledger, webhook, *, now=None, sender=publish, policy=None, quotes=None):
    live = now is None
    now = now or datetime.now(timezone.utc)
    clock = (lambda:datetime.now(timezone.utc)) if live else (lambda:now)
    policy = load_policy() if policy is None else policy
    day = now.astimezone(CENTRAL).date()
    all_day = [r for r in ledger.export()["records"] if parse_time(r["prediction"]["kickoff_utc"]).astimezone(CENTRAL).date() == day]
    records = [r for r in all_day if r["market"]["status"] in {"verified_available", "identity_mismatch"}
               and parse_time(r["prediction"]["kickoff_utc"]) > now]
    latest = {}
    for record in records:
        key = record["prediction"]["fixture_id"]
        if key not in latest or record["prediction"]["revision"] > latest[key]["prediction"]["revision"]:
            latest[key] = record
    items = sorted(latest.values(), key=lambda r:(r["prediction"]["kickoff_utc"],r["prediction"]["fixture_id"]))
    # A star is a descriptive probability threshold, never an approval or a
    # second delivery. All eligible prematch forecasts are published once.
    starred = [r for r in items if is_starred_probability(r["prediction"])]
    decision = {
        "date_central": day.isoformat(), "rule": "descriptive_model_probability_ge_0.70",
        "highlighted_prediction_ids": [r["prediction"]["prediction_id"] for r in starred],
        "status": "descriptive_only_not_validated_bet_selection",
    }
    number = ledger.daily(day.isoformat())
    if not any(d == decision for d in ledger.events(number, SELECTION)):
        ledger.append(number, SELECTION, decision)
    return {"daily": deliver(ledger, items, kind="daily", webhook=webhook,
                             now=now, sender=sender, clock=clock, policy=policy,
                             quotes=quotes),
            "starred": len(starred)}


def publish_results(ledger, webhook, *, sender=publish):
    items = [r for r in ledger.export()["records"]
             if r["market"]["status"] in {"verified_available", "identity_mismatch"}]
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
    parser.add_argument("mode",choices=("issue","annotate","quotes","grade","export","publish","results","metrics","alert"))
    parser.add_argument("--input",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--quotes",type=Path,help="Optional read-only price snapshots for highlighted paper picks")
    args=parser.parse_args()
    ledger=Ledger(os.environ.get("GITHUB_REPOSITORY",""),os.environ.get("GH_TOKEN","")).load()
    result={}
    if args.mode=="issue":result=ledger.issue_slate(json.loads(args.input.read_text()))
    elif args.mode=="annotate":annotate(ledger,json.loads(args.input.read_text()))
    elif args.mode=="quotes":result={"reference_quotes_saved":save_original_quotes(ledger,json.loads(args.input.read_text()))}
    elif args.mode=="grade":result=grade_issued(ledger)
    elif args.mode=="export":result=ledger.export()
    elif args.mode=="publish":
        quotes=verified_quote_map(json.loads(args.quotes.read_text())) if args.quotes and args.quotes.exists() else {}
        result=publish_predictions(ledger,os.environ.get("STATRALLY_PICKS_DISCORD_WEBHOOK",""),quotes=quotes)
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
                                         "result_counts":result if args.mode in {"grade","publish","results","alert","quotes"} else {},"trades_placed":0},sort_keys=True))


if __name__=="__main__":
    try:main()
    except Exception as error:
        raise SystemExit("Prediction platform failed ("+type(error).__name__+"); immutable records/reservations retained. No blind resend.") from None
