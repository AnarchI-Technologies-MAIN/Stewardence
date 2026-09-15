from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections
from django.test import RequestFactory

from apps.billing.models import StripeWebhookEvent
from apps.billing.views import stripe_webhook


pytestmark = pytest.mark.django_db(transaction=True)


def webhook_request():
    return RequestFactory().post(
        "/billing/webhook/stripe/",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="concurrent-signature",
    )


def test_simultaneous_duplicate_delivery_runs_handler_once(
    monkeypatch,
    settings,
):
    settings.STRIPE_SECRET_KEY = "rk_test_placeholder"
    settings.STRIPE_WEBHOOK_SECRET = "whsec_test_placeholder"

    event = {
        "id": "evt_concurrent_duplicate",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_concurrent_duplicate",
            },
        },
    }

    calls = []
    calls_lock = threading.Lock()
    start_barrier = threading.Barrier(2)

    monkeypatch.setattr(
        "apps.billing.views._stripe_client",
        lambda: None,
    )

    monkeypatch.setattr(
        "apps.billing.views.stripe.Webhook.construct_event",
        lambda **_kwargs: event,
    )

    def handler(obj):
        with calls_lock:
            calls.append(obj["id"])

        # Keep the winning transaction open briefly so the second
        # delivery actually contends on the unique Stripe event ID.
        time.sleep(0.25)

    monkeypatch.setattr(
        "apps.billing.views._handle_checkout_completed",
        handler,
    )

    def deliver():
        close_old_connections()

        try:
            start_barrier.wait(timeout=5)
            response = stripe_webhook(webhook_request())
            return response.status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(deliver),
            executor.submit(deliver),
        ]

        statuses = [
            future.result(timeout=15)
            for future in futures
        ]

    assert sorted(statuses) == [200, 200]

    assert calls == [
        "cs_concurrent_duplicate",
    ]

    receipts = list(
        StripeWebhookEvent.objects.filter(
            stripe_event_id="evt_concurrent_duplicate",
        )
    )

    assert len(receipts) == 1

    receipt = receipts[0]

    assert (
        receipt.event_type
        == "checkout.session.completed"
    )
