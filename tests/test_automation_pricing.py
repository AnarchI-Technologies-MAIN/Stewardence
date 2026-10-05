from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.billing.models import Subscription
from apps.billing.pricing import (
    PriceContract,
    automation_checkout_available,
    configured_price_contracts,
    portfolio_price_ids,
    subscription_price_contract,
    validate_price_object,
)
from apps.billing.stripe_schedules import ensure_founder_subscription_schedule


@pytest.fixture
def prices(settings):
    for portfolio in ("core", "automation"):
        for phase in ("standard", "founder_intro", "founder_ongoing"):
            setattr(
                settings,
                f"STRIPE_{portfolio.upper()}_{phase.upper()}_PRICE_ID",
                f"price_{portfolio}_{phase}",
            )


@pytest.mark.parametrize(
    "phase,cents",
    [
        ("standard", 14900),
        ("founder_intro", 7500),
        ("founder_ongoing", 11200),
    ],
)
def test_automation_prices_are_distinct_contracts(prices, phase, cents):
    contract = subscription_price_contract(
        {
            "items": {
                "data": [{"quantity": 1, "price": {"id": f"price_automation_{phase}"}}]
            }
        }
    )
    assert contract == PriceContract("automation", phase, cents)


def test_empty_or_multiple_prices_cannot_grant_a_portfolio(settings, prices):
    assert subscription_price_contract({"items": {"data": []}}) is None
    assert (
        subscription_price_contract({"items": {"data": [{"price": {"id": ""}}]}})
        is None
    )
    assert (
        subscription_price_contract(
            {
                "items": {
                    "data": [
                        {"price": {"id": "price_automation_standard"}},
                        {"price": {"id": "price_core_standard"}},
                    ]
                }
            }
        )
        is None
    )


def test_price_id_collision_is_rejected(settings, prices):
    settings.STRIPE_AUTOMATION_STANDARD_PRICE_ID = "price_core_standard"
    with pytest.raises(ValueError, match="distinct"):
        configured_price_contracts()


def test_unsupported_plan_has_no_checkout_price():
    with pytest.raises(ValueError, match="Unsupported"):
        portfolio_price_ids("enterprise")


def test_automation_checkout_requires_explicit_activation_and_all_prices(
    settings, prices
):
    settings.STRIPE_SECRET_KEY = "test-secret"
    settings.STRIPE_WEBHOOK_SECRET = "test-signing-secret"
    settings.AUTOMATION_ENABLED = False
    assert not automation_checkout_available()
    settings.AUTOMATION_ENABLED = True
    assert automation_checkout_available()
    settings.STRIPE_AUTOMATION_FOUNDER_ONGOING_PRICE_ID = ""
    assert not automation_checkout_available()


@pytest.mark.parametrize(
    "mutation",
    [
        {"active": False},
        {"currency": "eur"},
        {"unit_amount": 9900},
        {"recurring": {"interval": "year", "interval_count": 1}},
        {"recurring": {"interval": "month", "interval_count": 2}},
        {"recurring": {"interval": "month", "usage_type": "metered"}},
    ],
)
def test_incorrect_stripe_price_cannot_satisfy_contract(mutation):
    price = {
        "active": True,
        "currency": "usd",
        "unit_amount": 14900,
        "recurring": {"interval": "month", "interval_count": 1},
    }
    price.update(mutation)
    with pytest.raises(ValueError, match="contract"):
        validate_price_object(price, PriceContract("automation", "standard", 14900))


def test_automation_founder_schedule_uses_75_then_112(prices, monkeypatch):
    subscription = SimpleNamespace(
        portfolio="automation",
        is_founder=True,
        founder_sequence=8,
        stripe_subscription_id="sub_automation",
        stripe_schedule_id=None,
        billing_customer_id="customer-automation",
    )
    captured = {}
    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.create",
        lambda **kwargs: {
            "id": "sched_automation",
            "current_phase": {"start_date": 1800000000},
        },
    )

    def modify(schedule_id, **kwargs):
        captured.update(kwargs)
        return {"id": schedule_id, "phases": [{"end_date": 1815552000}, {}]}

    monkeypatch.setattr(
        "apps.billing.stripe_schedules.stripe.SubscriptionSchedule.modify", modify
    )
    ensure_founder_subscription_schedule(subscription=subscription)
    assert (
        captured["phases"][0]["items"][0]["price"] == "price_automation_founder_intro"
    )
    assert (
        captured["phases"][1]["items"][0]["price"] == "price_automation_founder_ongoing"
    )
    assert captured["phases"][0]["duration"] == {
        "interval": "month",
        "interval_count": 6,
    }


@pytest.mark.parametrize(
    "status,expected",
    [
        ("active", False),
        ("canceling", False),
        ("past_due", False),
        ("pending", False),
        ("canceled", False),
    ],
)
def test_unpersisted_automation_status_cannot_issue_entitlement(status, expected):
    # A status-only draft has no admitted payment receipt or enabled portfolio.
    subscription = Subscription(
        portfolio="automation",
        status=status,
        current_period_end=timezone.now() + timedelta(days=1),
    )
    assert subscription.grants_automation is expected


def test_core_and_expired_automation_cannot_run_automation():
    assert not Subscription(portfolio="core", status="active").grants_automation
    assert not Subscription(
        portfolio="automation",
        status="active",
        current_period_end=timezone.now() - timedelta(seconds=1),
    ).grants_automation
