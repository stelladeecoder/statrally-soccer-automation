"""Gross hypothetical flat-$10 paper performance from immutable entry quotes.

Not betting profit: no fills, fee verification, slippage or sufficient book depth.
A model probability must never stand in for an actual price.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from m13_beta_signals import parse_time

STAKE = Decimal("10")


def validated_reference(row):
    event = row.get("entry_quote")
    if event is None:
        return None
    p = row["prediction"]
    if not isinstance(event, dict) or set(event) != {
        "prediction_id", "provider", "side", "market_slug", "price_dollars",
        "observed_at", "reference_type", "fees_verified"
    } or event["prediction_id"] != p["prediction_id"] or event["provider"] != "polymarket_us" or (
        event["side"] != p["side"] or event["reference_type"] != "indicative_buy_quote"
        or event["fees_verified"] is not False
    ):
        raise RuntimeError("Invalid immutable reference quote")
    if not isinstance(event["market_slug"], str) or not event["market_slug"]:
        raise RuntimeError("Missing verified market identity")
    # Compare to market identity at saved publication when available.
    market = row.get("market", {})
    if market.get("status") == "verified_available" and market.get("market_slug") != event["market_slug"]:
        raise RuntimeError("Entry price market identity changed")
    observed = parse_time(event["observed_at"])
    issued = parse_time(row["issued_at"])
    kickoff = parse_time(p["kickoff_utc"])
    if not (issued <= observed < kickoff):
        raise RuntimeError("Reference quote not observed after issue and before kickoff")
    try:
        price = Decimal(event["price_dollars"])
    except (InvalidOperation, TypeError):
        raise RuntimeError("Invalid reference price") from None
    if not price.is_finite() or not 0 < price < 1:
        raise RuntimeError("Reference quote outside valid range")
    return price


def gross_paper_performance(rows):
    """Returns gross, before-fee estimate for priced graded bets only."""
    total = Decimal(0)
    staked = Decimal(0)
    returns = Decimal(0)
    gross = Decimal(0)
    graded = 0
    priced = 0
    missing = 0
    pending = 0
    seen = set()
    for row in rows:
        p = row["prediction"]
        fixture = p["fixture_id"]
        if fixture in seen:
            raise RuntimeError("Duplicate fixture in aggregate")
        seen.add(fixture)
        grade = row["grade"]
        if grade.get("status") != "graded":
            pending += 1
            continue
        if grade.get("result") not in ("WIN", "LOSS") or grade.get("correct") is not (grade["result"] == "WIN"):
            raise RuntimeError("Invalid settled result")
        graded += 1
        price = validated_reference(row)
        if price is None:
            missing += 1
            continue
        priced += 1
        staked += STAKE
        win_return = STAKE / price if grade["result"] == "WIN" else Decimal(0)
        returns += win_return
        gross += win_return - STAKE
    if priced != graded - missing:
        raise RuntimeError("Unbalanced priced sample")
    def money(v):
        return str(v.quantize(Decimal(".01"), rounding=ROUND_HALF_UP))
    return {
        "graded": graded, "priced": priced, "unpriced": missing, "pending": pending,
        "stake_dollars": money(staked), "gross_returns_dollars": money(returns),
        "gross_profit_dollars": money(gross) if priced else None,
        "gross_roi_percent": float(gross / staked * 100) if priced else None,
        "net_profit_dollars": None, "net_roi_percent": None,
        "fee_status": "not_verified",
        "basis": "Fixed $10 indicative quote at initial capture; no verified fills, liquidity, fees or slippage",
    }


def paper_line(stats):
    if not stats["priced"]:
        return f'N/A (no verified entry prices; {stats["unpriced"]} graded without quotes)'
    return (f'Gross {stats["gross_profit_dollars"]} USD | Gross ROI '
            f'{stats["gross_roi_percent"]:.1f}% | $' + stats["stake_dollars"] +
            f' staked | {stats["priced"]}/{stats["graded"]} graded priced'
            + (f' ({stats["unpriced"]} unpriced excluded)' if stats["unpriced"] else "")
            + ' · before fees, no fills')
