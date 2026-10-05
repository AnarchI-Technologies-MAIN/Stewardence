"""Checkout stale observations versus real-role PostgreSQL deletion commits."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import connections

from agentledger.tenancy.context import identity_transaction
from apps.billing import views
from apps.billing.founder_slots import (
    attach_founder_checkout_session,
    reserve_founder_slot,
)
from apps.billing.models import BillingCustomer, Subscription
from tests.stripe_fixtures import configure_paid_core_checkout

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def test_deletion_serializes_with_old_founder_checkout_observation(
    settings, monkeypatch
):
    assert connections["default"].vendor == "postgresql"
    user = get_user_model().objects.create_user(email="checkout-race@example.invalid")
    customer = BillingCustomer.objects.create(user=user)
    slot = reserve_founder_slot(billing_customer_id=customer.id)
    assert attach_founder_checkout_session(
        slot_sequence=slot.sequence,
        reservation_token=slot.reservation_token,
        billing_customer_id=customer.id,
        stripe_checkout_session_id="cs_checkout_race",
        checkout_expires_at=slot.checkout_expires_at,
    )
    session = {
        "id": "cs_checkout_race",
        "client_reference_id": str(user.id),
        "subscription": "sub_checkout_race",
        "metadata": {
            "founder_slot_sequence": str(slot.sequence),
            "founder_reservation_token": str(slot.reservation_token),
        },
    }
    authoritative = configure_paid_core_checkout(
        monkeypatch, settings, customer, session
    )
    monkeypatch.setattr(
        views,
        "ensure_founder_subscription_schedule",
        Mock(
            return_value={
                "schedule_id": "sched_checkout_race",
                "intro_ends_at": slot.checkout_expires_at,
            }
        ),
    )
    views._handle_checkout_completed(session)
    observed, resume, delete_started, delete_committed = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    identifiers = {}

    def paused_provider(external_id):
        assert external_id == session["subscription"]
        observed.set()
        assert resume.wait(15), "Checkout observation barrier was not released"
        return authoritative

    monkeypatch.setattr(views, "_retrieve_core_subscription", paused_provider)

    def invoke(kind):
        try:
            with identity_transaction(user.id):
                with connections["default"].cursor() as cursor:
                    cursor.execute("SET LOCAL ROLE agentledger_app")
                    cursor.execute("SET LOCAL statement_timeout = '20s'")
                    cursor.execute(
                        "SELECT current_user, pg_backend_pid(), "
                        "current_setting('transaction_isolation')"
                    )
                    role, pid, isolation = cursor.fetchone()
                    assert role == "agentledger_app"
                    assert isolation == "read committed"
                    identifiers[kind] = pid
                if kind == "checkout":
                    views._handle_checkout_completed(session)
                if kind == "delete":
                    delete_started.set()
                    views._handle_subscription_deleted(
                        {"id": session["subscription"], "status": "canceled"}
                    )
            if kind == "delete":
                delete_committed.set()
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        checkout = executor.submit(invoke, "checkout")
        try:
            assert observed.wait(10), (
                "Checkout never reached its post-observation provider barrier"
            )
            deletion = executor.submit(invoke, "delete")
            assert delete_started.wait(10), (
                "Deletion never established its app-role connection"
            )
            deadline = monotonic() + 10
            blocked = False
            while not delete_committed.is_set() and monotonic() < deadline:
                with connections["default"].cursor() as cursor:
                    cursor.execute(
                        "WITH RECURSIVE blockers(pid,path) AS ("
                        " SELECT %s::integer, ARRAY[%s::integer] UNION ALL"
                        " SELECT next.pid, blockers.path || next.pid FROM blockers"
                        " CROSS JOIN LATERAL "
                        "unnest(pg_blocking_pids(blockers.pid)) AS next(pid)"
                        " WHERE cardinality(blockers.path) < 16 "
                        "AND NOT next.pid = ANY(blockers.path)"
                        ") SELECT EXISTS(SELECT 1 FROM blockers WHERE pid = %s)",
                        [
                            identifiers["delete"],
                            identifiers["delete"],
                            identifiers["checkout"],
                        ],
                    )
                    blocked = cursor.fetchone()[0]
                if blocked:
                    break
            assert delete_committed.is_set() or blocked, (
                "Neither deletion commit nor blocker chain was proven"
            )
        finally:
            resume.set()
        checkout.result(timeout=25)
        deletion.result(timeout=25)
    assert delete_committed.is_set()
    assert identifiers["delete"] != identifiers["checkout"]
    subscription = Subscription.objects.get(billing_customer=customer)
    assert subscription.status == Subscription.Status.CANCELED
    assert not subscription.is_founder
    assert subscription.stripe_schedule_id is None
    assert subscription.founder_intro_ends_at is None
