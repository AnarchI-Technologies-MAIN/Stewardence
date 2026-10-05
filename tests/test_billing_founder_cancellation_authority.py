from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.billing.models import (
    BillingCustomer,
    Subscription,
)
from apps.billing.stripe_schedules import (
    schedule_founder_cancellation_at_period_end,
    undo_founder_cancellation,
)
from apps.billing.views import (
    _handle_subscription_schedule_event,
)
from tests.conftest import grant_paid_test_coverage

pytestmark = pytest.mark.django_db
User = get_user_model()


INTRO_PRICE = "price_founder_intro"
ONGOING_PRICE = "price_founder_ongoing"


def make_founder(
    *,
    email,
    status=Subscription.Status.ACTIVE,
):
    user = User.objects.create_user(
        email=email,
        password="test-password",
    )

    customer = BillingCustomer.objects.create(
        user=user,
        stripe_customer_id="cus_founder",
    )

    subscription = Subscription.objects.create(
        billing_customer=customer,
        portfolio=Subscription.Portfolio.CORE,
        status=status,
        stripe_subscription_id="sub_founder",
        stripe_schedule_id="sub_sched_founder",
        is_founder=True,
        founder_sequence=8,
        founder_intro_ends_at=datetime(
            2027,
            3,
            10,
            tzinfo=UTC,
        ),
        current_price_cents=4900,
    )

    if status in {Subscription.Status.ACTIVE, Subscription.Status.CANCELING}:
        grant_paid_test_coverage(subscription)
    return user, customer, subscription


def stripe_subscription(
    *,
    price_id=INTRO_PRICE,
    period_end=1800000000,
):
    return {
        "id": "sub_founder",
        "status": "active",
        "cancel_at_period_end": False,
        "current_period_end": period_end,
        "schedule": "sub_sched_founder",
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


def test_founder_cancel_uses_active_schedule(
    monkeypatch,
    settings,
):
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = INTRO_PRICE

    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = ONGOING_PRICE

    _user, _customer, subscription = make_founder(
        email="schedule-cancel@example.com",
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.Subscription.retrieve",
        lambda _id: stripe_subscription(),
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.retrieve",
        lambda _id: {
            "id": "sub_sched_founder",
            "status": "active",
            "current_phase": {
                "start_date": 1789000000,
                "end_date": 1804000000,
            },
        },
    )

    captured = {}

    def fake_modify(schedule_id, **kwargs):
        captured["schedule_id"] = schedule_id
        captured.update(kwargs)

        return {
            "id": schedule_id,
            "status": "active",
            "end_behavior": "cancel",
        }

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.modify",
        fake_modify,
    )

    result = schedule_founder_cancellation_at_period_end(
        subscription=subscription,
    )

    assert result["mode"] == "schedule"
    assert captured["schedule_id"] == "sub_sched_founder"
    assert captured["end_behavior"] == "cancel"
    assert captured["proration_behavior"] == "none"

    phase = captured["phases"][0]

    assert phase["start_date"] == 1789000000
    assert phase["end_date"] == 1800000000
    assert phase["items"][0]["price"] == INTRO_PRICE


def test_released_founder_cancel_uses_subscription(
    monkeypatch,
    settings,
):
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = INTRO_PRICE

    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = ONGOING_PRICE

    _user, _customer, subscription = make_founder(
        email="released-cancel@example.com",
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.Subscription.retrieve",
        lambda _id: stripe_subscription(price_id=ONGOING_PRICE),
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.retrieve",
        lambda _id: {
            "id": "sub_sched_founder",
            "status": "released",
        },
    )

    captured = {}

    def fake_subscription_modify(
        subscription_id,
        **kwargs,
    ):
        captured["subscription_id"] = subscription_id
        captured.update(kwargs)

        return {
            "id": subscription_id,
            "status": "active",
            "cancel_at_period_end": True,
        }

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.Subscription.modify",
        fake_subscription_modify,
    )

    result = schedule_founder_cancellation_at_period_end(
        subscription=subscription,
    )

    assert result["mode"] == "subscription"
    assert captured["subscription_id"] == "sub_founder"

    assert captured["cancel_at_period_end"] is True


def test_founder_undo_restores_original_intro_boundary(
    monkeypatch,
    settings,
):
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = INTRO_PRICE

    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = ONGOING_PRICE

    _user, _customer, subscription = make_founder(
        email="undo-founder@example.com",
        status=Subscription.Status.CANCELING,
    )

    subscription.cancel_at_period_end = True

    subscription.save(
        update_fields=[
            "cancel_at_period_end",
            "updated_at",
        ]
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.Subscription.retrieve",
        lambda _id: stripe_subscription(),
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.retrieve",
        lambda _id: {
            "id": "sub_sched_founder",
            "status": "active",
            "current_phase": {
                "start_date": 1789000000,
                "end_date": 1800000000,
            },
        },
    )

    captured = {}

    def fake_modify(schedule_id, **kwargs):
        captured["schedule_id"] = schedule_id
        captured.update(kwargs)

        return {
            "id": schedule_id,
            "status": "active",
            "end_behavior": "release",
        }

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.modify",
        fake_modify,
    )

    result = undo_founder_cancellation(
        subscription=subscription,
    )

    assert result["mode"] == "schedule"
    assert captured["end_behavior"] == "release"
    assert len(captured["phases"]) == 2

    expected_intro_end = int(subscription.founder_intro_ends_at.timestamp())

    assert captured["phases"][0]["end_date"] == expected_intro_end

    assert captured["phases"][0]["items"][0]["price"] == INTRO_PRICE

    assert captured["phases"][1]["items"][0]["price"] == ONGOING_PRICE


def test_schedule_event_normalizes_founder_canceling():
    _user, _customer, subscription = make_founder(
        email="schedule-event@example.com",
    )

    _handle_subscription_schedule_event(
        {
            "id": "sub_sched_founder",
            "status": "active",
            "end_behavior": "cancel",
        }
    )

    subscription.refresh_from_db()

    assert subscription.status == Subscription.Status.CANCELING

    assert subscription.cancel_at_period_end is True

    assert subscription.grants_access is True


def test_schedule_release_event_undoes_pending_cancel():
    _user, _customer, subscription = make_founder(
        email="schedule-release@example.com",
        status=Subscription.Status.CANCELING,
    )

    subscription.cancel_at_period_end = True

    subscription.save(
        update_fields=[
            "cancel_at_period_end",
            "updated_at",
        ]
    )

    _handle_subscription_schedule_event(
        {
            "id": "sub_sched_founder",
            "status": "active",
            "end_behavior": "release",
        }
    )

    subscription.refresh_from_db()

    assert subscription.status == Subscription.Status.ACTIVE

    assert subscription.cancel_at_period_end is False


def test_founder_cancel_route_requires_post(
    client,
):
    user, _customer, _subscription = make_founder(
        email="cancel-route@example.com",
    )

    client.force_login(user)

    response = client.get(reverse("billing:founder-cancel"))

    assert response.status_code == 405


def test_founder_undo_route_requires_post(
    client,
):
    user, _customer, _subscription = make_founder(
        email="undo-route@example.com",
        status=Subscription.Status.CANCELING,
    )

    client.force_login(user)

    response = client.get(reverse("billing:founder-cancel-undo"))

    assert response.status_code == 405


def test_founder_portal_uses_no_cancel_configuration(
    client,
    monkeypatch,
    settings,
):
    monkeypatch.setattr(
        "apps.billing.views.settings.STRIPE_SECRET_KEY",
        "sk_test_stewardence_unit_only",
    )

    user, _customer, _subscription = make_founder(
        email="founder-portal@example.com",
    )

    settings.STRIPE_BILLING_PORTAL_CONFIGURATION_ID = "bpc_standard"

    settings.STRIPE_BILLING_PORTAL_FOUNDER_CONFIGURATION_ID = "bpc_founder_no_cancel"

    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(url="https://billing.stripe.test/founder")

    monkeypatch.setattr(
        "apps.billing.views.stripe.billing_portal.Session.create",
        fake_create,
    )

    client.force_login(user)

    response = client.get(reverse("billing:portal"))

    assert response.status_code == 302

    assert captured["configuration"] == "bpc_founder_no_cancel"
