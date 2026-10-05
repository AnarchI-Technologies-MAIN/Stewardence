"""Real routed requests and independent committed-row observation; Stripe mocked."""

from contextlib import contextmanager

import pytest
from django.db import connections
from django.urls import reverse

from apps.billing import standard_checkout_flow as flow
from apps.billing.models import BillingCustomerRequest, CheckoutIntent
from tests.test_standard_checkout_flow import setup as checkout_setup

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture(name="setup")
def routed_setup(settings, monkeypatch):
    return checkout_setup.__wrapped__(settings, monkeypatch)


@contextmanager
def actual_app_default():
    original = connections["default"]
    app = connections["app_runtime"]
    connections["default"] = app
    try:
        yield
    finally:
        app.close()
        connections["default"] = original


def observe_before_writes(setup, monkeypatch):
    client = flow._client("synthetic-unused-value")
    observed = []
    for stage, service in [
        ("customer", client.v1.customers),
        ("session", client.v1.checkout.sessions),
    ]:
        original = service.create

        def wrapped(*, params, options, stage=stage, original=original):
            assert not connections["default"].in_atomic_block
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT current_user,pg_backend_pid()")
                role, writer_pid = cursor.fetchone()
                assert role == "agentledger_app"
            with connections["owner_runtime"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                assert cursor.fetchone()[0] != writer_pid
            request = BillingCustomerRequest.objects.using("owner_runtime").get(
                owner_id=setup[0].id
            )
            if stage == "customer":
                assert request.idempotency_key == options["idempotency_key"]
                assert request.params == params
            if stage == "session":
                intent = CheckoutIntent.objects.using("owner_runtime").get(
                    owner_id=setup[0].id
                )
                assert (
                    intent.params == params
                    and intent.idempotency_key == options["idempotency_key"]
                )
            observed.append(stage)
            return original(params=params, options=options)

        monkeypatch.setattr(service, "create", wrapped)
    return observed


@pytest.mark.parametrize("lost_stage", [None, "customer", "session"])
def test_routed_post_commits_frozen_requests_before_provider_write(
    client, setup, settings, monkeypatch, lost_stage
):
    settings.FOUNDER_OFFER_ENABLED = False
    settings.ALLOWED_HOSTS = ["testserver"]
    client.force_login(setup[0])
    observed = observe_before_writes(setup, monkeypatch)
    if lost_stage:
        setup[2][lost_stage] = True
    with actual_app_default():
        first = client.post(reverse("billing:checkout-core"))
        if lost_stage:
            assert first.status_code == 503
            assert (
                BillingCustomerRequest.objects.using("owner_runtime")
                .filter(owner_id=setup[0].id)
                .count()
                == 1
            )
            if lost_stage == "session":
                assert (
                    CheckoutIntent.objects.using("owner_runtime")
                    .filter(owner_id=setup[0].id)
                    .count()
                    == 1
                )
            second = client.post(reverse("billing:checkout-core"))
        if lost_stage is None:
            second = first
        assert second.status_code == 302
        assert second["Location"] == "https://checkout.stripe.com/c/pay/qualification"
    assert "customer" in observed and "session" in observed
    assert BillingCustomerRequest.objects.count() == CheckoutIntent.objects.count() == 1
    if lost_stage:
        assert setup[1][lost_stage][0] == setup[1][lost_stage][1]


def test_routed_closed_gate_does_not_call_provider(
    client, setup, settings, monkeypatch
):
    settings.FOUNDER_OFFER_ENABLED = False
    settings.STANDARD_CHECKOUT_INTENTS_ENABLED = False
    client.force_login(setup[0])
    monkeypatch.setattr(
        flow, "_client", lambda key: pytest.fail("Closed gate reached provider client")
    )
    with actual_app_default():
        response = client.post(reverse("billing:checkout-core"))
    assert response.status_code == 503
    assert not BillingCustomerRequest.objects.exists()
    assert not CheckoutIntent.objects.exists()
