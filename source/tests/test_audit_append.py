from __future__ import annotations

import uuid

import pytest

from apps.audit.append import (
    AuditAppendError,
    append_audit_event,
)
from apps.audit.events import AUDIT_EVENT_TYPES
from apps.audit.models import AuditEvent
from apps.jobs.models import BackgroundJob
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Audit Append Firm",
    )


@pytest.mark.parametrize(
    "event_type",
    sorted(AUDIT_EVENT_TYPES),
)
def test_exact_spec_event_registry_is_accepted(
    organization,
    event_type,
):
    event = append_audit_event(
        organization_id=organization.id,
        event_type=event_type,
        entity_type="test_entity",
        data={},
    )

    assert event.event_type == event_type


def test_registry_contains_exact_ten_spec_events():
    assert AUDIT_EVENT_TYPES == {
        "inventory.created",
        "inventory.changed",
        "discovery.completed",
        "reconciliation.accepted",
        "rule.created",
        "rule.changed",
        "assessment.completed",
        "report.generated",
        "connector.connected",
        "connector.disconnected",
    }


def test_append_creates_unsealed_event_and_durable_seal_job(
    organization,
):
    actor_id = uuid.uuid4()
    entity_id = uuid.uuid4()

    event = append_audit_event(
        organization_id=organization.id,
        event_type="inventory.created",
        entity_type="inventory_item",
        entity_id=entity_id,
        actor_user_id=actor_id,
        data={
            "monthly_cost": "49.00",
            "enabled": True,
        },
    )

    event.refresh_from_db()

    assert event.organization_id == organization.id
    assert event.actor_user_id == actor_id
    assert event.entity_id == entity_id
    assert event.data == {
        "monthly_cost": "49.00",
        "enabled": True,
    }

    assert event.node_hash is None
    assert event.batch_block_id is None
    assert event.batch_position is None

    job = BackgroundJob.objects.get(
        organization=organization,
        job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
    )

    assert job.status == BackgroundJob.Status.QUEUED
    assert job.payload == {}


def test_unsupported_event_type_fails_closed(
    organization,
):
    with pytest.raises(
        AuditAppendError,
        match="Unsupported audit event type",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.deleted",
            entity_type="inventory_item",
            data={},
        )

    assert AuditEvent.objects.count() == 0
    assert BackgroundJob.objects.count() == 0


def test_data_must_be_json_object(
    organization,
):
    with pytest.raises(
        AuditAppendError,
        match="must be a JSON object",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            data=["not", "an", "object"],
        )

    assert AuditEvent.objects.count() == 0


def test_nested_binary_float_is_rejected(
    organization,
):
    with pytest.raises(
        AuditAppendError,
        match="Binary floating-point values are not allowed",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.changed",
            entity_type="inventory_item",
            data={
                "financial": {
                    "monthly_cost": 49.99,
                }
            },
        )

    assert AuditEvent.objects.count() == 0
    assert BackgroundJob.objects.count() == 0


def test_decimal_string_is_preserved_exactly(
    organization,
):
    event = append_audit_event(
        organization_id=organization.id,
        event_type="inventory.changed",
        entity_type="inventory_item",
        data={
            "monthly_cost": "49.00",
        },
    )

    event.refresh_from_db()

    assert event.data["monthly_cost"] == "49.00"


def test_non_string_object_key_is_rejected(
    organization,
):
    with pytest.raises(
        AuditAppendError,
        match="object keys must be strings",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            data={
                "outer": {
                    7: "invalid",
                }
            },
        )

    assert AuditEvent.objects.count() == 0


def test_invalid_actor_uuid_fails_before_write(
    organization,
):
    with pytest.raises(
        AuditAppendError,
        match="actor_user_id must be a UUID or null",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            actor_user_id="not-a-uuid",
            data={},
        )

    assert AuditEvent.objects.count() == 0
    assert BackgroundJob.objects.count() == 0


def test_empty_entity_type_fails_before_write(
    organization,
):
    with pytest.raises(
        AuditAppendError,
        match="entity_type must not be empty",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="   ",
            data={},
        )

    assert AuditEvent.objects.count() == 0
    assert BackgroundJob.objects.count() == 0


def test_rfc8785_incompatible_value_fails_before_write(
    organization,
):
    huge_integer = 2**80

    with pytest.raises(
        AuditAppendError,
        match="RFC 8785 / I-JSON",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            data={
                "unsafe_integer": huge_integer,
            },
        )

    assert AuditEvent.objects.count() == 0
    assert BackgroundJob.objects.count() == 0


def test_event_and_job_are_one_atomic_commit(
    organization,
    monkeypatch,
):
    from apps.audit import append

    def fail_enqueue(**kwargs):
        raise RuntimeError("injected enqueue failure")

    monkeypatch.setattr(
        append,
        "enqueue_job",
        fail_enqueue,
    )

    with pytest.raises(
        RuntimeError,
        match="injected enqueue failure",
    ):
        append_audit_event(
            organization_id=organization.id,
            event_type="inventory.created",
            entity_type="inventory_item",
            data={},
        )

    assert AuditEvent.objects.count() == 0
    assert BackgroundJob.objects.count() == 0
