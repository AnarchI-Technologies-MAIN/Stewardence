from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model

from apps.billing.models import BillingCustomer, Subscription
from apps.billing.stripe_schedules import (
    ensure_founder_subscription_schedule,
)
from apps.billing.views import _handle_subscription_updated


pytestmark = pytest.mark.django_db
User = get_user_model()


def founder_subscription():
    user = User.objects.create_user(
        email="founder-schedule@example.com",
        password="test-password",
    )

    customer = BillingCustomer.objects.create(
        user=user,
        stripe_customer_id="cus_founder_schedule",
    )

    return Subscription.objects.create(
        billing_customer=customer,
        portfolio=Subscription.Portfolio.CORE,
        status=Subscription.Status.ACTIVE,
        is_founder=True,
        founder_sequence=7,
        stripe_subscription_id="sub_founder_schedule",
        current_price_cents=4900,
    )


def test_founder_schedule_is_six_intro_months_then_ongoing(
    monkeypatch,
    settings,
):
    subscription = founder_subscription()

    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder_49"
    )

    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = (
        "price_founder_75"
    )

    captured = {
        "creates": [],
        "modifies": [],
    }

    def create_schedule(**kwargs):
        captured["creates"].append(kwargs)

        return SimpleNamespace(
            id="sub_sched_founder",
            current_phase=SimpleNamespace(
                start_date=1_800_000_000,
            ),
            phases=[],
        )

    def modify_schedule(schedule_id, **kwargs):
        captured["modifies"].append(
            (schedule_id, kwargs)
        )

        return SimpleNamespace(
            id=schedule_id,
            phases=[
                SimpleNamespace(
                    start_date=1_800_000_000,
                    end_date=1_815_552_000,
                ),
                SimpleNamespace(
                    start_date=1_815_552_000,
                    end_date=None,
                ),
            ],
        )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules."
        "stripe.SubscriptionSchedule.create",
        create_schedule,
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules."
        "stripe.SubscriptionSchedule.modify",
        modify_schedule,
    )

    result = ensure_founder_subscription_schedule(
        subscription=subscription,
    )

    assert result["schedule_id"] == "sub_sched_founder"

    assert result["intro_ends_at"] == datetime.fromtimestamp(
        1_815_552_000,
        tz=dt_timezone.utc,
    )

    assert len(captured["creates"]) == 1

    create_kwargs = captured["creates"][0]

    assert (
        create_kwargs["from_subscription"]
        == "sub_founder_schedule"
    )

    assert create_kwargs["idempotency_key"] == (
        "stewardence-founder-schedule-create:"
        "sub_founder_schedule"
    )

    assert len(captured["modifies"]) == 1

    schedule_id, modify_kwargs = captured["modifies"][0]

    assert schedule_id == "sub_sched_founder"
    assert modify_kwargs["end_behavior"] == "release"
    assert modify_kwargs["proration_behavior"] == "none"

    phases = modify_kwargs["phases"]

    assert len(phases) == 2

    assert phases[0]["items"] == [
        {
            "price": "price_founder_49",
            "quantity": 1,
        }
    ]

    assert phases[0]["duration"] == {
        "interval": "month",
        "interval_count": 6,
    }

    assert phases[0]["proration_behavior"] == "none"

    assert phases[1]["items"] == [
        {
            "price": "price_founder_75",
            "quantity": 1,
        }
    ]

    assert "duration" not in phases[1]

    assert modify_kwargs["idempotency_key"] == (
        "stewardence-founder-schedule-configure-v1:"
        "sub_founder_schedule"
    )


def test_existing_local_schedule_is_retrieved_not_created(
    monkeypatch,
    settings,
):
    subscription = founder_subscription()

    subscription.stripe_schedule_id = "sub_sched_existing"
    subscription.save(
        update_fields=["stripe_schedule_id"]
    )

    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder_49"
    )

    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = (
        "price_founder_75"
    )

    creates = []
    retrieves = []

    monkeypatch.setattr(
        "apps.billing.stripe_schedules."
        "stripe.SubscriptionSchedule.create",
        lambda **kwargs: creates.append(kwargs),
    )

    def retrieve_schedule(schedule_id):
        retrieves.append(schedule_id)

        return SimpleNamespace(
            id=schedule_id,
            current_phase=SimpleNamespace(
                start_date=1_800_000_000,
            ),
            phases=[],
        )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules."
        "stripe.SubscriptionSchedule.retrieve",
        retrieve_schedule,
    )

    monkeypatch.setattr(
        "apps.billing.stripe_schedules."
        "stripe.SubscriptionSchedule.modify",
        lambda schedule_id, **_kwargs: SimpleNamespace(
            id=schedule_id,
            phases=[
                SimpleNamespace(
                    end_date=1_815_552_000,
                ),
                SimpleNamespace(
                    end_date=None,
                ),
            ],
        ),
    )

    result = ensure_founder_subscription_schedule(
        subscription=subscription,
    )

    assert result["schedule_id"] == "sub_sched_existing"
    assert creates == []
    assert retrieves == ["sub_sched_existing"]


def test_subscription_update_tracks_intro_price(
    settings,
):
    subscription = founder_subscription()

    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder_49"
    )
    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = (
        "price_founder_75"
    )
    settings.STRIPE_CORE_STANDARD_PRICE_ID = (
        "price_standard_99"
    )

    _handle_subscription_updated(
        {
            "id": "sub_founder_schedule",
            "status": "active",
            "cancel_at_period_end": False,
            "schedule": "sub_sched_founder",
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_founder_49",
                        }
                    }
                ]
            },
        }
    )

    subscription.refresh_from_db()

    assert subscription.current_price_cents == 4900
    assert (
        subscription.stripe_schedule_id
        == "sub_sched_founder"
    )


def test_subscription_update_tracks_ongoing_founder_price(
    settings,
):
    subscription = founder_subscription()

    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder_49"
    )
    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = (
        "price_founder_75"
    )
    settings.STRIPE_CORE_STANDARD_PRICE_ID = (
        "price_standard_99"
    )

    _handle_subscription_updated(
        {
            "id": "sub_founder_schedule",
            "status": "active",
            "cancel_at_period_end": False,
            "schedule": "sub_sched_founder",
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_founder_75",
                        }
                    }
                ]
            },
        }
    )

    subscription.refresh_from_db()

    assert subscription.current_price_cents == 7500


def test_unknown_stripe_price_does_not_invent_local_price(
    settings,
):
    subscription = founder_subscription()

    subscription.current_price_cents = 4900
    subscription.save(
        update_fields=["current_price_cents"]
    )

    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder_49"
    )
    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = (
        "price_founder_75"
    )
    settings.STRIPE_CORE_STANDARD_PRICE_ID = (
        "price_standard_99"
    )

    _handle_subscription_updated(
        {
            "id": "sub_founder_schedule",
            "status": "active",
            "cancel_at_period_end": False,
            "items": {
                "data": [
                    {
                        "price": {
                            "id": "price_unknown",
                        }
                    }
                ]
            },
        }
    )

    subscription.refresh_from_db()

    assert subscription.current_price_cents == 4900


def test_non_founder_cannot_receive_founder_schedule():
    user = User.objects.create_user(
        email="standard-schedule@example.com",
        password="test-password",
    )

    customer = BillingCustomer.objects.create(
        user=user,
    )

    subscription = Subscription.objects.create(
        billing_customer=customer,
        portfolio=Subscription.Portfolio.CORE,
        status=Subscription.Status.ACTIVE,
        is_founder=False,
        stripe_subscription_id="sub_standard",
        current_price_cents=9900,
    )

    with pytest.raises(
        RuntimeError,
        match="Founder schedule requires founder entitlement",
    ):
        ensure_founder_subscription_schedule(
            subscription=subscription,
        )
