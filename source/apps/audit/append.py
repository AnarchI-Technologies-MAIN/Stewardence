from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC
from typing import Any

from django.utils import timezone

from agentledger.tenancy.context import tenant_transaction
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import enqueue_job

from .events import AUDIT_EVENT_TYPES
from .merkle import MerkleError, canonical_json
from .models import AuditEvent

EVENT_SCHEMA_VERSION = 1


class AuditAppendError(ValueError):
    pass


def _uuid_or_none(
    value: Any,
    *,
    field_name: str,
) -> uuid.UUID | None:
    if value is None:
        return None

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise AuditAppendError(f"{field_name} must be a UUID or null") from error


def _utc_timestamp(value) -> str:
    if timezone.is_naive(value):
        raise AuditAppendError("Audit event time must be timezone-aware")

    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _validate_json_value(
    value: Any,
    *,
    path: str,
) -> None:
    if type(value) is float:
        raise AuditAppendError(
            f"Binary floating-point values are not allowed in audit data at {path}"
        )

    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise AuditAppendError(
                    f"Audit data object keys must be strings at {path}"
                )

            _validate_json_value(
                child,
                path=f"{path}.{key}",
            )

        return

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for index, child in enumerate(value):
            _validate_json_value(
                child,
                path=f"{path}[{index}]",
            )


def _validate_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise AuditAppendError("Audit event data must be a JSON object")

    _validate_json_value(
        data,
        path="data",
    )

    return data


def _event_envelope(
    *,
    organization_id: uuid.UUID,
    event_id: uuid.UUID,
    occurred_at,
    actor_user_id: uuid.UUID | None,
    event_type: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": EVENT_SCHEMA_VERSION,
        "organization_id": str(organization_id),
        "event_id": str(event_id),
        "occurred_at": _utc_timestamp(occurred_at),
        "actor_user_id": (str(actor_user_id) if actor_user_id is not None else None),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": (str(entity_id) if entity_id is not None else None),
        "data": data,
    }


def append_audit_event(
    *,
    organization_id: Any,
    event_type: str,
    entity_type: str,
    data: dict[str, Any],
    actor_user_id: Any = None,
    entity_id: Any = None,
    using: str = "default",
) -> AuditEvent:
    try:
        normalized_organization_id = uuid.UUID(str(organization_id))
    except (TypeError, ValueError, AttributeError) as error:
        raise AuditAppendError("organization_id must be a UUID") from error

    if event_type not in AUDIT_EVENT_TYPES:
        raise AuditAppendError("Unsupported audit event type")

    if not isinstance(entity_type, str):
        raise AuditAppendError("entity_type must be a string")

    entity_type = entity_type.strip()

    if not entity_type:
        raise AuditAppendError("entity_type must not be empty")

    if len(entity_type) > 160:
        raise AuditAppendError("entity_type exceeds the 160-character limit")

    normalized_actor_user_id = _uuid_or_none(
        actor_user_id,
        field_name="actor_user_id",
    )
    normalized_entity_id = _uuid_or_none(
        entity_id,
        field_name="entity_id",
    )
    validated_data = _validate_data(data)

    event_id = uuid.uuid4()
    occurred_at = timezone.now()

    envelope = _event_envelope(
        organization_id=normalized_organization_id,
        event_id=event_id,
        occurred_at=occurred_at,
        actor_user_id=normalized_actor_user_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=normalized_entity_id,
        data=validated_data,
    )

    try:
        canonical_json(envelope)
    except MerkleError as error:
        raise AuditAppendError(
            "Audit event envelope is not representable as RFC 8785 / I-JSON"
        ) from error

    with tenant_transaction(
        normalized_organization_id,
        using=using,
    ):
        event = AuditEvent.objects.using(using).create(
            id=event_id,
            organization_id=normalized_organization_id,
            occurred_at=occurred_at,
            actor_user_id=normalized_actor_user_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=normalized_entity_id,
            data=validated_data,
        )

        enqueue_job(
            organization_id=normalized_organization_id,
            job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
            payload={},
            using=using,
        )

    return event
