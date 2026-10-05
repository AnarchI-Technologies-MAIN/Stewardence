"""Unknown-aware calculations. AL-ROI-1 remains available for historical replay."""
from dataclasses import dataclass, fields
from decimal import Decimal

from .engine import AssumptionProvenance, ROIInputs, _money, PERCENT_UNIT, ROUND_HALF_UP, calculate_roi as legacy_calculate

ROI_ENGINE_VERSION = "AL-ROI-2"


@dataclass(frozen=True)
class ROIResult:
    engine_version: str
    inputs: ROIInputs
    monthly_labor_value: Decimal | None
    monthly_value: Decimal | None
    amortized_implementation_cost: Decimal | None
    monthly_total_cost: Decimal | None
    monthly_net_value: Decimal | None
    roi_percent: Decimal | None
    arithmetic: tuple[str, ...]
    unknown_inputs: tuple[str, ...]
    roi_unavailable_reason: str | None


def calculate_roi(inputs: ROIInputs) -> ROIResult:
    unknown = tuple(field.name for field in fields(inputs)
                    if getattr(inputs, field.name).provenance is AssumptionProvenance.UNKNOWN)

    def admitted(name):
        assumption = getattr(inputs, name)
        if name in unknown:
            return None
        value = Decimal(assumption.value)
        if name in {"hours_saved_per_month", "implementation_amortization_months"}:
            return value
        return _money(value)

    def sum_known(*values):
        if any(value is None for value in values):
            return None
        return _money(sum(values))

    hours = admitted("hours_saved_per_month")
    rate = admitted("loaded_hourly_rate")
    labor = None if hours is None or rate is None else _money(hours * _money(rate))
    implementation = admitted("implementation_cost")
    months = admitted("implementation_amortization_months")
    amortized = None if implementation is None or months is None else _money(_money(implementation) / months)
    value = sum_known(labor, admitted("attributable_revenue"), admitted("avoided_monthly_cost"))
    cost = sum_known(admitted("monthly_subscription_cost"), amortized)
    net = None if value is None or cost is None else _money(value - cost)
    reason = "Required assumptions are unknown" if net is None else None
    if cost == 0 and net is not None:
        reason = "Monthly total cost is zero"
    percent = None if reason else (net / cost * Decimal(100)).quantize(PERCENT_UNIT, ROUND_HALF_UP)

    def display(amount):
        return "Unknown" if amount is None else f"${amount}"

    arithmetic = (
        f"Monthly labor value: {display(labor)}",
        f"Monthly implementation cost: {display(amortized)}",
        f"Monthly value: {display(value)}",
        f"Monthly total cost: {display(cost)}",
        f"Monthly net value: {display(net)}",
        f"ROI: {reason}" if reason else f"ROI: {percent}%",
    )
    if not unknown:
        arithmetic = legacy_calculate(inputs).arithmetic
    return ROIResult(ROI_ENGINE_VERSION, inputs, labor, value, amortized, cost, net,
                     percent, arithmetic, unknown, reason)
