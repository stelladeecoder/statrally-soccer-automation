"""Descriptive model probability is distinct from validated selection eligibility."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

from m13_beta_signals import parse_time
from prediction_schema import canonical, probability

REQUIRED_CONDITIONS = frozenset(("accuracy_above_prevalence", "no_precision", "no_recall", "brier", "log_loss",
    "calibration", "test_sample", "calibration_sample", "both_sides", "coverage", "high_confidence",
    "paired_accuracy_evidence", "high_confidence_stability", "stability", "data_quality",
    "fresh_forward_evidence", "regression_and_leakage_checks"))

POLICY_PATH = Path(__file__).resolve().parents[1]/"config/prediction_selection_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text())


def describe_probability(confidence):
    p = probability(confidence)
    if p < Decimal(".5"):
        raise ValueError("Selected-side probability must be at least one half")
    if p < Decimal(".55"):return "Low confidence"
    if p < Decimal(".60"):return "Moderate confidence"
    if p < Decimal(".70"):return "Higher model probability"
    return "Very high model probability"



STAR_THRESHOLD = Decimal("0.70")


def is_starred_probability(prediction):
    """Descriptive 70%+ marker only; not calibrated reliability or bet approval."""
    return probability(prediction["confidence"]) >= STAR_THRESHOLD


def policy_valid(policy):
    required = {"schema_version","policy_version","descriptive_minimum","maximum_selections",
        "minimum_validation_observations","maximum_calibration_ece","minimum_validated_coverage",
        "required_conditions","approved_policies","note"}
    return (isinstance(policy,dict) and set(policy)==required and policy["schema_version"]==1
        and isinstance(policy["policy_version"],str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}",policy["policy_version"]) is not None
        and policy["descriptive_minimum"]=="0.55" and policy["maximum_selections"]==3
        and type(policy["minimum_validation_observations"]) is int and policy["minimum_validation_observations"]>=200
        and type(policy["maximum_calibration_ece"]) in (float,int) and 0<=policy["maximum_calibration_ece"]<=.08
        and type(policy["minimum_validated_coverage"]) in (float,int) and .1<=policy["minimum_validated_coverage"]<=1
        and isinstance(policy["approved_policies"],list) and isinstance(policy["required_conditions"],list)
        and len(policy["required_conditions"])==17 and set(policy["required_conditions"])==REQUIRED_CONDITIONS)


def classify(prediction, policy=None, *, now=None):
    policy = load_policy() if policy is None else policy
    confidence = probability(prediction["confidence"])
    reasons = []
    if confidence < Decimal(".55"):reasons.append("below_descriptive_screen")
    if prediction.get("probabilities_calibrated") is not True:reasons.append("uncalibrated")
    if prediction.get("data_quality_status") != "verified":reasons.append("unverified_data_quality")
    approved = None
    if not policy_valid(policy):
        reasons.append("selection_policy_invalid")
    else:
        for rule in policy["approved_policies"]:
            keys = {"approval_id","model_version","league","side","minimum_probability","observations","ece","coverage",
                    "deployment_gate_passed","fresh_forward_evidence","passed_conditions","threshold_selected_on",
                    "selection_end","approved_at","valid_until","evidence_sha256","calibration_method"}
            try:
                if not isinstance(rule,dict) or set(rule)!=keys:continue
                if (rule["model_version"],rule["league"],rule["side"]) != (prediction["model_version"],prediction["league"],prediction["side"]):continue
                cutoff = probability(rule["minimum_probability"])
                if not Decimal(".55") <= cutoff <= confidence:continue
                if (rule["deployment_gate_passed"] is not True or rule["fresh_forward_evidence"] is not True
                    or set(rule["passed_conditions"])!=set(policy["required_conditions"])
                    or rule["threshold_selected_on"]!="validation" or rule["calibration_method"] not in {"sigmoid","isotonic"}
                    or type(rule["observations"]) is not int or rule["observations"]<policy["minimum_validation_observations"]
                    or type(rule["ece"]) not in (float,int) or not 0<=rule["ece"]<=policy["maximum_calibration_ece"]
                    or type(rule["coverage"]) not in (float,int) or not policy["minimum_validated_coverage"]<=rule["coverage"]<=1
                    or not re.fullmatch(r"[a-f0-9]{64}",rule["evidence_sha256"])):continue
                created = parse_time(prediction["created_at"])
                if not parse_time(rule["selection_end"])<parse_time(rule["approved_at"])<=created:continue
                if parse_time(rule["valid_until"])<=max(parse_time(prediction["kickoff_utc"]),now or created):continue
                approved = rule["approval_id"]
                break
            except (KeyError,TypeError,ValueError,ArithmeticError):continue
        if approved is None:reasons.append("no_applicable_validated_policy")
    eligible = not reasons and approved is not None
    return {"probability_category":describe_probability(prediction["confidence"]),
            "category_is_validated_reliability":False,
            "calibration_status":"calibrated_model_output" if prediction.get("probabilities_calibrated") is True else "uncalibrated",
            "selection_eligible":eligible,"selection_status":"validated_policy_eligible" if eligible else "experimental_forecast",
            "selection_reasons":reasons,"approval_id":approved if eligible else None,
            "policy_version":policy.get("policy_version","invalid") if isinstance(policy,dict) else "invalid"}


def policy_digest(policy):
    return sha256(canonical(policy).encode()).hexdigest()


def eligible_ranked(items, policy=None, *, now=None):
    policy = load_policy() if policy is None else policy
    candidates = [r for r in items if classify(r["prediction"],policy,now=now)["selection_eligible"]]
    return sorted(candidates,key=lambda r:(-probability(r["prediction"]["confidence"]),r["prediction"]["fixture_id"]))
