"""Standard-only launch must not allocate or advertise founder contracts."""

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from django.urls import reverse

from apps.billing.models import BillingCustomer, FounderSlot

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def signed_in_customer(client):
    user = get_user_model().objects.create_user(
        email="standard-launch@example.invalid", password="test-password"
    )
    BillingCustomer.objects.create(user=user, stripe_customer_id="cus_standard_launch")
    client.force_login(user)
    return user


def test_standard_only_portfolio_has_no_founder_offer(client, settings, monkeypatch):
    settings.FOUNDER_OFFER_ENABLED = False
    signed_in_customer(client)

    def forbidden_count():
        raise AssertionError("Disabled offer must not query founder allocation")

    monkeypatch.setattr("apps.billing.views.founder_claimed_count", forbidden_count)
    response = client.get(reverse("billing:portfolio"))
    assert response.status_code == 200
    assert b"$99" in response.content
    assert b"$49" not in response.content
    assert b"Founding Customer Offer" not in response.content


def test_standard_only_checkout_ignores_submitted_founder_fields(
    client, settings, monkeypatch
):
    settings.FOUNDER_OFFER_ENABLED = False
    settings.STANDARD_CHECKOUT_INTENTS_ENABLED = True
    settings.STRIPE_CORE_STANDARD_PRICE_ID = "price_core_99"
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = "price_core_49"
    user = signed_in_customer(client)
    captured = []
    monkeypatch.setattr("apps.billing.views._stripe_client", lambda: None)

    def forbidden_reservation(**kwargs):
        raise AssertionError("Standard launch must never reserve founder slots")

    def start_frozen_flow(owner, **kwargs):
        assert owner.id == user.id
        assert not connections["default"].in_atomic_block
        captured.append(kwargs)
        return "https://checkout.stripe.com/c/pay/cs_standard"

    monkeypatch.setattr(
        "apps.billing.views.reserve_founder_slot", forbidden_reservation
    )
    monkeypatch.setattr(
        "apps.billing.standard_checkout_flow.start_standard_checkout", start_frozen_flow
    )
    response = client.post(
        reverse("billing:checkout-core"),
        {
            "founder_slot_sequence": "1",
            "price": "price_core_49",
            "portfolio": "automation",
        },
    )
    assert response.status_code == 302
    assert set(captured[0]) == {"success_url", "cancel_url"}
    assert captured[0]["success_url"].endswith(
        "/billing/checkout/success/?session_id={CHECKOUT_SESSION_ID}"
    )
    assert captured[0]["cancel_url"].endswith("/billing/portfolio/")
    assert not FounderSlot.objects.exists()


def test_missing_standard_price_stops_before_stripe_or_reservation(
    client, settings, monkeypatch
):
    settings.FOUNDER_OFFER_ENABLED = False
    settings.STRIPE_CORE_STANDARD_PRICE_ID = ""
    signed_in_customer(client)

    def forbidden_stripe():
        raise AssertionError("Missing launch configuration must stop before Stripe")

    monkeypatch.setattr("apps.billing.views._stripe_client", forbidden_stripe)
    response = client.post(reverse("billing:checkout-core"))
    assert response.status_code == 503
    assert not FounderSlot.objects.exists()
