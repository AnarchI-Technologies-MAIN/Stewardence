"""A canceled subscription generation cannot be revived by later events."""

import pytest

from apps.billing.models import Subscription
from apps.billing.views import (
    _handle_invoice_paid,
    _handle_invoice_payment_failed,
    _handle_subscription_deleted,
    _handle_subscription_updated,
)
from tests.test_billing_portal_cancellation import (
    make_subscription,
    stripe_subscription,
)

pytestmark = pytest.mark.django_db


def test_deleted_generation_stays_canceled_after_failed_then_paid_invoice():
    _, _, subscription = make_subscription(email="terminal-invoice@example.invalid")
    _handle_subscription_deleted(
        stripe_subscription(cancel_at_period_end=False, status="canceled")
    )
    invoice = {"subscription": "sub_test"}
    _handle_invoice_payment_failed(invoice)
    _handle_invoice_paid(invoice)
    subscription.refresh_from_db()
    assert subscription.status == Subscription.Status.CANCELED
    assert not subscription.grants_access
    assert not subscription.is_founder


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_deleted_generation_stays_canceled_after_subscription_update(status):
    _, _, subscription = make_subscription(email=f"terminal-{status}@example.invalid")
    _handle_subscription_deleted(
        stripe_subscription(cancel_at_period_end=False, status="canceled")
    )
    _handle_subscription_updated(
        stripe_subscription(cancel_at_period_end=False, status=status)
    )
    subscription.refresh_from_db()
    assert subscription.status == Subscription.Status.CANCELED
    assert not subscription.grants_access
    assert not subscription.is_founder
