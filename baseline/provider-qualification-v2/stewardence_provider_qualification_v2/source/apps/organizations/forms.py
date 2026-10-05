from __future__ import annotations

from django import forms

from .models import Organization


class OrganizationSetupForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = (
            "name",
            "industry",
        )
        labels = {
            "name": "Organization name",
            "industry": "Industry",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "autocomplete": "organization",
                    "placeholder": "Acme Advisory Group",
                }
            ),
        }


class OrganizationStartForm(forms.Form):
    START_IMPORT = "import_csv"
    START_MANUAL = "manual"
    START_EXPLORE = "explore"

    start_choice = forms.ChoiceField(
        label="How would you like to begin?",
        widget=forms.RadioSelect,
        choices=(
            (
                START_IMPORT,
                "Import my inventory from CSV",
            ),
            (
                START_MANUAL,
                "Add systems and tools manually",
            ),
            (
                START_EXPLORE,
                "Explore my workspace first",
            ),
        ),
    )
