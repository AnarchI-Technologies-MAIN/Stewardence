from __future__ import annotations

from decimal import Decimal

from django import forms

from .models import InventoryItem

DATA_CATEGORY_CHOICES = (
    ("public_information", "Public information"),
    ("internal_business_information", "Internal business information"),
    ("client_information", "Client information"),
    ("financial_records", "Financial records"),
    ("banking_information", "Banking information"),
    ("payroll", "Payroll"),
    ("tax_records", "Tax records"),
    ("health_information", "Health information"),
    ("legal_information", "Legal information"),
    ("authentication_credentials", "Authentication credentials"),
    ("personally_identifiable_information", "Personally identifiable information"),
)

CONNECTED_SYSTEM_CHOICES = (
    ("accounting", "Accounting system"),
    ("banking", "Banking or payment system"),
    ("payroll", "Payroll system"),
    ("tax", "Tax system"),
    ("document_storage", "Company file storage"),
    ("email", "Company email"),
    ("customer_records", "Customer or client records"),
    ("other", "Another company system"),
)

PERMISSION_CHOICES = (
    ("read", "Read information"),
    ("write", "Create or change information"),
    ("delete", "Delete information"),
    ("transmit", "Send information outside the firm"),
    ("administer", "Manage settings or other users"),
)

CAPABILITY_CHOICES = (
    ("content_generation", "Create written or visual content"),
    ("data_analysis", "Analyze company information"),
    ("external_transfer", "Send information outside the firm"),
    ("financial_transaction", "Initiate a financial transaction"),
    ("record_modification", "Change business records"),
    ("communication", "Communicate with people outside the firm"),
)


class InventoryItemForm(forms.ModelForm):
    monthly_cost = forms.DecimalField(
        label="Monthly subscription cost",
        min_value=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
        help_text="Enter the monthly amount in dollars.",
    )
    connected_systems = forms.MultipleChoiceField(
        label="Which company systems can it connect to?",
        choices=CONNECTED_SYSTEM_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    data_categories = forms.MultipleChoiceField(
        label="What kinds of information can it access?",
        choices=DATA_CATEGORY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    permissions = forms.MultipleChoiceField(
        label="What is it allowed to do?",
        choices=PERMISSION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    capabilities = forms.MultipleChoiceField(
        label="What can it do for the business?",
        choices=CAPABILITY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = InventoryItem
        fields = (
            "display_name",
            "vendor_name",
            "business_owner",
            "department",
            "user_count",
            "business_purpose",
            "monthly_cost",
            "seat_count",
            "connected_systems",
            "data_categories",
            "permissions",
            "capabilities",
            "autonomy_level",
            "human_approval",
            "status",
        )
        labels = {
            "display_name": "AI application or agent",
            "vendor_name": "Vendor",
            "business_owner": "Person responsible for this software",
            "department": "Team or department",
            "user_count": "How many people use it?",
            "business_purpose": "What does the firm use it for?",
            "seat_count": "Paid seats",
            "autonomy_level": "What can this AI do on its own?",
            "human_approval": "A person must approve important actions",
            "status": "How is the firm using it now?",
        }
        widgets = {
            "business_purpose": forms.Textarea(attrs={"rows": 3}),
            "autonomy_level": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["monthly_cost"].initial = Decimal(
                self.instance.monthly_cost_cents
            ) / Decimal(100)

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.monthly_cost_cents = int(
            self.cleaned_data["monthly_cost"] * Decimal(100)
        )
        if commit:
            instance.save()
        return instance
