from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from django.db import close_old_connections, connections

from agentledger.tenancy.context import tenant_transaction
from apps.audit.append import append_audit_event
from apps.audit.models import (
    AuditChainHead,
    AuditEvent,
    AuditMerkleBlock,
)
from apps.audit.sealing import seal_tenant_audit_events
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(
    transaction=True,
    databases="__all__",
)


def _seal_after_barrier(
    organization_id,
    barrier,
    *,
    using="worker_runtime",
):
    close_old_connections()

    try:
        barrier.wait()

        with tenant_transaction(
            organization_id,
            using=using,
        ):
            return seal_tenant_audit_events(
                organization_id,
                using=using,
            )
    finally:
        connections[using].close()


def _append_events(
    organization,
    count,
):
    event_ids = []

    for index in range(count):
        event = append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            entity_id=uuid.uuid4(),
            data={
                "ordinal": str(index),
            },
            using="app_runtime",
        )
        event_ids.append(event.id)

    return event_ids


def test_two_same_tenant_sealers_never_duplicate_block_sequence():
    organization = Organization.objects.create(
        name="Same Tenant Concurrency Firm",
    )

    event_ids = _append_events(
        organization,
        25,
    )

    barrier = Barrier(2)

    with ThreadPoolExecutor(
        max_workers=2,
    ) as executor:
        first = executor.submit(
            _seal_after_barrier,
            organization.id,
            barrier,
        )
        second = executor.submit(
            _seal_after_barrier,
            organization.id,
            barrier,
        )

        first.result()
        second.result()

    with tenant_transaction(
        organization.id,
        using="worker_runtime",
    ):
        blocks = list(
            AuditMerkleBlock.objects.using("worker_runtime")
            .filter(
                organization_id=organization.id,
            )
            .order_by("block_sequence")
        )

        events = list(
            AuditEvent.objects.using("worker_runtime")
            .filter(
                id__in=event_ids,
            )
            .order_by(
                "batch_position",
            )
        )

        head = AuditChainHead.objects.using("worker_runtime").get(
            organization_id=organization.id,
        )

    assert len(blocks) == 1
    assert blocks[0].block_sequence == 1
    assert blocks[0].event_count == 25

    assert head.last_block_sequence == 1
    assert head.last_block_hash == blocks[0].block_hash

    assert len(events) == 25
    assert all(event.node_hash is not None for event in events)
    assert all(event.batch_block_id == blocks[0].id for event in events)
    assert [event.batch_position for event in events] == list(range(25))


def test_two_different_tenants_can_seal_independently():
    first_org = Organization.objects.create(
        name="Concurrent Tenant Alpha",
    )
    second_org = Organization.objects.create(
        name="Concurrent Tenant Beta",
    )

    first_event_ids = _append_events(
        first_org,
        10,
    )
    second_event_ids = _append_events(
        second_org,
        12,
    )

    barrier = Barrier(2)

    with ThreadPoolExecutor(
        max_workers=2,
    ) as executor:
        first = executor.submit(
            _seal_after_barrier,
            first_org.id,
            barrier,
        )
        second = executor.submit(
            _seal_after_barrier,
            second_org.id,
            barrier,
        )

        first.result()
        second.result()

    with tenant_transaction(
        first_org.id,
        using="worker_runtime",
    ):
        first_blocks = list(
            AuditMerkleBlock.objects.using("worker_runtime").filter(
                organization_id=first_org.id,
            )
        )

        first_events = list(
            AuditEvent.objects.using("worker_runtime").filter(
                id__in=first_event_ids,
            )
        )

        first_head = AuditChainHead.objects.using("worker_runtime").get(
            organization_id=first_org.id,
        )

    with tenant_transaction(
        second_org.id,
        using="worker_runtime",
    ):
        second_blocks = list(
            AuditMerkleBlock.objects.using("worker_runtime").filter(
                organization_id=second_org.id,
            )
        )

        second_events = list(
            AuditEvent.objects.using("worker_runtime").filter(
                id__in=second_event_ids,
            )
        )

        second_head = AuditChainHead.objects.using("worker_runtime").get(
            organization_id=second_org.id,
        )

    assert len(first_blocks) == 1
    assert len(second_blocks) == 1

    assert first_blocks[0].block_sequence == 1
    assert second_blocks[0].block_sequence == 1

    assert first_blocks[0].event_count == 10
    assert second_blocks[0].event_count == 12

    assert first_head.last_block_sequence == 1
    assert second_head.last_block_sequence == 1

    assert first_head.last_block_hash == (first_blocks[0].block_hash)
    assert second_head.last_block_hash == (second_blocks[0].block_hash)

    assert all(event.batch_block_id == first_blocks[0].id for event in first_events)
    assert all(event.batch_block_id == second_blocks[0].id for event in second_events)


def test_events_committed_after_snapshot_wait_for_next_block():
    organization = Organization.objects.create(
        name="Fixed Snapshot Firm",
    )
    first_event_id = _append_events(
        organization,
        1,
    )[0]

    snapshot_established = Event()
    later_event_committed = Event()

    def seal_from_fixed_snapshot():
        close_old_connections()

        try:
            with tenant_transaction(
                organization.id,
                using="worker_runtime",
                isolation="repeatable_read",
            ):
                with connections["worker_runtime"].cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM audit_events WHERE organization_id = %s",
                        [organization.id],
                    )
                    assert cursor.fetchone()[0] == 1

                snapshot_established.set()
                assert later_event_committed.wait(timeout=10)

                return seal_tenant_audit_events(
                    organization.id,
                    using="worker_runtime",
                )
        finally:
            connections["worker_runtime"].close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_seal = executor.submit(
            seal_from_fixed_snapshot,
        )

        assert snapshot_established.wait(timeout=10)

        later_event_id = _append_events(
            organization,
            1,
        )[0]
        later_event_committed.set()

        first_block = first_seal.result(timeout=10)

    assert first_block is not None
    assert first_block.block_sequence == 1
    assert first_block.event_count == 1
    assert first_block.first_event_id == first_event_id
    assert first_block.last_event_id == first_event_id

    with tenant_transaction(
        organization.id,
        using="worker_runtime",
    ):
        later_event = AuditEvent.objects.using("worker_runtime").get(id=later_event_id)

    assert later_event.batch_block_id is None
    assert later_event.node_hash is None
    assert later_event.batch_position is None

    with tenant_transaction(
        organization.id,
        using="worker_runtime",
        isolation="repeatable_read",
    ):
        second_block = seal_tenant_audit_events(
            organization.id,
            using="worker_runtime",
        )

    assert second_block is not None
    assert second_block.block_sequence == 2
    assert second_block.event_count == 1
    assert second_block.first_event_id == later_event_id
    assert second_block.last_event_id == later_event_id
    assert second_block.previous_block_hash == first_block.block_hash

    with tenant_transaction(
        organization.id,
        using="worker_runtime",
    ):
        blocks = list(
            AuditMerkleBlock.objects.using("worker_runtime")
            .filter(organization_id=organization.id)
            .order_by("block_sequence")
        )

    assert [block.block_sequence for block in blocks] == [1, 2]
    assert blocks[1].previous_block_hash == blocks[0].block_hash
