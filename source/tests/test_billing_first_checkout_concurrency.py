"""Competing initial generations serialize on a pre-existing customer row.

Provider admission is stubbed here; exact invoice admission is tested separately.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from django.utils import timezone

from agentledger.tenancy.context import identity_transaction
from apps.billing import views
from apps.billing.models import BillingCustomer, Subscription

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def test_competing_first_completions_cannot_replace_uncovered_generation(monkeypatch):
    user = get_user_model().objects.create_user(email="first-race@example.invalid")
    customer = BillingCustomer.objects.create(user=user, stripe_customer_id="cus_first")
    observed, release, second_started = Event(), Event(), Event()
    backend_ids = {}

    def verified_provider(session, billing_customer):
        assert billing_customer.id == customer.id
        if session["subscription"] == "sub_first":
            observed.set()
            assert release.wait(15)
        return {"current_period_end": int(timezone.now().timestamp()) + 3600}

    monkeypatch.setattr(views, "_validate_core_checkout", verified_provider)

    def invoke(external):
        try:
            with identity_transaction(user.id):
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET LOCAL ROLE agentledger_app")
                    cursor.execute("SET LOCAL statement_timeout='20s'")
                    cursor.execute("SELECT current_user, pg_backend_pid()")
                    role, backend_ids[external] = cursor.fetchone()
                    assert role == "agentledger_app"
                if external == "sub_second":
                    second_started.set()
                views._handle_checkout_completed(
                    {
                        "id": "cs_" + external,
                        "client_reference_id": str(user.id),
                        "subscription": external,
                        "payment_status": "paid",
                        "metadata": {"portfolio": "core"},
                    }
                )
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(invoke, "sub_first")
        try:
            assert observed.wait(10)
            assert not Subscription.objects.filter(billing_customer=customer).exists()
            second = executor.submit(invoke, "sub_second")
            assert second_started.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with connections["default"].cursor() as cursor:
                    cursor.execute(
                        "SELECT %s = ANY(pg_blocking_pids(%s))",
                        [backend_ids["sub_first"], backend_ids["sub_second"]],
                    )
                    blocked = cursor.fetchone()[0]
                if blocked:
                    break
            assert blocked, "Competing absent-row completion did not serialize"
        finally:
            release.set()
        first.result(timeout=25)
        with pytest.raises(RuntimeError, match="cannot be replaced"):
            second.result(timeout=25)

    subscription = Subscription.objects.get(billing_customer=customer)
    assert subscription.stripe_subscription_id == "sub_first"
    assert not subscription.grants_access  # No invoice authority issued by this stub.
