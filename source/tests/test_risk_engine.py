from __future__ import annotations

from decimal import Decimal

import pytest

from apps.policies.engine import (
    SUPPORTED_RISK_DIMENSIONS,
    Condition,
    Effect,
    PolicyResult,
    Rule,
    RuleLayer,
    Severity,
    evaluate_policies,
)
from apps.policies.packs.accounting import ACCOUNTING_RISK_PACK_V1
from apps.policies.risk import (
    DEFAULT_RISK_CONFIGURATION,
    RISK_ENGINE_VERSION,
    RiskBand,
    RiskConfiguration,
    RiskContribution,
    RiskDefinitionError,
    RiskDimension,
    calculate_policy_risk,
    calculate_risk,
    classify_risk,
)


def contribution(dimension, points, rule_id="RULE-1"):
    return RiskContribution(
        reason="Recorded assessment evidence supports this contribution.",
        rule_id=rule_id,
        rule_version="1.0.0",
        dimension=dimension,
        points=points,
    )


def test_default_configuration_matches_all_eight_approved_weights():
    assert DEFAULT_RISK_CONFIGURATION.version == RISK_ENGINE_VERSION
    assert DEFAULT_RISK_CONFIGURATION.weights == (
        (RiskDimension.DATA_SENSITIVITY, 20),
        (RiskDimension.SYSTEM_PRIVILEGE, 20),
        (RiskDimension.AUTONOMY, 15),
        (RiskDimension.EXTERNAL_CONNECTIVITY, 15),
        (RiskDimension.HUMAN_OVERSIGHT, 10),
        (RiskDimension.FINANCIAL_IMPACT, 10),
        (RiskDimension.REGULATORY_RELEVANCE, 5),
        (RiskDimension.VENDOR_RISK, 5),
    )
    assert (
        sum(weight for _dimension, weight in DEFAULT_RISK_CONFIGURATION.weights) == 100
    )
    assert {dimension.value for dimension in RiskDimension} == (
        SUPPORTED_RISK_DIMENSIONS
    )


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0, RiskBand.LOW),
        (24, RiskBand.LOW),
        (25, RiskBand.MODERATE),
        (49, RiskBand.MODERATE),
        (50, RiskBand.HIGH),
        (74, RiskBand.HIGH),
        (75, RiskBand.CRITICAL),
        (100, RiskBand.CRITICAL),
    ],
)
def test_severity_bands_match_the_approved_boundaries(score, expected):
    assert classify_risk(score) is expected


def test_weighted_sum_is_exact_and_each_dimension_is_clamped_to_zero_through_100():
    result = calculate_risk(
        (
            contribution(RiskDimension.DATA_SENSITIVITY, 120, "DATA"),
            contribution(RiskDimension.SYSTEM_PRIVILEGE, 50, "PRIVILEGE"),
            contribution(RiskDimension.AUTONOMY, -20, "AUTONOMY"),
            contribution(RiskDimension.EXTERNAL_CONNECTIVITY, 40, "EXTERNAL"),
        )
    )

    breakdown = {item.dimension: item for item in result.dimensions}
    assert breakdown[RiskDimension.DATA_SENSITIVITY].raw_points == 120
    assert breakdown[RiskDimension.DATA_SENSITIVITY].score == 100
    assert breakdown[RiskDimension.AUTONOMY].score == 0
    assert result.raw_weighted_score == Decimal("36")
    assert result.score == 36
    assert result.band is RiskBand.MODERATE


def test_half_points_round_deterministically_away_from_zero():
    result = calculate_risk((contribution(RiskDimension.AUTONOMY, 30),))

    assert result.raw_weighted_score == Decimal("4.5")
    assert result.score == 5


@pytest.mark.parametrize(
    ("floor", "minimum"),
    [
        (RiskBand.LOW, 0),
        (RiskBand.MODERATE, 25),
        (RiskBand.HIGH, 50),
        (RiskBand.CRITICAL, 75),
    ],
)
def test_severity_floors_raise_the_numeric_score_to_the_band_minimum(floor, minimum):
    result = calculate_risk((), (floor,))

    assert result.score == minimum
    assert result.band is floor
    assert result.severity_floor is floor


def test_policy_effects_produce_traceable_contributions_and_critical_floor():
    context = {
        "data_categories": ["financial_records"],
        "capabilities": [
            "financial_transaction",
            "record_modification",
            "data_export",
            "communication",
        ],
        "connected_systems": ["banking"],
        "permissions": ["write"],
        "autonomy_level": 4,
        "human_approval": False,
        "vendor_review_status": "complete",
        "retention_status": "documented",
        "training_behavior": "not_used",
    }
    evaluation = evaluate_policies(ACCOUNTING_RISK_PACK_V1.rules, context)

    result = calculate_policy_risk(evaluation)

    assert result.score >= 75
    assert result.band is RiskBand.CRITICAL
    assert result.severity_floor is RiskBand.CRITICAL
    assert result.contributions
    assert all(
        item.reason
        and item.rule_id.startswith("ACC-")
        and item.rule_version == "1.1.0"
        and isinstance(item.dimension, RiskDimension)
        and isinstance(item.points, int)
        for item in result.contributions
    )
    assert all(line.startswith("+") for line in result.explanation_lines)
    assert all(" v1.1.0)" in line for line in result.explanation_lines)


def test_mandatory_platform_rule_applies_its_risk_floor_deterministically():
    rule = Rule(
        rule_id="PLATFORM-MANDATORY-1",
        version="1.0.0",
        layer=RuleLayer.MANDATORY_PLATFORM,
        conditions=(Condition("human_approval", "is_false"),),
        effects=(Effect("severity_floor", value="CRITICAL"),),
        result_on_match=PolicyResult.FAIL,
        explanation="An important action has no recorded approval step.",
        severity=Severity.CRITICAL,
        remediation="Record a required approval step.",
    )
    evaluation = evaluate_policies((rule,), {"human_approval": False})

    first = calculate_policy_risk(evaluation)
    second = calculate_policy_risk(evaluation)

    assert first == second
    assert first.score == 75
    assert first.band is RiskBand.CRITICAL


def test_dimension_arithmetic_explains_every_weighted_component():
    result = calculate_risk((contribution(RiskDimension.DATA_SENSITIVITY, 25),))

    assert result.dimensions[0].arithmetic == "Data Sensitivity: 25 × 20% = 5"
    assert len(result.dimensions) == 8


def test_invalid_configurations_and_inputs_fail_closed():
    with pytest.raises(RiskDefinitionError, match="immutable tuple"):
        RiskConfiguration("mutable", list(DEFAULT_RISK_CONFIGURATION.weights))
    with pytest.raises(RiskDefinitionError, match="each dimension exactly once"):
        RiskConfiguration("missing", ((RiskDimension.DATA_SENSITIVITY, 100),))
    with pytest.raises(RiskDefinitionError, match="total 100"):
        RiskConfiguration(
            "bad-total", tuple((dimension, 1) for dimension in RiskDimension)
        )
    with pytest.raises(RiskDefinitionError, match="0 to 100"):
        classify_risk(101)
    with pytest.raises(RiskDefinitionError, match="immutable tuple"):
        calculate_risk([])
