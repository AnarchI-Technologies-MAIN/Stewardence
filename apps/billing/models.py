from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class BillingCustomer(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing_customer",
    )

    stripe_customer_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Subscription(models.Model):
    class Portfolio(models.TextChoices):
        CORE = "core", "Core"
        AUTOMATION = "automation", "Automation"
        ENTERPRISE = "enterprise", "Enterprise"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        CANCELING = "canceling", "Canceling"
        PAST_DUE = "past_due", "Past due"
        CANCELED = "canceled", "Canceled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    billing_customer = models.OneToOneField(
        BillingCustomer,
        on_delete=models.CASCADE,
        related_name="subscription",
    )

    organization = models.OneToOneField(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="subscription",
        null=True,
        blank=True,
    )

    portfolio = models.CharField(
        max_length=16,
        choices=Portfolio,
        default=Portfolio.CORE,
    )

    stripe_subscription_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    stripe_schedule_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.PENDING,
    )

    is_founder = models.BooleanField(default=False)

    founder_sequence = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        unique=True,
    )

    founder_intro_ends_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    founder_entitlement_ends_on_cancel = models.BooleanField(default=True)

    current_price_cents = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    current_period_end = models.DateTimeField(
        null=True,
        blank=True,
    )

    cancel_at_period_end = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def grants_access(self) -> bool:
        if self._state.adding:
            return False
        from .entitlements import paid_subscription_access
        return paid_subscription_access(self.pk, using=self._state.db or "default")

    @property
    def grants_automation(self) -> bool:
        return bool(
            self.portfolio == self.Portfolio.AUTOMATION
            and self.grants_access
            and (
                self.current_period_end is not None
                and self.current_period_end > timezone.now()
            )
        )


class StripeWebhookEvent(models.Model):
    """Committed receipt for one successfully processed Stripe event."""

    stripe_event_id = models.CharField(
        max_length=255,
        unique=True,
    )
    event_type = models.CharField(
        max_length=255,
    )
    processed_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ("processed_at", "stripe_event_id")

    def __str__(self):
        return f"{self.event_type}: {self.stripe_event_id}"


class FounderSlot(models.Model):
    """One of the finite founder-price allocation slots."""

    sequence = models.PositiveSmallIntegerField(
        primary_key=True,
    )

    billing_customer = models.OneToOneField(
        BillingCustomer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="founder_slot",
    )

    reservation_token = models.UUIDField(
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )

    stripe_checkout_session_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
    )

    reserved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    checkout_expires_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ("sequence",)
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(sequence__gte=1) & models.Q(sequence__lte=20)),
                name="billing_founder_slot_sequence_1_20",
            ),
        ]

    def __str__(self):
        return f"Founder slot {self.sequence}"


class PaidCoverageAuthority(models.Model):
    """Operator-owned account/mode pin; absent configuration denies access."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    stripe_account_id = models.CharField(max_length=255)
    livemode = models.BooleanField()
    contracts = models.JSONField(default=dict)

    class Meta:
        db_table = "billing_paid_coverage_authority"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="paid_authority_singleton")]


class PaidCoverage(models.Model):
    """Issued immutable payment evidence, not a mutable subscription period."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT)
    stripe_subscription_id = models.CharField(max_length=255)
    stripe_customer_id = models.CharField(max_length=255)
    stripe_account_id = models.CharField(max_length=255)
    livemode = models.BooleanField()
    stripe_invoice_id = models.CharField(max_length=255)
    stripe_event_id = models.CharField(max_length=255)
    contract_version = models.CharField(max_length=64)
    phase = models.CharField(max_length=32)
    stripe_price_id = models.CharField(max_length=255)
    amount_cents = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    service_start = models.DateTimeField()
    service_end = models.DateTimeField()
    paid_at = models.DateTimeField()
    evidence_sha256 = models.CharField(max_length=64)
    admitted_at = models.DateTimeField(editable=False)
    admission_payload = models.JSONField(editable=False)

    class Meta:
        db_table = "billing_paid_coverage"
        constraints = [
            models.UniqueConstraint(fields=("stripe_account_id", "livemode", "stripe_invoice_id"), name="paid_coverage_invoice_unique"),
            models.CheckConstraint(condition=models.Q(service_end__gt=models.F("service_start")), name="paid_coverage_positive_interval"),
        ]

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Paid coverage can only be issued by billing admission")

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Paid coverage is append-only")


class BillingAdmissionReceipt(models.Model):
    """Committed exact ingester effect; ordinary runtime roles cannot read/write."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    stripe_account_id = models.CharField(max_length=255)
    livemode = models.BooleanField()
    stripe_event_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    effect_sha256 = models.CharField(max_length=64)
    envelope = models.JSONField(editable=False)
    coverage = models.ForeignKey(PaidCoverage, on_delete=models.PROTECT)
    committed_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        db_table = "billing_admission_receipt"
        constraints = [
            models.UniqueConstraint(fields=("stripe_account_id", "livemode", "stripe_event_id"), name="billing_admission_event_unique"),
            models.CheckConstraint(condition=models.Q(event_type="invoice.paid"), name="billing_admission_event_type"),
        ]

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Admission receipts can only be issued by billing admission")

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Admission receipts are append-only")


class CheckoutIntent(models.Model):
    """Frozen standard checkout request; provider outcomes use a narrow issuer."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    billing_customer = models.ForeignKey(BillingCustomer, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    generation = models.UUIDField(unique=True, editable=False)
    stripe_customer_id = models.CharField(max_length=255)
    stripe_account_id = models.CharField(max_length=255)
    livemode = models.BooleanField()
    stripe_price_id = models.CharField(max_length=255)
    contract_version = models.CharField(max_length=64)
    params = models.JSONField(editable=False)
    params_sha256 = models.CharField(max_length=64, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True, editable=False)
    expires_at = models.DateTimeField(editable=False)
    created_at = models.DateTimeField(editable=False)
    state = models.CharField(max_length=16, default="pending")
    stripe_session_id = models.CharField(max_length=255, null=True, unique=True)
    observed_session_id = models.CharField(max_length=255, null=True)
    observed_url = models.CharField(max_length=2048, null=True)

    class Meta:
        db_table = "billing_checkout_intents"
        constraints = [models.UniqueConstraint(fields=("billing_customer",), condition=models.Q(state__in=("pending", "attached", "complete")), name="checkout_one_unresolved_customer")]

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Checkout intents require narrow issuance")

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Checkout intents cannot be deleted")


class BillingCustomerRequest(models.Model):
    """One frozen create request per local customer; no timeout-driven reset."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    billing_customer = models.OneToOneField(BillingCustomer, on_delete=models.PROTECT)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    generation = models.UUIDField(unique=True, editable=False)
    stripe_account_id = models.CharField(max_length=255, editable=False)
    livemode = models.BooleanField(editable=False)
    params = models.JSONField(editable=False)
    params_sha256 = models.CharField(max_length=64, editable=False)
    idempotency_key = models.CharField(max_length=255, unique=True, editable=False)
    created_at = models.DateTimeField(editable=False)
    observed_customer_id = models.CharField(max_length=255, null=True, editable=False)

    class Meta:
        db_table = "billing_customer_requests"

    def save(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Customer requests require narrow issuance")

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError("Customer requests cannot be deleted")
