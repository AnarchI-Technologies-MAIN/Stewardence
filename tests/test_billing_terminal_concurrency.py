"""Real PostgreSQL stale-observation attack against canceled projection."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic

import pytest
from django.db import connections

from agentledger.tenancy.context import identity_transaction
from apps.billing import views
from apps.billing.models import Subscription
from tests.test_billing_portal_cancellation import (
    make_subscription,
    stripe_subscription,
)

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.mark.parametrize("incoming_status", ["active", "trialing"])
@pytest.mark.parametrize("contender_count", [1, 2, 4, 8])
def test_committed_deletion_cannot_be_overwritten_by_stale_update(
    monkeypatch, incoming_status, contender_count
):
    assert connections["default"].vendor == "postgresql"
    user, _, subscription = make_subscription(
        email=f"race-{incoming_status}-{contender_count}@example.invalid"
    )
    observed = Event()
    resume = Event()
    deletion_started = Event()
    deletion_committed = Event()
    identifiers = {}
    started = {f"update-{index}": Event() for index in range(contender_count)}
    original_contract = views.subscription_price_contract

    def pause_after_subscription_read(payload):
        observed.set()
        assert resume.wait(15), "Updater was not released"
        return original_contract(payload)

    monkeypatch.setattr(
        views, "subscription_price_contract", pause_after_subscription_read
    )

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
                if kind.startswith("update-"):
                    started[kind].set()
                    views._handle_subscription_updated(
                        stripe_subscription(
                            cancel_at_period_end=False, status=incoming_status
                        )
                    )
                if kind == "delete":
                    deletion_started.set()
                    views._handle_subscription_deleted(
                        stripe_subscription(
                            cancel_at_period_end=False, status="canceled"
                        )
                    )
            if kind == "delete":
                deletion_committed.set()
        finally:
            connections["default"].close()

    with ThreadPoolExecutor(max_workers=contender_count + 1) as executor:
        updaters = [executor.submit(invoke, "update-0")]
        try:
            assert observed.wait(10), "Updater never observed subscription"
            updaters.extend(
                executor.submit(invoke, f"update-{index}")
                for index in range(1, contender_count)
            )
            for event in started.values():
                assert event.wait(10), (
                    "Contender did not establish its role and isolation"
                )
            deleter = executor.submit(invoke, "delete")
            assert deletion_started.wait(10), "Deletion did not start"
            deadline = monotonic() + 10
            blocked = False
            while not deletion_committed.is_set() and monotonic() < deadline:
                with connections["default"].cursor() as cursor:
                    cursor.execute(
                        "WITH RECURSIVE blockers(pid, path) AS ("
                        " SELECT %s::integer, ARRAY[%s::integer]"
                        " UNION ALL"
                        " SELECT next.pid, blockers.path || next.pid"
                        " FROM blockers CROSS JOIN LATERAL"
                        " unnest(pg_blocking_pids(blockers.pid)) AS next(pid)"
                        " WHERE cardinality(blockers.path) < 16"
                        " AND NOT next.pid = ANY(blockers.path)"
                        ") SELECT EXISTS(SELECT 1 FROM blockers WHERE pid = %s)",
                        [
                            identifiers["delete"],
                            identifiers["delete"],
                            identifiers["update-0"],
                        ],
                    )
                    blocked = cursor.fetchone()[0]
                if blocked:
                    break
            assert deletion_committed.is_set() or blocked, (
                "Neither committed deletion nor a proven row-lock wait occurred"
            )
            # Subsequent updaters cannot all reach the after-read barrier while
            # the first owns the fixed row lock. Verify their actual DB waits.
            if blocked:
                deadline = monotonic() + 10
                waiting = set()
                while len(waiting) < contender_count - 1 and monotonic() < deadline:
                    for index in range(1, contender_count):
                        with connections["default"].cursor() as cursor:
                            cursor.execute(
                                "SELECT cardinality(pg_blocking_pids(%s)) > 0",
                                [identifiers[f"update-{index}"]],
                            )
                            if cursor.fetchone()[0]:
                                waiting.add(index)
                assert waiting == set(range(1, contender_count)), (
                    "A contender never reached a proven PostgreSQL lock wait"
                )
        finally:
            resume.set()
        for updater in updaters:
            updater.result(timeout=25)
        deleter.result(timeout=25)

    assert len(identifiers) == contender_count + 1
    assert len(set(identifiers.values())) == contender_count + 1

    subscription.refresh_from_db()
    assert subscription.status == Subscription.Status.CANCELED
    assert not subscription.grants_access
    assert not subscription.is_founder
