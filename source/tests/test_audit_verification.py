from __future__ import annotations

import uuid
from contextlib import contextmanager
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connections

from agentledger.tenancy.context import tenant_transaction
from apps.audit.append import append_audit_event
from apps.audit.models import AuditEvent
from apps.audit.sealing import seal_tenant_audit_events
from apps.audit.verification import (
    VerificationStatus,
    verify_tenant_audit_history,
)
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(
    transaction=True,
    databases="__all__",
)


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Audit Verification Firm",
    )


def append_event(organization, ordinal):
    return append_audit_event(
        organization_id=organization.id,
        event_type="inventory.changed",
        entity_type="inventory_item",
        entity_id=uuid.uuid4(),
        data={"ordinal": str(ordinal)},
        using="app_runtime",
    )


def seal(organization, *, max_events=1000):
    with tenant_transaction(
        organization.id,
        using="worker_runtime",
        isolation="repeatable_read",
    ):
        return seal_tenant_audit_events(
            organization.id,
            using="worker_runtime",
            max_events=max_events,
        )


@contextmanager
def audit_event_trigger_disabled():
    table = "audit_events"
    trigger = "audit_events_protect"

    with connections["default"].cursor() as cursor:
        cursor.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")

    try:
        yield
    finally:
        with connections["default"].cursor() as cursor:
            cursor.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")


def verify(organization):
    return verify_tenant_audit_history(
        organization.id,
        using="app_runtime",
    )


def test_missing_chain_and_unsealed_history_are_incomplete(
    organization,
):
    assert verify(organization).status is VerificationStatus.INCOMPLETE

    append_event(organization, 1)

    result = verify(organization)

    assert result.status is VerificationStatus.INCOMPLETE
    assert "No sealed" in result.reason


def test_complete_multi_block_history_is_valid(organization):
    append_event(organization, 1)
    append_event(organization, 2)
    seal(organization, max_events=1)

    incomplete = verify(organization)

    assert incomplete.status is VerificationStatus.INCOMPLETE
    assert incomplete.blocks_checked == 1
    assert incomplete.events_checked == 1

    seal(organization, max_events=1)

    result = verify(organization)

    assert result.status is VerificationStatus.VALID
    assert result.blocks_checked == 2
    assert result.events_checked == 2


def test_verification_command_reports_exact_status(organization):
    append_event(organization, 1)
    seal(organization)
    output = StringIO()

    call_command(
        "verify_audit",
        str(organization.id),
        database="app_runtime",
        stdout=output,
    )

    assert output.getvalue().splitlines()[0] == "VALID"


def test_modifying_sealed_committed_field_is_invalid(
    organization,
):
    event = append_event(organization, 1)
    seal(organization)

    with audit_event_trigger_disabled():
        AuditEvent.objects.filter(id=event.id).update(
            data={"ordinal": "tampered"},
        )

    result = verify(organization)

    assert result.status is VerificationStatus.INVALID


def test_deleting_sealed_event_fails_as_incomplete(organization):
    event = append_event(organization, 1)
    seal(organization)

    with audit_event_trigger_disabled():
        AuditEvent.objects.filter(id=event.id).delete()

    result = verify(organization)

    assert result.status is VerificationStatus.INCOMPLETE


def test_reordering_sealed_events_is_invalid(organization):
    first = append_event(organization, 1)
    second = append_event(organization, 2)
    seal(organization)

    with audit_event_trigger_disabled():
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                UPDATE audit_events
                SET batch_position = CASE
                    WHEN id = %s THEN 1
                    WHEN id = %s THEN 0
                END
                WHERE id IN (%s, %s)
                """,
                [first.id, second.id, first.id, second.id],
            )

    result = verify(organization)

    assert result.status is VerificationStatus.INVALID
