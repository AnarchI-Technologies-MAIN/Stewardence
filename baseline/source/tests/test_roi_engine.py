from __future__ import annotations

import ast
import inspect
from decimal import Decimal

import pytest

from apps.roi import engine
from apps.roi.engine import (
    ROI_ENGINE_VERSION,
    Assumption,
    AssumptionProvenance,
    ROIInputError,
    ROIInputs,
    calculate_roi,
)


def known(value, provenance=AssumptionProvenance.CUSTOMER_SUPPLIED):
    return Assumption(Decimal(str(value)), provenance)


def roi_inputs(**overrides):
    values = {
        "monthly_subscription_cost": known("100.00"),
        "implementation_cost": known("1200.00"),
        "implementation_amortization_months": Assumption(
            12, AssumptionProvenance.CUSTOMER_SUPPLIED
        ),
        "hours_saved_per_month": known("10.00", AssumptionProvenance.MEASURED),
        "loaded_hourly_rate": known("50.00"),
        "attributable_revenue": known("200.00", AssumptionProvenance.ESTIMATED),
        "avoided_monthly_cost": known("100.00", AssumptionProvenance.MEASURED),
    }
    values.update(overrides)
    return ROIInputs(**values)


def test_approved_roi_inputs_and_provenance_are_explicit():
    inputs = roi_inputs()

    assert {item.value for item in AssumptionProvenance} == {
        "Measured",
        "Customer supplied",
        "Estimated",
        "Unknown",
    }
    assert inputs.monthly_subscription_cost.value == Decimal("100.00")
    assert inputs.implementation_cost.value == Decimal("1200.00")
    assert inputs.hours_saved_per_month.provenance is AssumptionProvenance.MEASURED
    assert inputs.loaded_hourly_rate.value == Decimal("50.00")
    assert inputs.attributable_revenue.value == Decimal("200.00")
    assert inputs.avoided_monthly_cost.value == Decimal("100.00")


def test_roi_formulas_match_the_approved_baseline_exactly():
    result = calculate_roi(roi_inputs())

    assert result.engine_version == ROI_ENGINE_VERSION
    assert result.monthly_labor_value == Decimal("500.00")
    assert result.monthly_value == Decimal("800.00")
    assert result.amortized_implementation_cost == Decimal("100.00")
    assert result.monthly_total_cost == Decimal("200.00")
    assert result.monthly_net_value == Decimal("600.00")
    assert result.roi_percent == Decimal("300.00")


def test_every_result_exposes_calculator_reproducible_arithmetic():
    result = calculate_roi(roi_inputs())

    assert result.arithmetic == (
        "Monthly labor value: 10.00 hours × $50.00 = $500.00",
        (
            "Monthly value: $500.00 labor + $200.00 revenue + $100.00 "
            "avoided cost = $800.00"
        ),
        "Monthly implementation cost: $1200.00 ÷ 12 months = $100.00",
        "Monthly total cost: $100.00 subscription + $100.00 implementation = $200.00",
        "Monthly net value: $800.00 value - $200.00 cost = $600.00",
        "ROI: $600.00 ÷ $200.00 × 100 = 300.00%",
    )


def test_zero_total_cost_returns_not_available_instead_of_infinity():
    zero = Assumption(Decimal(0), AssumptionProvenance.UNKNOWN)
    result = calculate_roi(
        roi_inputs(
            monthly_subscription_cost=zero,
            implementation_cost=zero,
        )
    )

    assert result.monthly_total_cost == Decimal("0.00")
    assert result.roi_percent is None
    assert result.arithmetic[-1] == (
        "ROI: Not available because monthly total cost is $0.00"
    )
    assert "Infinity" not in " ".join(result.arithmetic)


def test_money_rounding_and_repeated_evaluation_are_deterministic():
    inputs = roi_inputs(
        implementation_cost=known("100.00"),
        implementation_amortization_months=Assumption(
            3, AssumptionProvenance.ESTIMATED
        ),
    )

    first = calculate_roi(inputs)
    second = calculate_roi(inputs)

    assert first == second
    assert first.amortized_implementation_cost == Decimal("33.33")


@pytest.mark.parametrize(
    "assumption",
    [
        lambda: Assumption(Decimal("-0.01"), AssumptionProvenance.MEASURED),
        lambda: Assumption(Decimal("NaN"), AssumptionProvenance.MEASURED),
        lambda: Assumption(Decimal("1.00"), AssumptionProvenance.UNKNOWN),
        lambda: Assumption(Decimal("1.00"), "Measured"),
    ],
)
def test_invalid_assumptions_fail_closed(assumption):
    with pytest.raises(ROIInputError):
        assumption()


def test_zero_amortization_period_fails_closed():
    with pytest.raises(ROIInputError, match="must be positive"):
        roi_inputs(
            implementation_amortization_months=Assumption(
                0, AssumptionProvenance.CUSTOMER_SUPPLIED
            )
        )


def test_roi_engine_has_no_database_network_clock_or_llm_dependency():
    source = inspect.getsource(engine)
    tree = ast.parse(source)
    imported_roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert imported_roots <= {"__future__", "dataclasses", "decimal", "enum"}
    assert all(
        forbidden not in source
        for forbidden in (
            "django.db",
            "requests",
            "httpx",
            "socket",
            "datetime.now",
            "time.time",
            "openai",
            "eval(",
            "exec(",
        )
    )
