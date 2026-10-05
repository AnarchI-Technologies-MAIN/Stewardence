"""A committed canceled external generation cannot be revived by checkout replay."""

from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model

from apps.billing.founder_slots import (
    attach_founder_checkout_session,
    claim_founder_slot,
    reserve_founder_slot,
)
from apps.billing.models import BillingCustomer, Subscription
from apps.billing.views import _handle_checkout_completed
from tests.stripe_fixtures import configure_paid_core_checkout

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("probe_early_effects", [True, False])
def test_canceled_founder_generation_rejects_exact_claimed_checkout_replay(
    settings, monkeypatch, probe_early_effects
):
    user = get_user_model().objects.create_user(
        email="terminal-founder@example.invalid"
    )
    customer = BillingCustomer.objects.create(user=user)
    slot = reserve_founder_slot(billing_customer_id=customer.id)
    assert attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_terminal",
        checkout_expires_at=slot.checkout_expires_at,
    )
    session = {
        "id": "cs_terminal",
        "client_reference_id": str(user.id),
        "subscription": "sub_terminal",
        "metadata": {
            "founder_slot_sequence": str(slot.sequence),
            "founder_reservation_token": str(slot.reservation_token),
        },
    }
    authoritative = configure_paid_core_checkout(
        monkeypatch, settings, customer, session
    )
    schedule = Mock(
        return_value={
            "schedule_id": "sched_terminal",
            "intro_ends_at": slot.checkout_expires_at,
        }
    )
    monkeypatch.setattr(
        "apps.billing.views.ensure_founder_subscription_schedule", schedule
    )
    _handle_checkout_completed(session)
    subscription = Subscription.objects.get(billing_customer=customer)
    slot.refresh_from_db()
    assert slot.claimed_at is not None
    assert subscription.is_founder
    subscription.status = Subscription.Status.CANCELED
    subscription.is_founder = False
    subscription.founder_sequence = None
    subscription.founder_intro_ends_at = None
    subscription.stripe_schedule_id = None
    subscription.save()
    before = Subscription.objects.filter(pk=subscription.pk).values().get()
    claimed_at = slot.claimed_at
    schedule.reset_mock()
    retrieve = Mock(return_value=authoritative)
    claim = Mock(wraps=claim_founder_slot)
    if probe_early_effects:
        claim.side_effect = AssertionError("Terminal checkout reached founder issuance")
    monkeypatch.setattr("apps.billing.views._retrieve_core_subscription", retrieve)
    monkeypatch.setattr("apps.billing.views.claim_founder_slot", claim)
    if probe_early_effects:
        with pytest.raises(
            RuntimeError, match="canceled.*generation|terminal.*generation"
        ):
            _handle_checkout_completed(session)
        retrieve.assert_not_called()
        claim.assert_not_called()
        schedule.assert_not_called()
    if not probe_early_effects:
        try:
            _handle_checkout_completed(session)
        except RuntimeError as error:
            assert "generation" in str(error)
    assert Subscription.objects.filter(pk=subscription.pk).values().get() == before
    slot.refresh_from_db()
    assert slot.claimed_at == claimed_at


def test_canceled_generation_allows_new_different_standard_subscription(
    settings, monkeypatch
):
    user = get_user_model().objects.create_user(
        email="terminal-standard@example.invalid"
    )
    customer = BillingCustomer.objects.create(user=user)
    subscription = Subscription.objects.create(
        billing_customer=customer,
        stripe_subscription_id="sub_old_canceled",
        status=Subscription.Status.CANCELED,
        portfolio=Subscription.Portfolio.CORE,
    )
    session = {
        "id": "cs_fresh_standard",
        "client_reference_id": str(user.id),
        "subscription": "sub_fresh_standard",
        "metadata": {},
    }
    configure_paid_core_checkout(monkeypatch, settings, customer, session)
    schedule = Mock(
        side_effect=AssertionError(
            "Fresh standard subscription issued founder schedule"
        )
    )
    monkeypatch.setattr(
        "apps.billing.views.ensure_founder_subscription_schedule", schedule
    )
    _handle_checkout_completed(session)
    subscription.refresh_from_db()
    assert subscription.status == Subscription.Status.ACTIVE
    assert subscription.stripe_subscription_id == "sub_fresh_standard"
    assert not subscription.is_founder
    assert subscription.current_price_cents == 9900
    schedule.assert_not_called()
