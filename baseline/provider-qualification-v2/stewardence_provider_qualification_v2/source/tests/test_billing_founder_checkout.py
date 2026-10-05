from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.billing.founder_slots import (
    attach_founder_checkout_session,
    claim_founder_slot,
    release_expired_founder_checkout,
    reserve_founder_slot,
)
from apps.billing.models import (
    BillingCustomer,
    FounderSlot,
    Subscription,
)
from apps.billing.views import (
    _handle_checkout_completed,
    _handle_checkout_expired,
    start_core_checkout,
)


pytestmark = pytest.mark.django_db
User = get_user_model()


def make_user(email):
    return User.objects.create_user(
        email=email,
        password="test-password",
    )


def checkout_request(user):
    request = RequestFactory().post(
        "/billing/checkout/core/"
    )
    request.user = user
    return request


def fake_session(
    *,
    session_id,
    user_id,
    sequence=None,
    token=None,
    subscription_id="sub_test",
):
    metadata = {
        "stewardence_user_id": str(user_id),
        "portfolio": Subscription.Portfolio.CORE,
    }

    if sequence is not None:
        metadata["founder_slot_sequence"] = str(sequence)

    if token is not None:
        metadata["founder_reservation_token"] = str(token)

    return {
        "id": session_id,
        "client_reference_id": str(user_id),
        "subscription": subscription_id,
        "metadata": metadata,
    }


def test_checkout_reserves_before_selecting_founder_price(
    monkeypatch,
    settings,
):
    user = make_user("founder-checkout@example.com")

    settings.STRIPE_SECRET_KEY = "rk_test_placeholder"
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder"
    )
    settings.STRIPE_CORE_STANDARD_PRICE_ID = (
        "price_standard"
    )

    monkeypatch.setattr(
        "apps.billing.views._stripe_client",
        lambda: None,
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.Customer.create",
        lambda **_kwargs: SimpleNamespace(
            id="cus_founder"
        ),
    )

    captured = {}

    def create_session(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            id="cs_founder",
            url="https://checkout.example/founder",
        )

    monkeypatch.setattr(
        "apps.billing.views.stripe.checkout.Session.create",
        create_session,
    )

    response = start_core_checkout(
        checkout_request(user)
    )

    assert response.status_code == 302

    customer = BillingCustomer.objects.get(user=user)
    slot = FounderSlot.objects.get(
        billing_customer=customer
    )

    assert captured["line_items"][0]["price"] == "price_founder"
    assert captured["expires_at"] > 0

    metadata = captured["metadata"]

    assert metadata["founder_slot_sequence"] == str(
        slot.sequence
    )
    assert metadata["founder_reservation_token"] == str(
        slot.reservation_token
    )

    assert (
        captured["subscription_data"]["metadata"]
        == metadata
    )

    slot.refresh_from_db()

    assert (
        slot.stripe_checkout_session_id
        == "cs_founder"
    )


def test_checkout_without_available_slot_uses_standard_price(
    monkeypatch,
    settings,
):
    for number in range(20):
        user = make_user(
            f"claimed-{number}@example.com"
        )
        customer = BillingCustomer.objects.create(
            user=user
        )
        slot = reserve_founder_slot(
            billing_customer_id=customer.id
        )
        slot.claimed_at = slot.reserved_at
        slot.save(update_fields=["claimed_at"])

    user = make_user("customer-21@example.com")

    settings.STRIPE_SECRET_KEY = "rk_test_placeholder"
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder"
    )
    settings.STRIPE_CORE_STANDARD_PRICE_ID = (
        "price_standard"
    )

    monkeypatch.setattr(
        "apps.billing.views._stripe_client",
        lambda: None,
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.Customer.create",
        lambda **_kwargs: SimpleNamespace(
            id="cus_standard"
        ),
    )

    captured = {}

    def create_session(**kwargs):
        captured.update(kwargs)

        return SimpleNamespace(
            id="cs_standard",
            url="https://checkout.example/standard",
        )

    monkeypatch.setattr(
        "apps.billing.views.stripe.checkout.Session.create",
        create_session,
    )

    response = start_core_checkout(
        checkout_request(user)
    )

    assert response.status_code == 302
    assert captured["line_items"][0]["price"] == "price_standard"
    assert "expires_at" not in captured

    assert "founder_slot_sequence" not in captured["metadata"]
    assert (
        "founder_reservation_token"
        not in captured["metadata"]
    )


def test_matching_completed_checkout_claims_founder_slot(
    monkeypatch,
):
    user = make_user("claim-founder@example.com")
    customer = BillingCustomer.objects.create(user=user)

    slot = reserve_founder_slot(
        billing_customer_id=customer.id
    )

    attached = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_claim",
        checkout_expires_at=slot.checkout_expires_at,
    )

    assert attached is True

    schedule_calls = []

    def fake_schedule(*, subscription):
        schedule_calls.append(
            {
                "subscription_id": subscription.stripe_subscription_id,
                "founder_sequence": subscription.founder_sequence,
            }
        )

        return {
            "schedule_id": "sub_sched_test_founder",
            "intro_ends_at": slot.checkout_expires_at,
        }

    monkeypatch.setattr(
        "apps.billing.views.ensure_founder_subscription_schedule",
        fake_schedule,
    )

    session = fake_session(
        session_id="cs_claim",
        user_id=user.id,
        sequence=slot.sequence,
        token=slot.reservation_token,
    )

    _handle_checkout_completed(session)

    subscription = Subscription.objects.get(
        billing_customer=customer
    )

    assert subscription.is_founder is True
    assert subscription.founder_sequence == slot.sequence
    assert subscription.current_price_cents == 4900

    assert (
        subscription.stripe_schedule_id
        == "sub_sched_test_founder"
    )

    assert (
        subscription.founder_intro_ends_at
        == slot.checkout_expires_at
    )

    assert schedule_calls == [
        {
            "subscription_id": "sub_test",
            "founder_sequence": slot.sequence,
        }
    ]

    slot.refresh_from_db()

    assert slot.claimed_at is not None


def test_stale_reservation_token_cannot_claim_founder_slot():
    user = make_user("stale-founder@example.com")
    customer = BillingCustomer.objects.create(user=user)

    slot = reserve_founder_slot(
        billing_customer_id=customer.id
    )

    attached = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_authoritative",
        checkout_expires_at=slot.checkout_expires_at,
    )

    assert attached is True

    stale_session = fake_session(
        session_id="cs_stale",
        user_id=user.id,
        sequence=slot.sequence,
        token=slot.reservation_token,
    )

    with pytest.raises(
        RuntimeError,
        match="could not prove its authoritative reservation",
    ):
        _handle_checkout_completed(stale_session)

    assert (
        Subscription.objects.filter(
            billing_customer=customer
        ).exists()
        is False
    )

    slot.refresh_from_db()

    assert (
        slot.stripe_checkout_session_id
        == "cs_authoritative"
    )

    assert slot.claimed_at is None


def test_matching_expired_checkout_releases_slot():
    user = make_user("expired-founder@example.com")
    customer = BillingCustomer.objects.create(user=user)

    slot = reserve_founder_slot(
        billing_customer_id=customer.id
    )

    attached = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_expired",
        checkout_expires_at=slot.checkout_expires_at,
    )

    assert attached is True

    session = fake_session(
        session_id="cs_expired",
        user_id=user.id,
        sequence=slot.sequence,
        token=slot.reservation_token,
        subscription_id=None,
    )

    _handle_checkout_expired(session)

    slot.refresh_from_db()

    assert slot.billing_customer_id is None
    assert slot.reservation_token is None
    assert slot.stripe_checkout_session_id is None
    assert slot.reserved_at is None
    assert slot.checkout_expires_at is None
    assert slot.claimed_at is None


def test_stale_expiration_cannot_release_newer_reservation():
    user = make_user("stale-expiry@example.com")
    customer = BillingCustomer.objects.create(user=user)

    first = reserve_founder_slot(
        billing_customer_id=customer.id
    )

    first_sequence = first.sequence
    first_token = first.reservation_token

    second = reserve_founder_slot(
        billing_customer_id=customer.id
    )

    attached = attach_founder_checkout_session(
        slot_sequence=second.sequence,
        reservation_token=second.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_current",
        checkout_expires_at=second.checkout_expires_at,
    )

    assert attached is True

    released = release_expired_founder_checkout(
        slot_sequence=first_sequence,
        reservation_token=first_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_old",
    )

    assert released is False

    second.refresh_from_db()

    assert second.billing_customer_id == customer.id
    assert (
        second.stripe_checkout_session_id
        == "cs_current"
    )
    assert second.claimed_at is None


def test_exact_claim_is_idempotent():
    user = make_user("idempotent-claim@example.com")
    customer = BillingCustomer.objects.create(user=user)

    slot = reserve_founder_slot(
        billing_customer_id=customer.id
    )

    attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_repeat",
        checkout_expires_at=slot.checkout_expires_at,
    )

    first = claim_founder_slot(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_repeat",
    )

    second = claim_founder_slot(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_repeat",
    )

    assert first is not None
    assert second is not None
    assert first.sequence == second.sequence


def test_stripe_session_failure_releases_reservation(
    monkeypatch,
    settings,
):
    user = make_user("stripe-failure@example.com")

    settings.STRIPE_SECRET_KEY = "rk_test_placeholder"
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder"
    )
    settings.STRIPE_CORE_STANDARD_PRICE_ID = (
        "price_standard"
    )

    monkeypatch.setattr(
        "apps.billing.views._stripe_client",
        lambda: None,
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.Customer.create",
        lambda **_kwargs: SimpleNamespace(
            id="cus_failure"
        ),
    )

    def fail_session(**_kwargs):
        raise RuntimeError("Stripe unavailable")

    monkeypatch.setattr(
        "apps.billing.views.stripe.checkout.Session.create",
        fail_session,
    )

    with pytest.raises(
        RuntimeError,
        match="Stripe unavailable",
    ):
        start_core_checkout(
            checkout_request(user)
        )

    # The identity transaction rolls back both the new customer and its
    # reservation when Stripe fails. No slot remains allocated to this user.
    assert not BillingCustomer.objects.filter(user=user).exists()
    assert not FounderSlot.objects.filter(
        billing_customer__user=user
    ).exists()
