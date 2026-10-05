from django import forms

from apps.assessments.models import AssessmentSnapshot


class FreezeForm(forms.Form):
    cycle_id = forms.UUIDField(widget=forms.HiddenInput)


class DecisionForm(forms.Form):
    expected_previous_event = forms.UUIDField(required=False, widget=forms.HiddenInput)
    event_kind = forms.ChoiceField(
        choices=[
            ("disposition", "Owner decision"),
            ("execution", "Owner execution statement"),
        ]
    )
    state = forms.ChoiceField(
        choices=[
            (value, value.replace("_", " "))
            for value in (
                "act",
                "defer",
                "decline",
                "accept_risk",
                "completion_recorded",
                "evidence_reviewed",
            )
        ]
    )
    responsible_label = forms.CharField(
        max_length=200, label="Responsible person (recorded name)"
    )
    due_date = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    notes = forms.CharField(
        required=False,
        max_length=4096,
        widget=forms.Textarea,
        label="Reason and evidence boundary",
    )
    links = forms.CharField(
        required=False,
        max_length=20489,
        widget=forms.Textarea,
        label="Evidence references: one HTTPS address per line; never fetched",
    )

    def clean_links(self):
        links = [
            line.strip()
            for line in self.cleaned_data["links"].splitlines()
            if line.strip()
        ]
        import re

        if len(links) > 10 or any(
            len(link) > 2048
            or not re.fullmatch(r"https://[^\s/?#@]+(?:[/?#][^\s]*)?", link)
            for link in links
        ):
            raise forms.ValidationError(
                "Use at most ten HTTPS references without credentials, "
                "each at most 2048 characters."
            )
        return links

    def clean(self):
        cleaned = super().clean()
        kind, state = cleaned.get("event_kind"), cleaned.get("state")
        if (
            kind == "disposition"
            and state not in ("act", "defer", "decline", "accept_risk")
            or kind == "execution"
            and state not in ("completion_recorded", "evidence_reviewed")
        ):
            self.add_error("state", "Choose a state matching the statement kind.")
        return cleaned


class UnusedStopForm(forms.Form):
    reason = forms.ChoiceField(
        choices=(
            ("context_too_large", "The frozen report exceeds its supported size"),
            ("owner_stopped", "I want to stop this unused report preparation"),
        )
    )


class ComparisonForm(forms.Form):
    baseline = forms.ModelChoiceField(
        queryset=AssessmentSnapshot.objects.none(), label="Earlier captured snapshot"
    )
    current = forms.ModelChoiceField(
        queryset=AssessmentSnapshot.objects.none(), label="Current captured snapshot"
    )

    def __init__(self, *args, organization_id, **kwargs):
        super().__init__(*args, **kwargs)
        snapshots = AssessmentSnapshot.objects.filter(
            organization_id=organization_id
        ).order_by("-captured_at", "-id")
        self.fields["baseline"].queryset = snapshots
        self.fields["current"].queryset = snapshots
