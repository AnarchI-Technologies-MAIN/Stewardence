from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.billing.models import (
    BillingCustomer,
    Subscription,
)
from apps.billing.views import (
    _handle_checkout_completed,
    _handle_subscription_deleted,
    _handle_subscription_updated,
)


pytestmark = pytest.mark.django_db
User = get_user_model()


def make_user(email):
    return User.objects.create_user(
        email=email,
        password="test-password",
    )


def make_subscription(
    *,
    email,
    founder=True,
    status=Subscription.Status.ACTIVE,
):
    user = make_user(email)

    customer = BillingCustomer.objects.create(
        user=user,
        stripe_customer_id="cus_test",
    )

    subscription = Subscription.objects.create(
        billing_customer=customer,
        portfolio=Subscription.Portfolio.CORE,
        status=status,
        stripe_subscription_id="sub_test",
        stripe_schedule_id=(
            "sub_sched_test"
            if founder
            else None
        ),
        is_founder=founder,
        founder_sequence=(
            7
            if founder
            else None
        ),
        founder_intro_ends_at=(
            datetime(
                2027,
                3,
                10,
                tzinfo=dt_timezone.utc,
            )
            if founder
            else None
        ),
        current_price_cents=(
            4900
            if founder
            else 9900
        ),
    )

    return user, customer, subscription


def stripe_subscription(
    *,
    cancel_at_period_end,
    status="active",
    period_end=1800000000,
    price_id="price_unknown",
    schedule="sub_sched_test",
):
    return {
        "id": "sub_test",
        "status": status,
        "cancel_at_period_end": (
            cancel_at_period_end
        ),
        "current_period_end": period_end,
        "schedule": schedule,
        "items": {
            "data": [
                {
                    "current_period_end": period_end,
                    "price": {
                        "id": price_id,
                    },
                }
            ]
        },
    }


def test_portal_requires_authenticated_user(
    client,
):
    response = client.get(
        reverse("billing:portal")
    )

    assert response.status_code == 302


def test_portal_session_uses_owned_stripe_customer(
    client,
    monkeypatch,
    settings,
):
    monkeypatch.setattr(
        "apps.billing.views.settings.STRIPE_SECRET_KEY",
        "sk_test_stewardence_unit_only",
    )

    user = make_user(
        "portal-owner@example.com"
    )

    BillingCustomer.objects.create(
        user=user,
        stripe_customer_id="cus_owned",
    )

    settings.STRIPE_BILLING_PORTAL_CONFIGURATION_ID = (
        "bpc_test"
    )

    settings.STRIPE_BILLING_PORTAL_FOUNDER_CONFIGURATION_ID = (
        "bpc_founder_test"
    )

    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            url="https://billing.stripe.test/session"
        )

    monkeypatch.setattr(
        "apps.billing.views.stripe.billing_portal.Session.create",
        fake_create,
    )

    client.force_login(user)

    response = client.get(
        reverse("billing:portal")
    )

    assert response.status_code == 302

    assert (
        response["Location"]
        == "https://billing.stripe.test/session"
    )

    assert captured["customer"] == "cus_owned"
    assert captured["configuration"] == "bpc_test"

    assert captured["return_url"].endswith(
        reverse(
            "organizations:workspace-selection"
        )
    )


def test_pending_cancellation_retains_access_and_founder():
    _user, _customer, subscription = (
        make_subscription(
            email="canceling@example.com",
        )
    )

    _handle_subscription_updated(
        stripe_subscription(
            cancel_at_period_end=True,
        )
    )

    subscription.refresh_from_db()

    assert (
        subscription.status
        == Subscription.Status.CANCELING
    )

    assert (
        subscription.cancel_at_period_end
        is True
    )

    assert subscription.grants_access is True
    assert subscription.is_founder is True

    assert (
        subscription.stripe_schedule_id
        == "sub_sched_test"
    )

    assert (
        subscription.current_period_end
        == datetime.fromtimestamp(
            1800000000,
            tz=dt_timezone.utc,
        )
    )


def test_subscription_update_cannot_undo_schedule_owned_founder_cancel():
    _user, _customer, subscription = (
        make_subscription(
            email="schedule-owned-cancel@example.com",
            status=Subscription.Status.CANCELING,
        )
    )

    subscription.cancel_at_period_end = True

    subscription.save(
        update_fields=[
            "cancel_at_period_end",
            "updated_at",
        ]
    )

    # Real Stripe evidence established that a founder subscription
    # managed by an active SubscriptionSchedule reports
    # cancel_at_period_end=False on the underlying Subscription even
    # while the schedule itself is configured to cancel at the paid
    # period boundary.
    #
    # Therefore a customer.subscription.updated event is not allowed
    # to clear Stewardence's normalized CANCELING state. Only the
    # authoritative schedule restoration event may do that.
    _handle_subscription_updated(
        stripe_subscription(
            cancel_at_period_end=False,
        )
    )

    subscription.refresh_from_db()

    assert (
        subscription.status
        == Subscription.Status.CANCELING
    )

    assert (
        subscription.cancel_at_period_end
        is True
    )

    assert subscription.grants_access is True
    assert subscription.is_founder is True

    assert (
        subscription.stripe_schedule_id
        == "sub_sched_test"
    )


def test_actual_deletion_ends_founder_economic_entitlement():
    _user, _customer, subscription = (
        make_subscription(
            email="deleted-founder@example.com",
        )
    )

    _handle_subscription_deleted(
        stripe_subscription(
            cancel_at_period_end=False,
            status="canceled",
        )
    )

    subscription.refresh_from_db()

    assert (
        subscription.status
        == Subscription.Status.CANCELED
    )

    assert subscription.grants_access is False
    assert subscription.is_founder is False

    # Preserve historical founder provenance.
    assert subscription.founder_sequence == 7

    assert subscription.stripe_schedule_id is None
    assert subscription.founder_intro_ends_at is None


def test_standard_resubscription_clears_active_founder_state(
    monkeypatch,
):
    user, customer, subscription = (
        make_subscription(
            email="standard-resubscribe@example.com",
            status=Subscription.Status.CANCELED,
        )
    )

    subscription.is_founder = True
    subscription.stripe_schedule_id = (
        "sub_sched_historical"
    )

    subscription.save(
        update_fields=[
            "is_founder",
            "stripe_schedule_id",
            "updated_at",
        ]
    )

    session = {
        "id": "cs_standard_new",
        "client_reference_id": str(user.id),
        "subscription": "sub_standard_new",
        "metadata": {
            "portfolio": "core",
        },
    }

    _handle_checkout_completed(
        session
    )

    subscription.refresh_from_db()

    assert (
        subscription.stripe_subscription_id
        == "sub_standard_new"
    )

    assert (
        subscription.status
        == Subscription.Status.ACTIVE
    )

    assert subscription.is_founder is False
    assert subscription.founder_sequence == 7
    assert subscription.stripe_schedule_id is None
    assert subscription.founder_intro_ends_at is None
    assert subscription.current_price_cents == 9900
