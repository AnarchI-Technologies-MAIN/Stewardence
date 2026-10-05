import uuid

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import (
    AuditChainHead,
    AuditEvent,
    AuditMerkleBlock,
)
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db


def make_org(name="Audit Test Firm"):
    return Organization.objects.create(name=name)


def test_audit_event_defaults_to_unsealed():
    organization = make_org()

    event = AuditEvent.objects.create(
        organization=organization,
        event_type="inventory.created",
        entity_type="inventory_item",
        entity_id=uuid.uuid4(),
        data={"source": "manual"},
    )

    assert event.node_hash is None
    assert event.batch_block_id is None
    assert event.batch_position is None


def test_audit_event_order_is_occurred_at_then_uuid():
    organization = make_org()

    first_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    first = AuditEvent.objects.create(
        id=first_id,
        organization=organization,
        event_type="one",
        entity_type="inventory_item",
        data={},
    )

    AuditEvent.objects.create(
        id=second_id,
        organization=organization,
        event_type="two",
        entity_type="inventory_item",
        data={},
        occurred_at=first.occurred_at,
    )

    assert list(AuditEvent.objects.values_list("id", flat=True)) == [
        first_id,
        second_id,
    ]


def test_chain_head_starts_at_genesis():
    organization = make_org()

    head = AuditChainHead.objects.create(
        organization=organization,
    )

    assert head.last_block_sequence == 0
    assert head.last_block_hash is None


def test_chain_head_rejects_hashless_nonzero_sequence():
    organization = make_org()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditChainHead.objects.create(
                organization=organization,
                last_block_sequence=1,
                last_block_hash=None,
            )


def test_chain_head_rejects_genesis_with_hash():
    organization = make_org()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditChainHead.objects.create(
                organization=organization,
                last_block_sequence=0,
                last_block_hash="11" * 32,
            )


def test_merkle_block_sequence_unique_per_organization():
    organization = make_org()

    common = {
        "organization": organization,
        "block_sequence": 1,
        "algorithm_version": "AL-MERKLE-1",
        "canonicalization_version": "RFC8785",
        "event_count": 1,
        "first_event_id": uuid.uuid4(),
        "last_event_id": uuid.uuid4(),
        "merkle_root": "11" * 32,
        "previous_block_hash": None,
        "block_hash": "22" * 32,
    }

    AuditMerkleBlock.objects.create(**common)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditMerkleBlock.objects.create(
                **{
                    **common,
                    "id": uuid.uuid4(),
                }
            )


def test_same_block_sequence_allowed_for_different_tenants():
    organization_a = make_org("Audit Firm A")
    organization_b = make_org("Audit Firm B")

    for organization in (
        organization_a,
        organization_b,
    ):
        AuditMerkleBlock.objects.create(
            organization=organization,
            block_sequence=1,
            algorithm_version="AL-MERKLE-1",
            canonicalization_version="RFC8785",
            event_count=1,
            first_event_id=uuid.uuid4(),
            last_event_id=uuid.uuid4(),
            merkle_root="11" * 32,
            previous_block_hash=None,
            block_hash="22" * 32,
        )

    assert AuditMerkleBlock.objects.count() == 2


def test_audit_event_seal_metadata_is_all_or_nothing():
    organization = make_org()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AuditEvent.objects.create(
                organization=organization,
                event_type="inventory.created",
                entity_type="inventory_item",
                data={},
                node_hash="11" * 32,
            )


def test_sealed_event_can_reference_block_consistently():
    organization = make_org()

    event_id = uuid.uuid4()

    block = AuditMerkleBlock.objects.create(
        organization=organization,
        block_sequence=1,
        algorithm_version="AL-MERKLE-1",
        canonicalization_version="RFC8785",
        event_count=1,
        first_event_id=event_id,
        last_event_id=event_id,
        merkle_root="11" * 32,
        previous_block_hash=None,
        block_hash="22" * 32,
    )

    event = AuditEvent.objects.create(
        id=event_id,
        organization=organization,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
        node_hash="33" * 32,
        batch_block=block,
        batch_position=0,
    )

    assert event.batch_block_id == block.id
    assert event.batch_position == 0
