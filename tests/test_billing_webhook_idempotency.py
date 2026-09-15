from __future__ import annotations

import pytest
from django.test import RequestFactory

from apps.billing.models import StripeWebhookEvent
from apps.billing.views import stripe_webhook


pytestmark = pytest.mark.django_db


def stripe_event(
    event_id,
    event_type="checkout.session.completed",
):
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": "stripe-object-id",
            },
        },
    }


def webhook_request():
    return RequestFactory().post(
        "/billing/webhook/stripe/",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="test-signature",
    )


def configure_signed_event(
    monkeypatch,
    settings,
    event,
):
    settings.STRIPE_SECRET_KEY = "rk_test_placeholder"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_placeholder"

    monkeypatch.setattr(
        "apps.billing.views._stripe_client",
        lambda: None,
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.Webhook.construct_event",
        lambda **_kwargs: event,
    )


def test_duplicate_event_runs_handler_exactly_once(
    monkeypatch,
    settings,
):
    event = stripe_event("evt_duplicate")
    calls = []

    configure_signed_event(
        monkeypatch,
        settings,
        event,
    )

    monkeypatch.setattr(
        "apps.billing.views._handle_checkout_completed",
        lambda obj: calls.append(obj["id"]),
    )

    first = stripe_webhook(webhook_request())
    second = stripe_webhook(webhook_request())

    assert first.status_code == 200
    assert second.status_code == 200

    assert calls == [
        "stripe-object-id",
    ]

    receipts = list(
        StripeWebhookEvent.objects.all()
    )

    assert len(receipts) == 1
    assert receipts[0].stripe_event_id == "evt_duplicate"
    assert (
        receipts[0].event_type
        == "checkout.session.completed"
    )


def test_handler_failure_rolls_back_receipt_and_allows_retry(
    monkeypatch,
    settings,
):
    event = stripe_event("evt_retry")
    calls = []

    configure_signed_event(
        monkeypatch,
        settings,
        event,
    )

    def fail_once(_obj):
        calls.append("failed")
        raise RuntimeError("processing failed")

    monkeypatch.setattr(
        "apps.billing.views._handle_checkout_completed",
        fail_once,
    )

    with pytest.raises(
        RuntimeError,
        match="processing failed",
    ):
        stripe_webhook(webhook_request())

    assert StripeWebhookEvent.objects.count() == 0

    monkeypatch.setattr(
        "apps.billing.views._handle_checkout_completed",
        lambda _obj: calls.append("succeeded"),
    )

    response = stripe_webhook(webhook_request())

    assert response.status_code == 200

    assert calls == [
        "failed",
        "succeeded",
    ]

    assert StripeWebhookEvent.objects.count() == 1

    receipt = StripeWebhookEvent.objects.get()

    assert receipt.stripe_event_id == "evt_retry"


def test_different_event_ids_process_independently(
    monkeypatch,
    settings,
):
    current = {
        "event": stripe_event("evt_first"),
    }
    calls = []

    settings.STRIPE_SECRET_KEY = "rk_test_placeholder"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_placeholder"

    monkeypatch.setattr(
        "apps.billing.views._stripe_client",
        lambda: None,
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.Webhook.construct_event",
        lambda **_kwargs: current["event"],
    )

    monkeypatch.setattr(
        "apps.billing.views._handle_checkout_completed",
        lambda obj: calls.append(obj["id"]),
    )

    first = stripe_webhook(webhook_request())

    current["event"] = stripe_event("evt_second")

    second = stripe_webhook(webhook_request())

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 2
    assert StripeWebhookEvent.objects.count() == 2

    assert set(
        StripeWebhookEvent.objects.values_list(
            "stripe_event_id",
            flat=True,
        )
    ) == {
        "evt_first",
        "evt_second",
    }


def test_unknown_signed_event_is_receipted_once(
    monkeypatch,
    settings,
):
    event = stripe_event(
        "evt_unknown",
        "customer.created",
    )

    configure_signed_event(
        monkeypatch,
        settings,
        event,
    )

    first = stripe_webhook(webhook_request())
    second = stripe_webhook(webhook_request())

    assert first.status_code == 200
    assert second.status_code == 200

    assert StripeWebhookEvent.objects.count() == 1

    receipt = StripeWebhookEvent.objects.get()

    assert receipt.stripe_event_id == "evt_unknown"
    assert receipt.event_type == "customer.created"


@pytest.mark.parametrize(
    "event",
    [
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {},
            },
        },
        {
            "id": "evt_missing_type",
            "data": {
                "object": {},
            },
        },
    ],
)
def test_missing_stripe_event_identity_fails_closed(
    monkeypatch,
    settings,
    event,
):
    configure_signed_event(
        monkeypatch,
        settings,
        event,
    )

    response = stripe_webhook(webhook_request())

    assert response.status_code == 400
    assert StripeWebhookEvent.objects.count() == 0
