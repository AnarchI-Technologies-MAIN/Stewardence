from django import forms

from .quickbooks_client import OAuthError
from .quickbooks_reports import ReportPeriod


class SandboxReportForm(forms.Form):
    start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(
        label="End date (inclusive)", widget=forms.DateInput(attrs={"type": "date"})
    )
    accounting_basis = forms.ChoiceField(
        choices=[
            ("", "Select report basis"),
            ("Cash", "Cash"),
            ("Accrual", "Accrual"),
        ]
    )
    authorize_export = forms.BooleanField(
        label="Read this sandbox report and download it to my device."
    )

    def clean(self):
        data = super().clean()
        if all(data.get(k) for k in ("start_date", "end_date", "accounting_basis")):
            try:
                self.period = ReportPeriod(
                    data["start_date"], data["end_date"], data["accounting_basis"]
                )
            except OAuthError:
                raise forms.ValidationError(
                    "Choose an ordered date range of at most 92 days, inclusive."
                ) from None
        return data
