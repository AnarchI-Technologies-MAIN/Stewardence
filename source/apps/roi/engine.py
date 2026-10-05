from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

ROI_ENGINE_VERSION = "AL-ROI-1"
MONEY_UNIT = Decimal("0.01")
PERCENT_UNIT = Decimal("0.01")


class ROIInputError(ValueError):
    pass


class AssumptionProvenance(str, Enum):
    MEASURED = "Measured"
    CUSTOMER_SUPPLIED = "Customer supplied"
    ESTIMATED = "Estimated"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class Assumption:
    value: Decimal | int
    provenance: AssumptionProvenance

    def __post_init__(self):
        if isinstance(self.value, bool) or not isinstance(self.value, (Decimal, int)):
            raise ROIInputError("Assumption values must be Decimal or integer values")
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ROIInputError("Assumption values must be finite")
        if self.value < 0:
            raise ROIInputError("Assumption values cannot be negative")
        if not isinstance(self.provenance, AssumptionProvenance):
            raise ROIInputError("Every assumption requires an approved provenance")
        if self.provenance is AssumptionProvenance.UNKNOWN and self.value != 0:
            raise ROIInputError("Unknown assumptions must use a zero value")


@dataclass(frozen=True)
class ROIInputs:
    monthly_subscription_cost: Assumption
    implementation_cost: Assumption
    implementation_amortization_months: Assumption
    hours_saved_per_month: Assumption
    loaded_hourly_rate: Assumption
    attributable_revenue: Assumption
    avoided_monthly_cost: Assumption

    def __post_init__(self):
        if not all(
            isinstance(getattr(self, field.name), Assumption) for field in fields(self)
        ):
            raise ROIInputError("Every ROI input requires a value and provenance")
        months = self.implementation_amortization_months.value
        if not isinstance(months, int) or isinstance(months, bool) or months <= 0:
            raise ROIInputError("Implementation amortization months must be positive")


@dataclass(frozen=True)
class ROIResult:
    engine_version: str
    inputs: ROIInputs
    monthly_labor_value: Decimal
    monthly_value: Decimal
    amortized_implementation_cost: Decimal
    monthly_total_cost: Decimal
    monthly_net_value: Decimal
    roi_percent: Decimal | None
    arithmetic: tuple[str, ...]


def _money(value: Decimal | int) -> Decimal:
    return Decimal(value).quantize(MONEY_UNIT, ROUND_HALF_UP)


def calculate_roi(inputs: ROIInputs) -> ROIResult:
    subscription = _money(inputs.monthly_subscription_cost.value)
    implementation = _money(inputs.implementation_cost.value)
    months = inputs.implementation_amortization_months.value
    hours = Decimal(inputs.hours_saved_per_month.value)
    hourly_rate = _money(inputs.loaded_hourly_rate.value)
    revenue = _money(inputs.attributable_revenue.value)
    avoided_cost = _money(inputs.avoided_monthly_cost.value)

    monthly_labor_value = _money(hours * hourly_rate)
    amortized_implementation_cost = _money(implementation / Decimal(months))
    monthly_value = _money(monthly_labor_value + revenue + avoided_cost)
    monthly_total_cost = _money(subscription + amortized_implementation_cost)
    monthly_net_value = _money(monthly_value - monthly_total_cost)
    roi_percent = None
    if monthly_total_cost != 0:
        roi_percent = (monthly_net_value / monthly_total_cost * Decimal(100)).quantize(
            PERCENT_UNIT,
            ROUND_HALF_UP,
        )

    arithmetic = (
        f"Monthly labor value: {hours} hours × ${hourly_rate} = ${monthly_labor_value}",
        (
            f"Monthly value: ${monthly_labor_value} labor + ${revenue} revenue + "
            f"${avoided_cost} avoided cost = ${monthly_value}"
        ),
        (
            f"Monthly implementation cost: ${implementation} ÷ {months} months "
            f"= ${amortized_implementation_cost}"
        ),
        (
            f"Monthly total cost: ${subscription} subscription + "
            f"${amortized_implementation_cost} implementation = "
            f"${monthly_total_cost}"
        ),
        (
            f"Monthly net value: ${monthly_value} value - ${monthly_total_cost} "
            f"cost = ${monthly_net_value}"
        ),
        (
            f"ROI: ${monthly_net_value} ÷ ${monthly_total_cost} × 100 = {roi_percent}%"
            if roi_percent is not None
            else "ROI: Not available because monthly total cost is $0.00"
        ),
    )

    return ROIResult(
        engine_version=ROI_ENGINE_VERSION,
        inputs=inputs,
        monthly_labor_value=monthly_labor_value,
        monthly_value=monthly_value,
        amortized_implementation_cost=amortized_implementation_cost,
        monthly_total_cost=monthly_total_cost,
        monthly_net_value=monthly_net_value,
        roi_percent=roi_percent,
        arithmetic=arithmetic,
    )
