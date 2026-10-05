from __future__ import annotations

from django import forms
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import User


class PublicSignupForm(forms.Form):
    first_name = forms.CharField(
        label="First name",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "given-name",
                "placeholder": "First name",
            }
        ),
    )
    last_name = forms.CharField(
        label="Last name",
        max_length=150,
        required=False,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "family-name",
                "placeholder": "Last name",
            }
        ),
    )
    email = forms.EmailField(
        label="Work email",
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "placeholder": "you@company.com",
            }
        ),
    )
    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Create a strong password",
            }
        ),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "new-password",
                "placeholder": "Enter it again",
            }
        ),
    )
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    def clean_email(self) -> str:
        raw_email = self.cleaned_data.get("email", "")
        email = User.objects.normalize_identity(raw_email)

        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("An account already exists for this email address.")

        return email

    def clean_website(self) -> str:
        value = self.cleaned_data.get("website", "")

        if value:
            raise ValidationError("Unable to create this account.")

        return value

    def clean(self):
        cleaned = super().clean()

        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error(
                "password2",
                "The two passwords do not match.",
            )
            return cleaned

        if password1:
            candidate = User(
                email=cleaned.get("email", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
            )

            try:
                password_validation.validate_password(
                    password1,
                    user=candidate,
                )
            except ValidationError as error:
                self.add_error(
                    "password1",
                    error,
                )

        return cleaned

    def save(self) -> User:
        if not self.is_valid():
            raise ValueError("Cannot save an invalid signup form.")

        return User.objects.create_user(
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
            first_name=self.cleaned_data["first_name"],
            last_name=self.cleaned_data["last_name"],
        )
