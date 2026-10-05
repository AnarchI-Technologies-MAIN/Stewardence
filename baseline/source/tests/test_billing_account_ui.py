from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from apps.billing.models import Subscription
from apps.billing.views import (
    billing_account,
    founder_cancel,
    founder_cancel_undo,
)


class FakeUser:
    id = 1001
    email = "proof@example.com"
    is_authenticated = True

    def get_short_name(self):
        return "Proof"


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


def fake_billing_customer():
    return SimpleNamespace(
        stripe_customer_id="cus_test_proof"
    )


def make_subscription(
    *,
    founder,
    status,
    cancel_at_period_end,
):
    return SimpleNamespace(
        is_founder=founder,
        status=status,
        cancel_at_period_end=cancel_at_period_end,
        grants_access=True,
        current_price_cents=4900 if founder else 9900,
        current_period_end=None,
        get_status_display=lambda: status.title(),
        get_portfolio_display=lambda: "Core",
    )


def render_account(
    *,
    subscription,
):
    request = RequestFactory().get(
        "/billing/account/"
    )

    request.user = FakeUser()

    with patch(
        "apps.billing.views._subscription_for_user",
        return_value=subscription,
    ):
        with patch(
            "apps.billing.views."
            "BillingCustomer.objects.filter",
            return_value=FakeQuery(
                fake_billing_customer()
            ),
        ):
            # Presentation tests mock their queries and transaction context.
            # The POST guard tests below keep the real context untouched.
            with patch(
                "apps.billing.security.identity_transaction",
                side_effect=lambda _user_id: nullcontext(),
            ):
                response = billing_account(request)

    return (
        response,
        response.content.decode("utf-8"),
    )


def test_billing_account_requires_login():
    request = RequestFactory().get(
        "/billing/account/"
    )

    request.user = AnonymousUser()

    response = billing_account(
        request
    )

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


def test_standard_subscriber_sees_manage_billing_only():
    subscription = make_subscription(
        founder=False,
        status=Subscription.Status.ACTIVE,
        cancel_at_period_end=False,
    )

    response, body = render_account(
        subscription=subscription
    )

    assert response.status_code == 200
    assert "Manage billing" in body
    assert "Cancel at period end" not in body
    assert "Keep my subscription" not in body


def test_active_founder_sees_cancel_not_undo():
    subscription = make_subscription(
        founder=True,
        status=Subscription.Status.ACTIVE,
        cancel_at_period_end=False,
    )

    response, body = render_account(
        subscription=subscription
    )

    assert response.status_code == 200
    assert "Manage billing" in body
    assert "Cancel at period end" in body
    assert "Keep my subscription" not in body


def test_canceling_founder_sees_undo_not_cancel():
    subscription = make_subscription(
        founder=True,
        status=Subscription.Status.CANCELING,
        cancel_at_period_end=True,
    )

    response, body = render_account(
        subscription=subscription
    )

    assert response.status_code == 200
    assert "Manage billing" in body
    assert "Keep my subscription" in body
    assert "Cancel at period end" not in body


def test_founder_cancel_is_post_only():
    request = RequestFactory().get(
        "/billing/founder/cancel/"
    )

    request.user = FakeUser()

    response = founder_cancel(
        request
    )

    assert response.status_code == 405


def test_founder_cancel_undo_is_post_only():
    request = RequestFactory().get(
        "/billing/founder/cancel/undo/"
    )

    request.user = FakeUser()

    response = founder_cancel_undo(
        request
    )

    assert response.status_code == 405
