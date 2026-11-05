"""Public forecast interface. Reject arbitrary private fields before persistence."""
from datetime import timezone
from decimal import Decimal
from hashlib import sha256
import json
from m13_beta_signals import parse_time
from m13_discord_embeds import CENTRAL, COMPETITIONS

STATUSES = {"predicted", "insufficient_history", "unresolved_team_identity", "missing_fixture_data", "model_error"}
MARKETS = {"verified_available", "not_found", "identity_mismatch", "market_closed", "provider_unavailable"}
BASE = {"fixture_id", "espn_event_id", "league", "home_team", "away_team", "espn_home_team_id", "espn_away_team_id",
        "kickoff_utc", "fixture_observed_at", "fixture_source", "prediction_status"}
FORECAST = BASE | {"p_yes", "p_no", "side", "confidence", "model_name", "model_version", "created_at", "history_coverage",
                   "identity_verified", "probabilities_calibrated", "data_quality_status", "baseline_yes_probability", "prediction_source"}
RECORD = FORECAST | {"prediction_id", "revision"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def probability(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Probability string required")
    p = Decimal(value)
    if not p.is_finite() or not 0 <= p <= 1:
        raise ValueError("Invalid probability")
    return p


def forecast_identity(record):
    semantic = {k: v for k, v in record.items() if k not in
                {"created_at", "fixture_observed_at", "prediction_id", "revision"}}
    return sha256(canonical(semantic).encode()).hexdigest()


def validate(record, *, stored=False):
    expected = RECORD if stored else FORECAST
    if not isinstance(record, dict) or set(record) != expected:
        raise ValueError("Unreviewed or missing forecast fields")
    if record["league"] not in COMPETITIONS or record["prediction_status"] != "predicted":
        raise ValueError("Supported successful prediction required")
    for field in ("espn_event_id", "espn_home_team_id", "espn_away_team_id"):
        value = record[field]
        if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 20:
            raise ValueError("Stable ESPN identity required")
    if record["espn_home_team_id"] == record["espn_away_team_id"] or record["fixture_id"] != f"espn:{record['league']}:{record['espn_event_id']}":
        raise ValueError("Fixture identity mismatch")
    for field, limit in (("home_team", 200), ("away_team", 200), ("model_name", 80), ("model_version", 100)):
        value = record[field]
        if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid public display field")
    if record["home_team"] == record["away_team"] or record["fixture_source"] != "ESPN scoreboard":
        raise ValueError("Independently verified fixture required")
    kickoff, created, observed = (parse_time(record[k]) for k in ("kickoff_utc", "created_at", "fixture_observed_at"))
    if not observed <= created < kickoff or created.astimezone(CENTRAL).date() != kickoff.astimezone(CENTRAL).date():
        raise ValueError("Forward same-day prematch observation required")
    yes, no, confidence = (probability(record[k]) for k in ("p_yes", "p_no", "confidence"))
    if abs(yes+no-1) > Decimal("1e-12") or record["side"] != ("YES" if yes >= Decimal(".5") else "NO") or abs(confidence-max(yes,no)) > Decimal("1e-12"):
        raise ValueError("Contradictory probabilities or selected outcome")
    if (record["model_name"] != "uncalibrated_rolling_poisson" or record["model_version"] != "rolling-poisson-10-v1"
            or record["probabilities_calibrated"] is not False or record["identity_verified"] is not True
            or record["prediction_source"] != "forward_recorded"
            or record["data_quality_status"] not in {"research_snapshot", "reviewed_domestic_proxy"}):
        raise ValueError("Unapproved model, identity, quality or historical replay")
    coverage = record["history_coverage"]
    if not isinstance(coverage, dict) or set(coverage) != {"minimum_matches_per_team", "home_matches_used", "away_matches_used", "latest_history_date", "source"}:
        raise ValueError("Reviewed aggregate history coverage required")
    if any(type(coverage[k]) is not int or coverage[k] != 10 for k in ("minimum_matches_per_team", "home_matches_used", "away_matches_used")):
        raise ValueError("Ten prior matches per team required")
    from datetime import date
    latest = date.fromisoformat(coverage["latest_history_date"])
    if latest >= min(created.astimezone(timezone.utc).date(), kickoff.astimezone(timezone.utc).date()):
        raise ValueError("Same-day or future historical result")
    if coverage["source"] not in {"same_competition", "reviewed_domestic_proxy"}:
        raise ValueError("Unreviewed historical source")
    if (coverage["source"] == "reviewed_domestic_proxy") != (record["data_quality_status"] == "reviewed_domestic_proxy"):
        raise ValueError("Historical quality annotation mismatch")
    if record["baseline_yes_probability"] is not None:
        probability(record["baseline_yes_probability"])
    if stored and (record["prediction_id"] != forecast_identity(record) or type(record["revision"]) is not int or record["revision"] < 1):
        raise ValueError("Invalid immutable forecast identity/revision")
    return record
