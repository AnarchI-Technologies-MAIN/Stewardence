"""Actual HTTP gates must reject attempts before payment-provider side effects."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.billing.models import BillingCustomer, FounderSlot, Subscription
from apps.billing.views import _handle_checkout_completed

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner(client):
    user = get_user_model().objects.create_user(
        email="payflow-gates@example.invalid", password="qualification-only"
    )
    BillingCustomer.objects.create(user=user, stripe_customer_id="cus_gate_probe")
    client.force_login(user)
    return user


@pytest.fixture
def forbidden_effects(monkeypatch):
    names = (
        "_stripe_client",
        "reserve_founder_slot",
        "claim_founder_slot",
        "stripe.Customer.create",
        "stripe.checkout.Session.create",
    )
    mocks = []
    for name in names:
        mock = Mock(side_effect=AssertionError("Denied checkout reached " + name))
        monkeypatch.setattr("apps.billing.views." + name, mock)
        mocks.append(mock)
    return mocks


@pytest.mark.parametrize("route", ["checkout-core", "checkout-automation"])
def test_checkout_get_never_creates_payment_or_reservation(
    client, owner, forbidden_effects, route
):
    response = client.get(reverse("billing:" + route))
    assert response.status_code == 405
    for mock in forbidden_effects:
        mock.assert_not_called()
    assert not FounderSlot.objects.exists()


@pytest.mark.parametrize("founder_enabled", [False, True])
def test_disabled_automation_cannot_be_enabled_by_posted_offer(
    client, owner, settings, forbidden_effects, founder_enabled
):
    settings.AUTOMATION_ENABLED = False
    settings.FOUNDER_OFFER_ENABLED = founder_enabled
    settings.STRIPE_SECRET_KEY = "sk_test_not_a_real_credential"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_qualification_only"
    for phase in ("STANDARD", "FOUNDER_INTRO", "FOUNDER_ONGOING"):
        setattr(
            settings,
            "STRIPE_AUTOMATION_" + phase + "_PRICE_ID",
            "price_automation_" + phase,
        )
    response = client.post(
        reverse("billing:checkout-automation"),
        {
            "AUTOMATION_ENABLED": "1",
            "portfolio": "automation",
            "founder": "true",
            "price": "price_automation_FOUNDER_INTRO",
            "founder_slot_sequence": "1",
        },
    )
    assert response.status_code == 503
    for mock in forbidden_effects:
        mock.assert_not_called()
    assert not FounderSlot.objects.exists()
    assert not Subscription.objects.exists()


def test_missing_core_price_cannot_be_bypassed_by_posted_founder_price(
    client, owner, settings, forbidden_effects
):
    settings.FOUNDER_OFFER_ENABLED = False
    settings.STRIPE_CORE_STANDARD_PRICE_ID = ""
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = "price_core_intro"
    response = client.post(
        reverse("billing:checkout-core"),
        {
            "FOUNDER_OFFER_ENABLED": "1",
            "price": "price_core_intro",
            "founder": "true",
        },
    )
    assert response.status_code == 503
    for mock in forbidden_effects:
        mock.assert_not_called()
    assert not FounderSlot.objects.exists()


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_core_route_does_not_accept_posted_enterprise_or_founder_authority(
    client, owner, settings, monkeypatch
):
    settings.FOUNDER_OFFER_ENABLED = False
    settings.STANDARD_CHECKOUT_INTENTS_ENABLED = True
    settings.STRIPE_CORE_STANDARD_PRICE_ID = "price_core_standard"
    reservation = Mock(
        side_effect=AssertionError("Posted founder field gained authority")
    )
    create = Mock(
        return_value=SimpleNamespace(
            id="cs_gate", url="https://example.invalid/checkout"
        )
    )
    monkeypatch.setattr("apps.billing.views._stripe_client", lambda: None)
    monkeypatch.setattr("apps.billing.views.reserve_founder_slot", reservation)
    monkeypatch.setattr("apps.billing.views.stripe.checkout.Session.create", create)
    frozen_flow = Mock(return_value="https://checkout.stripe.com/c/pay/qualification")
    monkeypatch.setattr(
        "apps.billing.standard_checkout_flow.start_standard_checkout", frozen_flow
    )
    response = client.post(
        reverse("billing:checkout-core"),
        {
            "portfolio": "enterprise",
            "branches": "999",
            "founder": "true",
            "price": "price_enterprise_intro",
            "founder_slot_sequence": "1",
        },
    )
    assert response.status_code == 302
    reservation.assert_not_called()
    create.assert_not_called()
    frozen_flow.assert_called_once()
    assert frozen_flow.call_args.args[0].id == owner.id
    # Price, portfolio, branch count and founder authority cannot cross this
    # entrypoint. The frozen service's actual-role tests verify its exact offer.
    payload = frozen_flow.call_args.kwargs
    assert set(payload) == {"success_url", "cancel_url"}
    assert payload["success_url"].endswith(
        "/billing/checkout/success/?session_id={CHECKOUT_SESSION_ID}"
    )
    assert payload["cancel_url"].endswith("/billing/portfolio/")
    assert not FounderSlot.objects.exists()


def test_unsupported_enterprise_completion_does_not_claim_or_activate(
    owner, forbidden_effects
):
    with pytest.raises(RuntimeError, match="unsupported portfolio"):
        _handle_checkout_completed(
            {
                "id": "cs_enterprise_gate",
                "client_reference_id": str(owner.id),
                "customer": "cus_gate_probe",
                "subscription": "sub_enterprise_gate",
                "payment_status": "paid",
                "metadata": {
                    "portfolio": "enterprise",
                    "stewardence_user_id": str(owner.id),
                    "founder_slot_sequence": "1",
                    "founder_reservation_token": "unissued",
                },
            }
        )
    for mock in forbidden_effects:
        mock.assert_not_called()
    assert not FounderSlot.objects.exists()
    assert not Subscription.objects.exists()
