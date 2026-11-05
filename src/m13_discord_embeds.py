"""Compact native Discord presentation; no prediction or grading decisions."""
from datetime import datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
PICK_COLOR, WIN_COLOR, LOSS_COLOR, NEUTRAL_COLOR = 0x3498DB, 0x2ECC71, 0xE74C3C, 0x95A5A6
# Keep legacy names for existing integrations; prediction cards are blue for either side.
YES_COLOR = NO_COLOR = PICK_COLOR
COMPETITIONS = {
    "epl": "Premier League", "bundesliga": "Bundesliga", "laliga": "La Liga",
    "serie_a": "Serie A", "ligue_1": "Ligue 1", "eredivisie": "Eredivisie",
    "liga_portugal": "Liga Portugal", "brasileirao": "Brasileirão Série A",
    "mls": "MLS", "liga_mx": "Liga MX", "primera_lpf": "Argentina Primera División",
    "champions_league": "UEFA Champions League", "europa_league": "UEFA Europa League",
}


def units(text):
    return len(text.encode("utf-16-le")) // 2


def plain(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Display text required")
    return " ".join(text.split())


def markdown(text):
    return re.sub(r"([\\*_~`|\[\]<>])", r"\\\1", plain(text))


def clip(text, limit):
    if units(text) <= limit:
        return text
    result = ""
    for char in text:
        if units(result + char + "…") > limit:
            return result + "…"
        result += char
    return text


def local_time(stamp):
    value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Aware kickoff required")
    return value.astimezone(CENTRAL)


def clock(value):
    return value.strftime("%I:%M %p").lstrip("0")


def side_style(side):
    if side not in ("YES", "NO"):
        raise ValueError("BTTS side required")
    return (PICK_COLOR, "🔵 BTTS YES") if side == "YES" else (PICK_COLOR, "🔵 BTTS NO")


def embed_units(embed):
    return sum(units(text) for text in [embed.get("title", ""), embed.get("description", ""),
        embed.get("footer", {}).get("text", "")] +
        [value for field in embed.get("fields", []) for value in (field["name"], field["value"])])


def validate_payload(payload):
    if not isinstance(payload, dict) or set(payload) - {"content", "embeds", "allowed_mentions"}:
        raise ValueError("Unreviewed Discord payload fields")
    content, embeds = payload.get("content", ""), payload.get("embeds", [])
    if not isinstance(content, str) or units(content) > 2000 or not isinstance(embeds, list) or len(embeds) > 10:
        raise ValueError("Discord message limit exceeded")
    if not content.strip() and not embeds:
        raise ValueError("Empty Discord message")
    if payload.get("allowed_mentions", {"parse": []}) != {"parse": []}:
        raise ValueError("Discord mentions must be disabled")
    for embed in embeds:
        if not isinstance(embed, dict) or set(embed) - {"title", "description", "color", "fields", "footer"}:
            raise ValueError("Unreviewed embed fields")
        for key, limit in (("title", 256), ("description", 4096)):
            if key in embed and (not isinstance(embed[key], str) or not embed[key].strip() or units(embed[key]) > limit):
                raise ValueError("Discord embed text limit exceeded")
        if type(embed.get("color")) is not int or not 0 <= embed["color"] <= 0xFFFFFF:
            raise ValueError("Invalid embed accent")
        footer = embed.get("footer", {})
        if not isinstance(footer, dict) or set(footer) - {"text"} or not isinstance(footer.get("text", ""), str) or units(footer.get("text", "")) > 2048:
            raise ValueError("Discord footer limit exceeded")
        fields = embed.get("fields", [])
        if not isinstance(fields, list) or len(fields) > 25:
            raise ValueError("Discord field limit exceeded")
        if not embed.get("title") and not embed.get("description") and not fields:
            raise ValueError("Empty Discord embed")
        for field in fields:
            if not isinstance(field, dict) or set(field) - {"name", "value", "inline"}:
                raise ValueError("Unreviewed embed field")
            for key, limit in (("name", 256), ("value", 1024)):
                if not isinstance(field.get(key), str) or not field[key].strip() or units(field[key]) > limit:
                    raise ValueError("Discord field text limit exceeded")
            if "inline" in field and type(field["inline"]) is not bool:
                raise ValueError("Invalid field layout")
    if sum(embed_units(embed) for embed in embeds) > 6000:
        raise ValueError("Discord aggregate embed limit exceeded")
    return payload


def payload_text(payload):
    """Readable durable Issue/legacy-test summary, independent of signal hashes."""
    lines = [payload.get("content", "")]
    for embed in payload.get("embeds", []):
        lines.extend([embed.get("title", ""), embed.get("description", "")])
        lines.extend(field["name"] + ": " + field["value"] for field in embed.get("fields", []))
        lines.append(embed.get("footer", {}).get("text", ""))
    return "\n".join(line for line in lines if line)


def match_card(signal, footer):
    title = plain(signal["home_team"]) + " vs " + plain(signal["away_team"])
    when = local_time(signal["kickoff_utc"])
    description = markdown(COMPETITIONS.get(signal.get("league"), "Competition unavailable"))
    description += " · " + when.strftime("%a, %b %d, %Y").replace(" 0", " ")
    short = clip(title, 256)
    if short != title:
        description += "\n" + markdown(title)
    return {"title": short, "description": description, "color": side_style(signal["side"])[0],
            "footer": {"text": footer}}, when


def pick_card(signal):
    embed, when = match_card(signal, "Experimental paper pick")
    embed["description"] += " · " + clock(when) + " CT"
    probability = format(Decimal(str(signal["model_probability"])), ".1%").replace(".0%", "%")
    quote = format(Decimal(str(signal["market_price"])), "f")
    if "." in quote:
        quote = quote.rstrip("0").rstrip(".")
    if "." not in quote:
        quote += ".00"
    elif len(quote.rsplit(".", 1)[1]) == 1:
        quote += "0"
    provider = "Polymarket US" if signal["market_ticker"].startswith("astatc-") else "Kalshi"
    embed["fields"] = [
        {"name": "Prediction", "value": side_style(signal["side"])[1], "inline": True},
        {"name": "Model estimate", "value": probability, "inline": True},
        {"name": provider + " quote", "value": "$" + quote, "inline": True},
    ]
    return embed


def render_paper_result(signal, result):
    if result.get("status") != "graded":
        return None
    goals = result.get("home_goals"), result.get("away_goals")
    if any(type(value) is not int or value < 0 for value in goals):
        raise ValueError("Verified integer final score required")
    expected = "WIN" if (signal["side"] == "YES") == all(value > 0 for value in goals) else "LOSS"
    if result.get("result") != expected:
        raise ValueError("Result contradicts verified score and original side")
    embed, _ = match_card(signal, "Verified full-time · Paper result")
    embed["color"] = WIN_COLOR if expected == "WIN" else LOSS_COLOR
    embed["fields"] = [
        {"name": "Original prediction", "value": side_style(signal["side"])[1], "inline": True},
        {"name": "Outcome", "value": ("🟢 **WIN**" if expected == "WIN" else "🔴 **LOSS**"), "inline": True},
        {"name": "Final score", "value": f"{goals[0]}–{goals[1]}", "inline": True},
    ]
    return validate_payload({"content": "Experimental paper result · No financial P&L.",
                             "embeds": [embed], "allowed_mentions": {"parse": []}})


def watchlist_cards(day, groups, failed):
    fields = []
    for competition in sorted(groups):
        lines = [line for _, line in sorted(groups[competition])]
        value, continuation = "", False
        for line in lines:
            if units(line) > 1024:
                raise ValueError("Watchlist fixture exceeds Discord field limit")
            if value and units(value + "\n" + line) > 1024:
                fields.append({"name": plain(competition) + (" (continued)" if continuation else ""), "value": value, "inline": False})
                value, continuation = "", True
            value += ("\n" if value else "") + line
        if value:
            fields.append({"name": plain(competition) + (" (continued)" if continuation else ""), "value": value, "inline": False})
    title = day.strftime("%A") + " watchlist"
    description = day.strftime("%b %d, %Y").replace(" 0", " ") + " · All times Central"
    if not fields:
        description += "\nNo matches scheduled today. All configured feeds succeeded."
    if failed:
        description += "\nSchedule incomplete: unavailable feeds for " + ", ".join(markdown(value) for value in failed)
    base = {"title": title, "description": description, "color": NEUTRAL_COLOR,
            "footer": {"text": "Fixtures only · Not every match becomes a pick"}, "fields": []}
    cards, current = [], dict(base, fields=[])
    for field in fields:
        trial = dict(current, fields=current["fields"] + [field])
        if current["fields"] and (len(trial["fields"]) > 25 or embed_units(trial) > 5700):
            cards.append(current)
            current = dict(base, fields=[])
        current["fields"].append(field)
    cards.append(current)
    pages = []
    for index, card in enumerate(cards, 1):
        if len(cards) > 1:
            card["title"] += f" · {index}/{len(cards)}"
        pages.append(validate_payload({"embeds": [card], "allowed_mentions": {"parse": []}}))
    return pages
