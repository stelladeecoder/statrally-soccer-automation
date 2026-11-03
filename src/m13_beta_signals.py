"""M13 experimental paper signals. Never interpret these as approved bets."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import hashlib
import json
from m13_discord_embeds import CENTRAL, pick_card, validate_payload

def number(value):
    if type(value) not in (str,int,float) or isinstance(value,bool):
        raise ValueError("Invalid numeric field")
    try:
        x=Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid numeric field") from None
    if not x.is_finite():
        raise ValueError("Nonfinite numeric field")
    return x

def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp string required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid timestamp") from None
    if result.tzinfo is None:
        raise ValueError("Aware timestamp required")
    return result.astimezone(timezone.utc)


def signal_identity(signal):
    ticker, side = signal.get("market_ticker"), signal.get("side")
    if not isinstance(ticker, str) or not ticker.strip() or side not in ("YES", "NO"):
        raise ValueError("Invalid paper signal identity")
    return ticker + "|" + side + "|" + parse_time(signal.get("kickoff_utc")).isoformat()


def signal_proof(signal):
    snapshot = dict(signal)
    for field in ("kickoff_utc", "observed_at_utc"):
        snapshot[field] = parse_time(snapshot.get(field)).isoformat()
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def render_beta(envelope, now=None, *, allow_empty=False, require_current_day=False):
    if not isinstance(envelope,dict) or envelope.get("schema_version")!=1 or envelope.get("status")!="experimental_paper":
        raise ValueError("Experimental paper schema required")
    if type(envelope.get("trades_placed")) is not int or envelope["trades_placed"]!=0:
        raise ValueError("Trading activity not allowed")
    if set(envelope)!={"schema_version","status","trades_placed","signals"}:
        raise ValueError("Unreviewed beta envelope fields")
    candidates=envelope.get("signals")
    if not isinstance(candidates,list) or not (0 if allow_empty else 1)<=len(candidates)<=3:
        raise ValueError("One to three signals required")
    if not candidates:
        return None
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Aware clock required")
    seen=set()
    embeds=[]
    for s in candidates:
        if not isinstance(s,dict) or s.get("fixture_verified") is not True or s.get("quote_verified") is not True:
            raise ValueError("Independent fixture and quote verification required")
        fields=("market_ticker","home_team","away_team","side","kickoff_utc","observed_at_utc","league","espn_event_id")
        if set(s)-set(fields)-{"model_probability","market_price","fixture_verified","quote_verified","espn_home_team_id","espn_away_team_id"}:
            raise ValueError("Unreviewed signal fields must not enter public paper logs")
        ids=(s.get("espn_home_team_id"),s.get("espn_away_team_id"))
        if any(value is not None for value in ids):
            if any(not isinstance(value,str) or not value.isascii() or not value.isdigit() for value in ids) or ids[0]==ids[1]:
                raise ValueError("Both distinct ESPN team IDs are required")
        if any(not isinstance(s.get(k),str) or not s[k].strip() for k in fields):
            raise ValueError("Missing signal identity")
        if s["side"] not in ("YES","NO") or s["market_ticker"] in seen:
            raise ValueError("Invalid side or duplicate market")
        if s["league"] not in ("epl","bundesliga","laliga","serie_a","ligue_1","eredivisie","liga_portugal","brasileirao","mls","liga_mx","primera_lpf","champions_league","europa_league") or not s["espn_event_id"].isascii() or not s["espn_event_id"].isdigit():
            raise ValueError("Supported league and explicit ESPN event identity required")
        seen.add(s["market_ticker"])
        try:
            kickoff=datetime.fromisoformat(s["kickoff_utc"].replace("Z","+00:00"))
            observed=datetime.fromisoformat(s["observed_at_utc"].replace("Z","+00:00"))
        except ValueError:
            raise ValueError("Invalid timestamp") from None
        if kickoff.tzinfo is None or observed.tzinfo is None:
            raise ValueError("Aware timestamps required")
        if not observed<=now<kickoff or (now-observed).total_seconds()>900:
            raise ValueError("Quote stale, future, or fixture already started")
        p=number(s.get("model_probability"))
        q=number(s.get("market_price"))
        if not Decimal("0")<=p<=Decimal("1") or not Decimal("0")<q<Decimal("1"):
            raise ValueError("Invalid probability or executable price")
        if require_current_day and kickoff.astimezone(CENTRAL).date() != now.astimezone(CENTRAL).date():
            raise ValueError("New paper picks must kick off on the current Central calendar day")
        embeds.append(pick_card(s))
    return validate_payload({"content":"Experimental paper picks · Unvalidated model · No verified betting edge · No trades placed.",
                             "embeds":embeds,"allowed_mentions":{"parse":[]}})
