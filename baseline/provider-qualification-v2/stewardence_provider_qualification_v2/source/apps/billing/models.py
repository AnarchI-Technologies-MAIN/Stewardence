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
        return self.status in {
            self.Status.ACTIVE,
            self.Status.CANCELING,
        }

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
