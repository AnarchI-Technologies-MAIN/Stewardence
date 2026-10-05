"""Plain questions with explicit unknown/none/no distinctions."""

from decimal import Decimal

from django import forms

from .explicit_declarations import CONTRACT, LIST_FIELDS, NONE
from .forms import (
    CAPABILITY_CHOICES,
    CONNECTED_SYSTEM_CHOICES,
    DATA_CATEGORY_CHOICES,
    PERMISSION_CHOICES,
)
from .models import InventoryItem
from .provenance import INVENTORY_FACT_FIELDS


class ExplicitInventoryForm(forms.Form):
    display_name = forms.CharField(label="Tool or workflow name", max_length=255)
    vendor_name = forms.CharField(
        label="Vendor, if known", max_length=255, required=False
    )
    business_owner = forms.CharField(
        label="Responsible person, if known", max_length=255, required=False
    )
    department = forms.CharField(label="Team, if known", max_length=255, required=False)
    business_purpose = forms.CharField(
        label="Purpose, if known",
        max_length=4096,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    user_count = forms.IntegerField(
        label="People using it, if known",
        min_value=0,
        max_value=2147483647,
        required=False,
    )
    seat_count = forms.IntegerField(
        label="Paid seats, if known", min_value=0, max_value=2147483647, required=False
    )
    monthly_cost = forms.DecimalField(
        label="Monthly cost in dollars, if known",
        min_value=Decimal("0"),
        max_value=Decimal("21474836.47"),
        decimal_places=2,
        required=False,
    )
    human_approval = forms.ChoiceField(
        label="Must a person approve important actions?",
        choices=(("", "Unknown"), ("yes", "Yes"), ("no", "No")),
        required=False,
    )
    autonomy_level = forms.ChoiceField(
        label="Independent actions, if known",
        choices=(("", "Unknown"), *InventoryItem.Autonomy.choices),
        required=False,
    )
    status = forms.ChoiceField(
        label="Current use, if known",
        choices=(("", "Unknown"), *InventoryItem.Status.choices),
        required=False,
    )
    declaration_as_of = forms.DateField(
        label="As of which date do you declare these details?",
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Your stated knowledge date; this does not verify the details.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        super().__init__(*args, **kwargs)
        choices = dict(
            zip(
                LIST_FIELDS,
                (
                    CONNECTED_SYSTEM_CHOICES,
                    DATA_CATEGORY_CHOICES,
                    PERMISSION_CHOICES,
                    CAPABILITY_CHOICES,
                ),
                strict=True,
            )
        )
        for field, options in choices.items():
            self.fields[field] = forms.MultipleChoiceField(
                label=field.replace("_", " ").capitalize(),
                choices=(*options, (NONE, "None — I explicitly declare none")),
                required=False,
                widget=forms.CheckboxSelectMultiple,
                help_text=(
                    "Leave unselected when unknown. "
                    "Do not combine none with another answer."
                ),
            )
        if instance is not None:
            declared = set(instance.declared_fields)
            self.initial["declaration_as_of"] = instance.declaration_as_of
            for field in INVENTORY_FACT_FIELDS:
                if field not in declared:
                    continue
                value = getattr(instance, field)
                if field == "monthly_cost_cents":
                    self.initial["monthly_cost"] = Decimal(value) / 100
                elif field == "human_approval":
                    self.initial[field] = "yes" if value else "no"
                elif field in LIST_FIELDS:
                    self.initial[field] = value or [NONE]
                else:
                    self.initial[field] = value

    def clean(self):
        data = super().clean()
        for field in LIST_FIELDS:
            selected = data.get(field, [])
            if NONE in selected and len(selected) != 1:
                self.add_error(
                    field, "Choose none by itself, or choose the known values."
                )
        return data

    def declaration_payload(self):
        if not self.is_valid():
            raise ValueError("Valid declaration form required")
        declared = []
        values = {}
        for field in INVENTORY_FACT_FIELDS:
            name = "monthly_cost" if field == "monthly_cost_cents" else field
            value = self.cleaned_data[name]
            known = value is not None and value != "" and value != []
            if known:
                declared.append(field)
            if field in LIST_FIELDS:
                values[field] = (
                    [] if not known or value == [NONE] else sorted(set(value))
                )
            elif field == "monthly_cost_cents":
                values[field] = int(value * 100) if known else 0
            elif field in ("user_count", "seat_count", "autonomy_level"):
                values[field] = int(value) if known else 0
            elif field == "human_approval":
                values[field] = value == "yes" if known else True
            elif field == "status":
                values[field] = value if known else "reviewing"
            else:
                values[field] = value or ""
        return {
            "schema": CONTRACT,
            "declared_fields": sorted(declared),
            "as_of": self.cleaned_data["declaration_as_of"].isoformat(),
            "values": values,
        }
