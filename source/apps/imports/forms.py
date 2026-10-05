from django import forms


class CsvUploadForm(forms.Form):
    spreadsheet = forms.FileField(
        label="Software list spreadsheet",
        help_text="Choose a UTF-8 CSV with no more than 100 software rows.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv,text/csv"}),
    )
