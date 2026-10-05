from __future__ import annotations

from django import forms

from apps.inventory.forms import CAPABILITY_CHOICES, DATA_CATEGORY_CHOICES
from apps.inventory.models import InventoryItem

from .models import OrganizationRule
from .risk import RiskDimension

SEVERITY_FLOOR_CHOICES = (("", "No minimum"),) + tuple(
    (value, label) for value, label in OrganizationRule.Severity.choices
)
CONTROL_CHOICES = (
    ("", "No required control"),
    ("human_approval", "Human approval"),
    ("recipient_review", "Recipient review"),
    ("change_review", "Accounting-change review"),
)
RISK_DIMENSION_CHOICES = (("", "Do not add risk points"),) + tuple(
    (dimension.value, dimension.label) for dimension in RiskDimension
)


class OrganizationRuleForm(forms.ModelForm):
    data_category = forms.ChoiceField(
        label="This software accesses",
        choices=DATA_CATEGORY_CHOICES,
    )
    capability = forms.ChoiceField(
        label="This software can",
        choices=CAPABILITY_CHOICES,
    )
    severity_floor = forms.ChoiceField(
        label="Minimum risk level",
        choices=SEVERITY_FLOOR_CHOICES,
        required=False,
    )
    required_control = forms.ChoiceField(
        label="Require this control",
        choices=CONTROL_CHOICES,
        required=False,
    )
    risk_dimension = forms.ChoiceField(
        label="Risk area",
        choices=RISK_DIMENSION_CHOICES,
        required=False,
    )
    risk_points = forms.IntegerField(
        label="Points to add in that risk area",
        min_value=0,
        max_value=100,
        required=False,
    )
    finding_message = forms.CharField(
        label="Finding to create",
        max_length=500,
        required=False,
    )
    review_message = forms.CharField(
        label="Review to recommend",
        max_length=500,
        required=False,
    )
    test_item = forms.ModelChoiceField(
        label="Try this rule against",
        queryset=InventoryItem.objects.none(),
        required=False,
    )

    class Meta:
        model = OrganizationRule
        fields = (
            "name",
            "enabled",
            "result_on_match",
            "severity",
            "explanation",
            "remediation",
        )
        labels = {
            "name": "Rule name",
            "enabled": "Use this rule in assessments",
            "result_on_match": "When this rule matches",
            "severity": "Finding severity",
            "explanation": "Explain why this matters",
            "remediation": "Recommended next step",
        }

    def __init__(self, *args, organization_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.organization_id = organization_id
        self.fields["test_item"].queryset = InventoryItem.objects.filter(
            organization_id=organization_id,
            archived_at__isnull=True,
        )
        if not self.instance._state.adding:
            conditions = self.instance.definition.get("all", [])
            effects = self.instance.definition.get("effects", [])
            if len(conditions) >= 2:
                self.fields["data_category"].initial = conditions[0].get("value")
                self.fields["capability"].initial = conditions[1].get("value")
            for effect in effects:
                if effect.get("type") == "severity_floor":
                    self.fields["severity_floor"].initial = effect.get("value")
                elif effect.get("type") == "require_control":
                    self.fields["required_control"].initial = effect.get("control")
                elif effect.get("type") == "risk_points":
                    self.fields["risk_dimension"].initial = effect.get("dimension")
                    self.fields["risk_points"].initial = effect.get("value")
                elif effect.get("type") == "create_finding":
                    self.fields["finding_message"].initial = effect.get("message")
                elif effect.get("type") == "recommend_review":
                    self.fields["review_message"].initial = effect.get("message")

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        matches = OrganizationRule.objects.filter(
            organization_id=self.organization_id,
            name=name,
        )
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError("This firm already has a rule with that name.")
        return name

    def clean(self):
        cleaned = super().clean()
        dimension = cleaned.get("risk_dimension")
        points = cleaned.get("risk_points")
        if bool(dimension) != (points is not None):
            raise forms.ValidationError(
                "Choose both a risk area and its points, or leave both blank."
            )
        if not any(
            (
                cleaned.get("severity_floor"),
                cleaned.get("required_control"),
                dimension,
                cleaned.get("finding_message"),
                cleaned.get("review_message"),
            )
        ):
            raise forms.ValidationError("Choose at least one assessment effect.")
        return cleaned

    def structured_definition(self):
        effects = []
        if self.cleaned_data.get("risk_dimension"):
            effects.append(
                {
                    "type": "risk_points",
                    "dimension": self.cleaned_data["risk_dimension"],
                    "value": self.cleaned_data["risk_points"],
                }
            )
        if self.cleaned_data.get("severity_floor"):
            effects.append(
                {"type": "severity_floor", "value": self.cleaned_data["severity_floor"]}
            )
        if self.cleaned_data.get("required_control"):
            effects.append(
                {
                    "type": "require_control",
                    "control": self.cleaned_data["required_control"],
                }
            )
        if self.cleaned_data.get("finding_message"):
            effects.append(
                {
                    "type": "create_finding",
                    "message": self.cleaned_data["finding_message"],
                }
            )
        if self.cleaned_data.get("review_message"):
            effects.append(
                {
                    "type": "recommend_review",
                    "message": self.cleaned_data["review_message"],
                }
            )
        return {
            "all": [
                {
                    "field": "data_categories",
                    "operator": "contains",
                    "value": self.cleaned_data["data_category"],
                },
                {
                    "field": "capabilities",
                    "operator": "contains",
                    "value": self.cleaned_data["capability"],
                },
            ],
            "effects": effects,
        }
