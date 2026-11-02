"""M13 experimental paper signals. Never interpret these as approved bets."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

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

def render_beta(envelope, now=None):
    if not isinstance(envelope,dict) or envelope.get("schema_version")!=1 or envelope.get("status")!="experimental_paper":
        raise ValueError("Experimental paper schema required")
    if envelope.get("trades_placed")!=0:
        raise ValueError("Trading activity not allowed")
    candidates=envelope.get("signals")
    if not isinstance(candidates,list) or not 1<=len(candidates)<=3:
        raise ValueError("One to three signals required")
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Aware clock required")
    seen=set()
    lines=["**StatRally | BETA PAPER PICKS — EXPERIMENTAL**",
           "Unvalidated model • No verified betting edge • No trades placed"]
    for s in candidates:
        if not isinstance(s,dict) or s.get("fixture_verified") is not True or s.get("quote_verified") is not True:
            raise ValueError("Independent fixture and quote verification required")
        fields=("market_ticker","home_team","away_team","side","kickoff_utc","observed_at_utc")
        if any(not isinstance(s.get(k),str) or not s[k].strip() for k in fields):
            raise ValueError("Missing signal identity")
        if s["side"] not in ("YES","NO") or s["market_ticker"] in seen:
            raise ValueError("Invalid side or duplicate market")
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
        local=kickoff.astimezone(ZoneInfo("America/Chicago"))
        lines.append(f"• {s['home_team']} vs {s['away_team']} | BTTS {s['side']} | {local:%b %d %I:%M %p} CT")
        lines.append(f"  Model estimate {p:.1%} | Kalshi quote ${q:.2f} | PAPER ONLY")
    payload={"content":"\\n".join(lines),"allowed_mentions":{"parse":[]}}
    if len(payload["content"])>2000:
        raise ValueError("Discord message too long")
    return payload
