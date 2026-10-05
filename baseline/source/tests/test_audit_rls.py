import os
import uuid

import psycopg
import pytest
from django.db import DatabaseError, connections

from agentledger.tenancy.context import tenant_transaction
from apps.audit.models import (
    AuditChainHead,
    AuditEvent,
    AuditMerkleBlock,
)
from apps.organizations.models import Organization

pytestmark = [
    pytest.mark.rls,
    pytest.mark.skipif(
        os.getenv("AGENTLEDGER_RLS_TESTS") != "1",
        reason="run through scripts/verify_rls.py",
    ),
    pytest.mark.django_db(
        transaction=True,
        databases={
            "default",
            "owner_runtime",
            "app_runtime",
            "worker_runtime",
        },
    ),
]


@pytest.fixture
def audit_rls_fixture():
    organization_a = Organization.objects.create(name="Audit RLS Firm A")
    organization_b = Organization.objects.create(name="Audit RLS Firm B")

    yield organization_a, organization_b

    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            TRUNCATE TABLE
                audit_events,
                audit_merkle_blocks,
                audit_chain_heads
            CASCADE
            """
        )

    Organization.objects.filter(
        id__in=[
            organization_a.id,
            organization_b.id,
        ]
    ).delete()


def insufficient_privilege(error):
    cause = error.__cause__
    return isinstance(
        cause,
        psycopg.errors.InsufficientPrivilege,
    )


def make_block(
    organization,
    *,
    sequence=1,
):
    event_id = uuid.uuid4()

    return AuditMerkleBlock.objects.create(
        organization=organization,
        block_sequence=sequence,
        algorithm_version="AL-MERKLE-1",
        canonicalization_version="RFC8785",
        event_count=1,
        first_event_id=event_id,
        last_event_id=event_id,
        merkle_root="11" * 32,
        previous_block_hash=None,
        block_hash="22" * 32,
    )


def test_app_runtime_sees_only_tenant_events(
    audit_rls_fixture,
):
    organization_a, organization_b = audit_rls_fixture

    AuditEvent.objects.create(
        organization=organization_a,
        event_type="tenant.a",
        entity_type="inventory_item",
        data={},
    )

    AuditEvent.objects.create(
        organization=organization_b,
        event_type="tenant.b",
        entity_type="inventory_item",
        data={},
    )

    with tenant_transaction(
        organization_a.id,
        using="app_runtime",
    ):
        values = list(
            AuditEvent.objects.using("app_runtime").values_list(
                "event_type",
                flat=True,
            )
        )

    assert values == ["tenant.a"]


def test_app_runtime_can_insert_own_tenant_event(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    with tenant_transaction(
        organization_a.id,
        using="app_runtime",
    ):
        event = AuditEvent.objects.using("app_runtime").create(
            organization_id=organization_a.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            data={"source": "manual"},
        )

    assert event.organization_id == organization_a.id


def test_app_runtime_cannot_insert_cross_tenant_event(
    audit_rls_fixture,
):
    organization_a, organization_b = audit_rls_fixture

    with pytest.raises(DatabaseError):
        with tenant_transaction(
            organization_a.id,
            using="app_runtime",
        ):
            AuditEvent.objects.using("app_runtime").create(
                organization_id=organization_b.id,
                event_type="cross.tenant",
                entity_type="inventory_item",
                data={},
            )


def test_app_runtime_cannot_update_event(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    event = AuditEvent.objects.create(
        organization=organization_a,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
    )

    with pytest.raises(DatabaseError) as error:
        with tenant_transaction(
            organization_a.id,
            using="app_runtime",
        ):
            AuditEvent.objects.using("app_runtime").filter(
                id=event.id,
            ).update(
                event_type="inventory.changed",
            )

    assert insufficient_privilege(error.value)


def test_worker_cannot_change_committed_event_envelope(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    event = AuditEvent.objects.create(
        organization=organization_a,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={"original": True},
    )

    with pytest.raises(DatabaseError):
        with tenant_transaction(
            organization_a.id,
            using="worker_runtime",
        ):
            AuditEvent.objects.using("worker_runtime").filter(
                id=event.id,
            ).update(
                data={"original": False},
            )


def test_worker_can_apply_complete_sealing_metadata_once(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    event = AuditEvent.objects.create(
        organization=organization_a,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
    )

    block = make_block(organization_a)

    with tenant_transaction(
        organization_a.id,
        using="worker_runtime",
    ):
        updated = (
            AuditEvent.objects.using("worker_runtime")
            .filter(
                id=event.id,
            )
            .update(
                node_hash="33" * 32,
                batch_block_id=block.id,
                batch_position=0,
            )
        )

    assert updated == 1


def test_worker_cannot_reseal_event(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    event = AuditEvent.objects.create(
        organization=organization_a,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
    )

    first_block = make_block(
        organization_a,
        sequence=1,
    )

    second_block = make_block(
        organization_a,
        sequence=2,
    )

    with tenant_transaction(
        organization_a.id,
        using="worker_runtime",
    ):
        AuditEvent.objects.using("worker_runtime").filter(
            id=event.id,
        ).update(
            node_hash="33" * 32,
            batch_block_id=first_block.id,
            batch_position=0,
        )

    with pytest.raises(DatabaseError):
        with tenant_transaction(
            organization_a.id,
            using="worker_runtime",
        ):
            AuditEvent.objects.using("worker_runtime").filter(
                id=event.id,
            ).update(
                node_hash="44" * 32,
                batch_block_id=second_block.id,
                batch_position=0,
            )


def test_worker_cannot_update_merkle_block(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    block = make_block(organization_a)

    with pytest.raises(DatabaseError) as error:
        with tenant_transaction(
            organization_a.id,
            using="worker_runtime",
        ):
            AuditMerkleBlock.objects.using("worker_runtime").filter(
                id=block.id,
            ).update(
                merkle_root="99" * 32,
            )

    assert insufficient_privilege(error.value)


def test_worker_chain_head_is_tenant_scoped(
    audit_rls_fixture,
):
    organization_a, organization_b = audit_rls_fixture

    AuditChainHead.objects.create(
        organization=organization_a,
    )

    AuditChainHead.objects.create(
        organization=organization_b,
    )

    with tenant_transaction(
        organization_a.id,
        using="worker_runtime",
    ):
        ids = list(
            AuditChainHead.objects.using("worker_runtime").values_list(
                "organization_id",
                flat=True,
            )
        )

    assert ids == [organization_a.id]


def test_missing_tenant_context_hides_worker_audit_rows(
    audit_rls_fixture,
):
    organization_a, _ = audit_rls_fixture

    AuditEvent.objects.create(
        organization=organization_a,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
    )

    with pytest.raises(DatabaseError):
        list(
            AuditEvent.objects.using("worker_runtime").values_list(
                "id",
                flat=True,
            )
        )
