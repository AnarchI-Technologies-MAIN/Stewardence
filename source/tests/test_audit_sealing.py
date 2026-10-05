import uuid
from datetime import UTC

import pytest

from agentledger.tenancy.context import tenant_transaction
from apps.audit.merkle import (
    build_block_envelope,
    hash_block,
    hash_leaf,
    merkle_root_from_hashes,
)
from apps.audit.models import (
    AuditChainHead,
    AuditEvent,
    AuditMerkleBlock,
)
from apps.audit.sealing import (
    MAX_EVENTS_PER_BLOCK,
    AuditSealingError,
    seal_tenant_audit_events,
)
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(
    transaction=True,
    databases={
        "default",
        "worker_runtime",
    },
)


@pytest.fixture
def organization():
    return Organization.objects.create(name="Merkle Sealing Firm")


def create_event(
    organization,
    *,
    event_id=None,
    event_type="inventory.updated",
    data=None,
    occurred_at=None,
):
    values = {
        "id": event_id or uuid.uuid4(),
        "organization": organization,
        "event_type": event_type,
        "entity_type": "inventory_item",
        "entity_id": uuid.uuid4(),
        "data": data or {},
    }

    if occurred_at is not None:
        values["occurred_at"] = occurred_at

    return AuditEvent.objects.create(**values)


def seal(organization):
    with tenant_transaction(
        organization.id,
        using="worker_runtime",
    ):
        return seal_tenant_audit_events(
            organization.id,
            using="worker_runtime",
        )


def test_no_events_returns_none_and_preserves_genesis(
    organization,
):
    result = seal(organization)

    assert result is None

    head = AuditChainHead.objects.get(organization=organization)

    assert head.last_block_sequence == 0
    assert head.last_block_hash is None
    assert AuditMerkleBlock.objects.count() == 0


def test_single_event_creates_first_block(
    organization,
):
    event = create_event(
        organization,
        data={"monthly_cost": "49.00"},
    )

    result = seal(organization)

    assert result is not None
    assert result.block_sequence == 1
    assert result.event_count == 1
    assert result.previous_block_hash is None

    event.refresh_from_db()

    assert event.batch_block_id == result.id
    assert event.batch_position == 0
    assert event.node_hash is not None


def test_event_leaf_hash_commits_complete_envelope(
    organization,
):
    event = create_event(
        organization,
        data={
            "monthly_cost": "49.00",
            "enabled": True,
        },
    )

    result = seal(organization)

    event.refresh_from_db()

    envelope = {
        "schema_version": 1,
        "organization_id": str(organization.id),
        "event_id": str(event.id),
        "occurred_at": (
            event.occurred_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.")
            + f"{event.occurred_at.astimezone(UTC).microsecond:06d}Z"
        ),
        "actor_user_id": None,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": str(event.entity_id),
        "data": event.data,
    }

    assert event.node_hash == hash_leaf(envelope).hex()

    assert result is not None


def test_event_order_is_occurred_at_then_id(
    organization,
):
    first_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000002")

    first = create_event(
        organization,
        event_id=first_id,
    )

    create_event(
        organization,
        event_id=second_id,
        occurred_at=first.occurred_at,
    )

    result = seal(organization)

    assert result is not None
    assert result.first_event_id == first_id
    assert result.last_event_id == second_id

    assert list(
        AuditEvent.objects.order_by("batch_position").values_list(
            "id",
            flat=True,
        )
    ) == [
        first_id,
        second_id,
    ]


def test_block_hash_commits_to_previous_block_hash(
    organization,
):
    first_event = create_event(
        organization,
        event_type="first",
    )

    first = seal(organization)

    assert first is not None

    create_event(
        organization,
        event_type="second",
    )

    second = seal(organization)

    assert second is not None
    assert second.block_sequence == 2
    assert second.previous_block_hash == first.block_hash

    block = AuditMerkleBlock.objects.get(id=second.id)

    expected = hash_block(
        build_block_envelope(
            organization_id=str(organization.id),
            block_sequence=2,
            event_count=1,
            first_event_id=str(block.first_event_id),
            last_event_id=str(block.last_event_id),
            merkle_root_hex=block.merkle_root,
            previous_block_hash=first.block_hash,
        )
    ).hex()

    assert block.block_hash == expected

    first_event.refresh_from_db()
    assert first_event.batch_position == 0


def test_second_seal_without_new_events_is_noop(
    organization,
):
    create_event(organization)

    first = seal(organization)
    second = seal(organization)

    assert first is not None
    assert second is None

    assert AuditMerkleBlock.objects.count() == 1

    head = AuditChainHead.objects.get(organization=organization)

    assert head.last_block_sequence == 1


def test_maximum_batch_size_is_enforced(
    organization,
):
    for index in range(1001):
        create_event(
            organization,
            event_type=f"event.{index}",
        )

    first = seal(organization)

    assert first is not None
    assert first.event_count == MAX_EVENTS_PER_BLOCK

    assert AuditEvent.objects.filter(batch_block__isnull=True).count() == 1

    second = seal(organization)

    assert second is not None
    assert second.event_count == 1
    assert second.block_sequence == 2


def test_other_tenant_events_are_not_sealed(
    organization,
):
    other = Organization.objects.create(name="Other Audit Firm")

    own = create_event(organization)
    foreign = create_event(other)

    result = seal(organization)

    assert result is not None

    own.refresh_from_db()
    foreign.refresh_from_db()

    assert own.batch_block_id is not None
    assert foreign.batch_block_id is None


def test_merkle_root_matches_event_leaf_sequence(
    organization,
):
    events = [
        create_event(
            organization,
            event_type=f"event.{index}",
        )
        for index in range(5)
    ]

    result = seal(organization)

    assert result is not None

    sealed = list(
        AuditEvent.objects.filter(id__in=[event.id for event in events]).order_by(
            "batch_position"
        )
    )

    expected_root = merkle_root_from_hashes(
        [bytes.fromhex(event.node_hash) for event in sealed]
    ).hex()

    assert result.merkle_root == expected_root


def test_invalid_batch_limits_fail_closed(
    organization,
):
    with tenant_transaction(
        organization.id,
        using="worker_runtime",
    ):
        with pytest.raises(ValueError):
            seal_tenant_audit_events(
                organization.id,
                using="worker_runtime",
                max_events=0,
            )

        with pytest.raises(ValueError):
            seal_tenant_audit_events(
                organization.id,
                using="worker_runtime",
                max_events=1001,
            )


def test_transaction_rolls_back_on_sealing_failure(
    organization,
    monkeypatch,
):
    event = create_event(organization)

    from apps.audit import sealing

    original = sealing.hash_block

    def fail_block_hash(block):
        raise AuditSealingError("injected sealing failure")

    monkeypatch.setattr(
        sealing,
        "hash_block",
        fail_block_hash,
    )

    with pytest.raises(AuditSealingError):
        seal(organization)

    monkeypatch.setattr(
        sealing,
        "hash_block",
        original,
    )

    event.refresh_from_db()

    assert event.node_hash is None
    assert event.batch_block_id is None
    assert event.batch_position is None
    assert AuditMerkleBlock.objects.count() == 0

    assert not AuditChainHead.objects.filter(organization=organization).exists()


def test_diagnostic_exact_event_envelope(
    organization,
):
    from django.db import connections

    from apps.audit.sealing import (
        _event_envelope,
        _utc_timestamp,
    )

    event = create_event(
        organization,
        data={
            "monthly_cost": "49.00",
            "enabled": True,
        },
    )

    with connections["default"].cursor() as cursor:
        cursor.execute(
            """
            SELECT
                id,
                organization_id,
                occurred_at,
                actor_user_id,
                event_type,
                entity_type,
                entity_id,
                data
            FROM audit_events
            WHERE id = %s
            """,
            [event.id],
        )
        row = cursor.fetchone()

    actual = _event_envelope(row)

    event.refresh_from_db()

    expected = {
        "schema_version": 1,
        "organization_id": str(event.organization_id),
        "event_id": str(event.id),
        "occurred_at": _utc_timestamp(event.occurred_at),
        "actor_user_id": (
            str(event.actor_user_id) if event.actor_user_id is not None else None
        ),
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": (str(event.entity_id) if event.entity_id is not None else None),
        "data": event.data,
    }

    print()
    print("===== RAW DATABASE ROW =====")
    print(repr(row))

    print()
    print("===== SEALER ENVELOPE =====")
    print(repr(actual))

    print()
    print("===== MODEL ENVELOPE =====")
    print(repr(expected))

    print()
    print("===== FIELD DIFFERENCES =====")

    differences = {
        key: {
            "sealer": actual.get(key),
            "model": expected.get(key),
        }
        for key in sorted(set(actual) | set(expected))
        if actual.get(key) != expected.get(key)
    }

    print(repr(differences))

    print()
    print("SEALER HASH:", hash_leaf(actual).hex())
    print("MODEL HASH: ", hash_leaf(expected).hex())

    assert actual == expected
