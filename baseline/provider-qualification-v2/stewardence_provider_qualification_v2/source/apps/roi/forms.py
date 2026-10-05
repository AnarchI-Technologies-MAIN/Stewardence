from __future__ import annotations

from decimal import Decimal

from django import forms

from .engine import Assumption, AssumptionProvenance, ROIInputs

PROVENANCE_CHOICES = tuple((item.value, item.value) for item in AssumptionProvenance)


def _provenance_field():
    return forms.ChoiceField(
        label="How do you know this amount?",
        choices=PROVENANCE_CHOICES,
    )


class ROIForm(forms.Form):
    monthly_subscription_cost = forms.DecimalField(
        label="Monthly subscription cost",
        min_value=Decimal(0),
        max_digits=12,
        decimal_places=2,
    )
    monthly_subscription_cost_provenance = _provenance_field()
    implementation_cost = forms.DecimalField(
        label="One-time implementation cost",
        min_value=Decimal(0),
        max_digits=12,
        decimal_places=2,
    )
    implementation_cost_provenance = _provenance_field()
    implementation_amortization_months = forms.IntegerField(
        label="Months used to spread the implementation cost",
        min_value=1,
        max_value=120,
    )
    implementation_amortization_months_provenance = _provenance_field()
    hours_saved_per_month = forms.DecimalField(
        label="Hours saved each month",
        min_value=Decimal(0),
        max_digits=10,
        decimal_places=2,
    )
    hours_saved_per_month_provenance = _provenance_field()
    loaded_hourly_rate = forms.DecimalField(
        label="Hourly labor cost including benefits",
        min_value=Decimal(0),
        max_digits=10,
        decimal_places=2,
    )
    loaded_hourly_rate_provenance = _provenance_field()
    attributable_revenue = forms.DecimalField(
        label="Additional monthly revenue attributable to this software",
        min_value=Decimal(0),
        max_digits=12,
        decimal_places=2,
    )
    attributable_revenue_provenance = _provenance_field()
    avoided_monthly_cost = forms.DecimalField(
        label="Monthly operational cost avoided",
        min_value=Decimal(0),
        max_digits=12,
        decimal_places=2,
    )
    avoided_monthly_cost_provenance = _provenance_field()

    def clean(self):
        cleaned = super().clean()
        for field_name in (
            "monthly_subscription_cost",
            "implementation_cost",
            "implementation_amortization_months",
            "hours_saved_per_month",
            "loaded_hourly_rate",
            "attributable_revenue",
            "avoided_monthly_cost",
        ):
            value = cleaned.get(field_name)
            if (
                cleaned.get(f"{field_name}_provenance")
                == AssumptionProvenance.UNKNOWN.value
                and value is not None
                and value != 0
            ):
                self.add_error(
                    field_name,
                    "Use 0 when this amount is unknown.",
                )
        return cleaned

    def to_inputs(self) -> ROIInputs:
        def assumption(field_name):
            return Assumption(
                value=self.cleaned_data[field_name],
                provenance=AssumptionProvenance(
                    self.cleaned_data[f"{field_name}_provenance"]
                ),
            )

        return ROIInputs(
            monthly_subscription_cost=assumption("monthly_subscription_cost"),
            implementation_cost=assumption("implementation_cost"),
            implementation_amortization_months=assumption(
                "implementation_amortization_months"
            ),
            hours_saved_per_month=assumption("hours_saved_per_month"),
            loaded_hourly_rate=assumption("loaded_hourly_rate"),
            attributable_revenue=assumption("attributable_revenue"),
            avoided_monthly_cost=assumption("avoided_monthly_cost"),
        )
