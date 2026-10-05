from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from django.db import connections, transaction

from .merkle import (
    ALGORITHM_VERSION,
    CANONICALIZATION_VERSION,
    build_block_envelope,
    hash_block,
    hash_leaf,
    merkle_root_from_hashes,
)
from .models import AuditMerkleBlock

MAX_EVENTS_PER_BLOCK = 1000


class AuditSealingError(RuntimeError):
    pass


@dataclass(frozen=True)
class SealedAuditBlock:
    id: uuid.UUID
    organization_id: uuid.UUID
    block_sequence: int
    event_count: int
    first_event_id: uuid.UUID
    last_event_id: uuid.UUID
    merkle_root: str
    previous_block_hash: str | None
    block_hash: str


def _utc_timestamp(value) -> str:
    if value.tzinfo is None:
        raise AuditSealingError("Audit occurred_at must be timezone-aware")

    normalized = value.astimezone(UTC)

    return normalized.strftime("%Y-%m-%dT%H:%M:%S.") + f"{normalized.microsecond:06d}Z"


def _event_envelope(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        event_id,
        organization_id,
        occurred_at,
        actor_user_id,
        event_type,
        entity_type,
        entity_id,
        data,
    ) = row

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as error:
            raise AuditSealingError(
                "Audit event data could not be decoded as JSON"
            ) from error

    if not isinstance(data, dict):
        raise AuditSealingError("Audit event data must be a JSON object")

    return {
        "schema_version": 1,
        "organization_id": str(organization_id),
        "event_id": str(event_id),
        "occurred_at": _utc_timestamp(occurred_at),
        "actor_user_id": (str(actor_user_id) if actor_user_id is not None else None),
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": (str(entity_id) if entity_id is not None else None),
        "data": data,
    }


def _ensure_chain_head(
    organization_id: uuid.UUID,
    *,
    using: str,
) -> None:
    with connections[using].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_chain_heads (
                organization_id,
                last_block_sequence,
                last_block_hash,
                updated_at
            )
            VALUES (
                %s,
                0,
                NULL,
                clock_timestamp()
            )
            ON CONFLICT (organization_id)
            DO NOTHING
            """,
            [organization_id],
        )


def seal_tenant_audit_events(
    organization_id: uuid.UUID,
    *,
    using: str = "default",
    max_events: int = MAX_EVENTS_PER_BLOCK,
) -> SealedAuditBlock | None:
    if max_events < 1:
        raise ValueError("max_events must be at least 1")

    if max_events > MAX_EVENTS_PER_BLOCK:
        raise ValueError(f"max_events cannot exceed {MAX_EVENTS_PER_BLOCK}")

    with transaction.atomic(using=using):
        _ensure_chain_head(
            organization_id,
            using=using,
        )

        with connections[using].cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    last_block_sequence,
                    last_block_hash
                FROM audit_chain_heads
                WHERE organization_id = %s
                FOR UPDATE
                """,
                [organization_id],
            )

            head = cursor.fetchone()

            if head is None:
                raise AuditSealingError(
                    "Tenant audit chain head could not be established"
                )

            last_block_sequence = head[0]
            previous_block_hash = head[1]

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
                WHERE organization_id = %s
                  AND batch_block_id IS NULL
                  AND node_hash IS NULL
                  AND batch_position IS NULL
                ORDER BY occurred_at ASC, id ASC
                LIMIT %s
                """,
                [
                    organization_id,
                    max_events,
                ],
            )

            rows = cursor.fetchall()

        if not rows:
            return None

        envelopes = [_event_envelope(row) for row in rows]

        leaf_hashes = [hash_leaf(envelope) for envelope in envelopes]

        root_bytes = merkle_root_from_hashes(leaf_hashes)

        root_hex = root_bytes.hex()
        block_sequence = last_block_sequence + 1

        first_event_id = rows[0][0]
        last_event_id = rows[-1][0]

        block_envelope = build_block_envelope(
            organization_id=str(organization_id),
            block_sequence=block_sequence,
            event_count=len(rows),
            first_event_id=str(first_event_id),
            last_event_id=str(last_event_id),
            merkle_root_hex=root_hex,
            previous_block_hash=previous_block_hash,
        )

        block_hash_hex = hash_block(block_envelope).hex()

        block = AuditMerkleBlock.objects.using(using).create(
            organization_id=organization_id,
            block_sequence=block_sequence,
            algorithm_version=ALGORITHM_VERSION,
            canonicalization_version=CANONICALIZATION_VERSION,
            event_count=len(rows),
            first_event_id=first_event_id,
            last_event_id=last_event_id,
            merkle_root=root_hex,
            previous_block_hash=previous_block_hash,
            block_hash=block_hash_hex,
        )

        with connections[using].cursor() as cursor:
            for position, row in enumerate(rows):
                event_id = row[0]
                node_hash_hex = leaf_hashes[position].hex()

                cursor.execute(
                    """
                    UPDATE audit_events
                    SET
                        node_hash = %s,
                        batch_block_id = %s,
                        batch_position = %s
                    WHERE id = %s
                      AND organization_id = %s
                      AND node_hash IS NULL
                      AND batch_block_id IS NULL
                      AND batch_position IS NULL
                    """,
                    [
                        node_hash_hex,
                        block.id,
                        position,
                        event_id,
                        organization_id,
                    ],
                )

                if cursor.rowcount != 1:
                    raise AuditSealingError(
                        "Audit event sealing transition lost exclusivity"
                    )

            cursor.execute(
                """
                UPDATE audit_chain_heads
                SET
                    last_block_sequence = %s,
                    last_block_hash = %s,
                    updated_at = clock_timestamp()
                WHERE organization_id = %s
                  AND last_block_sequence = %s
                  AND last_block_hash IS NOT DISTINCT FROM %s
                """,
                [
                    block_sequence,
                    block_hash_hex,
                    organization_id,
                    last_block_sequence,
                    previous_block_hash,
                ],
            )

            if cursor.rowcount != 1:
                raise AuditSealingError("Audit chain head advancement lost exclusivity")

        return SealedAuditBlock(
            id=block.id,
            organization_id=organization_id,
            block_sequence=block_sequence,
            event_count=len(rows),
            first_event_id=first_event_id,
            last_event_id=last_event_id,
            merkle_root=root_hex,
            previous_block_hash=previous_block_hash,
            block_hash=block_hash_hex,
        )
