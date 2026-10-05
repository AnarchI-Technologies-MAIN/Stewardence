from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from django.contrib.auth import get_user_model
from django.db import close_old_connections

from apps.billing.founder_slots import reserve_founder_slot
from apps.billing.models import BillingCustomer, FounderSlot


pytestmark = pytest.mark.django_db(transaction=True)

User = get_user_model()


def _reserve(customer_id, barrier):
    close_old_connections()

    try:
        barrier.wait(timeout=10)

        slot = reserve_founder_slot(
            billing_customer_id=customer_id,
        )

        if slot is None:
            return None

        return slot.sequence
    finally:
        close_old_connections()


def test_twenty_five_simultaneous_customers_never_exceed_twenty_slots():
    customer_ids = []

    for number in range(25):
        user = User.objects.create_user(
            email=f"founder-race-{number}@example.com",
        )

        customer = BillingCustomer.objects.create(
            user=user,
        )

        customer_ids.append(customer.id)

    barrier = threading.Barrier(len(customer_ids))

    with ThreadPoolExecutor(
        max_workers=len(customer_ids),
    ) as executor:
        futures = [
            executor.submit(
                _reserve,
                customer_id,
                barrier,
            )
            for customer_id in customer_ids
        ]

        results = [
            future.result(timeout=30)
            for future in futures
        ]

    allocated = sorted(
        result
        for result in results
        if result is not None
    )

    rejected = [
        result
        for result in results
        if result is None
    ]

    assert allocated == list(range(1, 21))
    assert len(set(allocated)) == 20
    assert len(rejected) == 5

    assert FounderSlot.objects.count() == 20
    assert (
        FounderSlot.objects
        .exclude(billing_customer__isnull=True)
        .count()
        == 20
    )


def test_same_customer_concurrently_receives_only_one_slot():
    user = User.objects.create_user(
        email="same-founder-customer@example.com",
    )

    customer = BillingCustomer.objects.create(
        user=user,
    )

    barrier = threading.Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                _reserve,
                customer.id,
                barrier,
            ),
            executor.submit(
                _reserve,
                customer.id,
                barrier,
            ),
        ]

        results = [
            future.result(timeout=20)
            for future in futures
        ]

    assert results[0] == results[1]
    assert results[0] == 1

    assert (
        FounderSlot.objects.filter(
            billing_customer=customer,
        ).count()
        == 1
    )

    assert (
        FounderSlot.objects
        .exclude(billing_customer__isnull=True)
        .count()
        == 1
    )


def test_twenty_first_sequential_customer_receives_no_slot():
    customers = []

    for number in range(21):
        user = User.objects.create_user(
            email=f"founder-sequential-{number}@example.com",
        )

        customers.append(
            BillingCustomer.objects.create(
                user=user,
            )
        )

    results = [
        reserve_founder_slot(
            billing_customer_id=customer.id,
        )
        for customer in customers
    ]

    assert [
        slot.sequence
        for slot in results[:20]
    ] == list(range(1, 21))

    assert results[20] is None
    assert FounderSlot.objects.count() == 20
