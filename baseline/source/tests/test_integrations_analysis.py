from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from apps.integrations.analysis import Attribution, Evidence, EvidenceKind, analyze_roi
from apps.integrations.capabilities import classify_ai_connection

START, END = date(2026, 9, 1), date(2026, 10, 1)


def approval():
    return Attribution("invoice-entry", "owner-1", "approval-1", "USD", START, END)


def samples():
    values = {
        "tool_cost": ("100", "USD"),
        "implementation_cost": ("20", "USD"),
        "baseline_hours": ("10", "hours"),
        "current_hours": ("4", "hours"),
        "loaded_hourly_rate": ("25", "USD/hour"),
    }
    return tuple(
        Evidence(
            k,
            "qbo:company-1",
            k,
            Decimal(v),
            u,
            START,
            END,
            EvidenceKind.MEASURED,
            "a" * 64,
        )
        for k, (v, u) in values.items()
    )


def test_period_roi_uses_attributed_delta_and_all_costs():
    result = analyze_roi(approval(), samples())
    assert result["status"] == "measured_inputs"
    assert result["net_value"] == "30.00"
    assert result["roi_percent"] == "25.00"
    assert result["excluded_optional_benefits"] == [
        "attributable_revenue",
        "avoided_cost",
    ]


@pytest.mark.parametrize(
    "metric",
    [
        "tool_cost",
        "implementation_cost",
        "baseline_hours",
        "current_hours",
        "loaded_hourly_rate",
    ],
)
def test_missing_data_never_becomes_positive_roi(metric):
    result = analyze_roi(approval(), tuple(e for e in samples() if e.metric != metric))
    assert result["status"] == "insufficient_evidence"
    assert result["roi_percent"] is None
    assert result["missing_metrics"] == [metric]
    assert result["action_cards"][0]["approval_required"]


def test_estimates_are_explicit():
    data = samples()
    result = analyze_roi(
        approval(), (replace(data[0], kind=EvidenceKind.ESTIMATED), *data[1:])
    )
    assert result["status"] == "modeled"
    assert result["assumptions"] == ["tool_cost"]
    assert result["action_cards"][0]["code"] == "validate_roi_assumptions"


def test_same_evidence_is_not_double_counted():
    assert analyze_roi(approval(), samples() * 2) == analyze_roi(approval(), samples())


@pytest.mark.parametrize(
    "change", [{"value": Decimal(200)}, {"reference": "other-payment"}]
)
def test_conflicting_or_unreconciled_evidence_is_rejected(change):
    with pytest.raises(ValueError):
        analyze_roi(approval(), (*samples(), replace(samples()[0], **change)))


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "EUR"},
        {"period_end": date(2026, 11, 1)},
        {"metric": "profit_guarantee"},
    ],
)
def test_incompatible_evidence_is_rejected(change):
    with pytest.raises(ValueError):
        analyze_roi(approval(), (replace(samples()[0], **change), *samples()[1:]))


def test_worse_workflow_keeps_negative_time_difference():
    data = tuple(
        replace(e, value=Decimal(12)) if e.metric == "current_hours" else e
        for e in samples()
    )
    result = analyze_roi(approval(), data)
    assert result["hours_difference"] == "-2"
    assert result["net_value"] == "-170.00"
    assert result["action_cards"][0]["execution_status"] == "proposal_only"


def test_zero_cost_does_not_produce_infinite_roi():
    data = tuple(
        replace(e, value=Decimal(0))
        if e.metric in {"tool_cost", "implementation_cost"}
        else e
        for e in samples()
    )
    assert analyze_roi(approval(), data)["roi_percent"] is None


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal(-1), 1.0])
def test_invalid_values_are_rejected(bad):
    with pytest.raises(ValueError):
        replace(samples()[0], value=bad)


def test_grant_does_not_claim_ai_usage_or_savings():
    result = classify_ai_connection(
        application_id="app-1",
        observed_grant=True,
        reviewed_ai_catalog={
            "app-1": {"product_id": "known-ai-product", "reference": "catalog-1"}
        },
    )
    assert result["connection_status"] == "permission_grant_observed"
    assert result["ai_feature_enabled"] == "unknown"
    assert result["actual_usage"] == "unknown"
    assert result["realized_roi"] == "not_established"


def test_unknown_app_identity_stays_unknown():
    result = classify_ai_connection(
        application_id="unknown-app", observed_grant=True, reviewed_ai_catalog={}
    )
    assert result["ai_capability_status"] == "unknown"


def test_decimal_context_cannot_change_calculation():
    from decimal import localcontext

    expected = analyze_roi(approval(), samples())
    with localcontext() as ctx:
        ctx.prec = 3
        actual = analyze_roi(approval(), samples())
    assert actual == expected


def test_order_and_repeated_delivery_preserve_receipt_hashes():
    expected = analyze_roi(approval(), samples())
    assert analyze_roi(approval(), tuple(reversed(samples())) * 2) == expected
    assert len(expected["input_sha256"]) == 64
    assert len(expected["result_sha256"]) == 64


def test_changed_evidence_changes_receipt():
    expected = analyze_roi(approval(), samples())
    changed = analyze_roi(
        approval(), (replace(samples()[0], value=Decimal(101)), *samples()[1:])
    )
    assert changed["input_sha256"] != expected["input_sha256"]
    assert changed["result_sha256"] != expected["result_sha256"]


@pytest.mark.parametrize(
    "bad", [Decimal("1e100"), Decimal("1e-100"), Decimal("0e99999")]
)
def test_unbounded_decimal_inputs_are_rejected(bad):
    with pytest.raises(ValueError):
        replace(samples()[0], value=bad)
