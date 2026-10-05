from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.billing.founder_slots import (
    attach_founder_checkout_session,
    reserve_founder_slot,
)
from apps.billing.models import BillingCustomer


pytestmark = pytest.mark.django_db
User = get_user_model()


def make_user(email):
    return User.objects.create_user(
        email=email,
        password="test-password",
    )


def test_repeat_reservation_preserves_generation():
    user = make_user("stable-generation@example.com")

    customer = BillingCustomer.objects.create(
        user=user,
    )

    first = reserve_founder_slot(
        billing_customer_id=customer.id,
    )

    second = reserve_founder_slot(
        billing_customer_id=customer.id,
    )

    assert second.sequence == first.sequence
    assert second.reservation_token == first.reservation_token


def test_first_session_attachment_wins_but_same_id_is_idempotent():
    user = make_user("attachment-winner@example.com")

    customer = BillingCustomer.objects.create(
        user=user,
    )

    slot = reserve_founder_slot(
        billing_customer_id=customer.id,
    )

    first = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_authoritative",
        checkout_expires_at=slot.checkout_expires_at,
    )

    repeated = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_authoritative",
        checkout_expires_at=slot.checkout_expires_at,
    )

    loser = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_other",
        checkout_expires_at=slot.checkout_expires_at,
    )

    assert first is True
    assert repeated is True
    assert loser is False

    slot.refresh_from_db()

    assert (
        slot.stripe_checkout_session_id
        == "cs_authoritative"
    )


def test_checkout_creation_uses_reservation_idempotency_key(
    client,
    monkeypatch,
    settings,
):
    monkeypatch.setattr(
        "apps.billing.views.settings.STRIPE_SECRET_KEY",
        "sk_test_stewardence_unit_only",
    )

    user = make_user("checkout-idempotency@example.com")

    BillingCustomer.objects.create(
        user=user,
        stripe_customer_id="cus_checkout_idempotency",
    )

    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = (
        "price_founder_intro"
    )

    captured = []

    def fake_create(**kwargs):
        captured.append(kwargs)

        return SimpleNamespace(
            id="cs_same_generation",
            url="https://checkout.stripe.test/same",
        )

    monkeypatch.setattr(
        "apps.billing.views.stripe.checkout.Session.create",
        fake_create,
    )

    client.force_login(user)

    first = client.post(
        reverse("billing:checkout-core")
    )

    assert first.status_code == 302

    customer = BillingCustomer.objects.get(
        user=user,
    )

    slot = reserve_founder_slot(
        billing_customer_id=customer.id,
    )

    expected_key = (
        "stewardence-founder-checkout:"
        f"{slot.reservation_token}"
    )

    assert captured[0]["idempotency_key"] == expected_key


def test_repeat_checkout_reuses_open_session(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "apps.billing.views.settings.STRIPE_SECRET_KEY",
        "sk_test_stewardence_unit_only",
    )

    user = make_user("reuse-session@example.com")

    customer = BillingCustomer.objects.create(
        user=user,
        stripe_customer_id="cus_reuse_session",
    )

    slot = reserve_founder_slot(
        billing_customer_id=customer.id,
    )

    attached = attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_existing",
        checkout_expires_at=slot.checkout_expires_at,
    )

    assert attached is True

    create_calls = []

    monkeypatch.setattr(
        "apps.billing.views.stripe.checkout.Session.retrieve",
        lambda session_id: {
            "id": session_id,
            "status": "open",
            "url": "https://checkout.stripe.test/existing",
        },
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.checkout.Session.create",
        lambda **kwargs: create_calls.append(kwargs),
    )

    client.force_login(user)

    response = client.post(
        reverse("billing:checkout-core")
    )

    assert response.status_code == 302
    assert (
        response["Location"]
        == "https://checkout.stripe.test/existing"
    )

    assert create_calls == []
