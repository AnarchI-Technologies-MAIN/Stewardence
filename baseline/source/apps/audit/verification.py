from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from agentledger.tenancy.context import tenant_transaction

from .merkle import (
    ALGORITHM_VERSION,
    CANONICALIZATION_VERSION,
    build_block_envelope,
    hash_block,
    hash_leaf,
    merkle_root_from_hashes,
)
from .models import AuditChainHead, AuditEvent, AuditMerkleBlock
from .sealing import _event_envelope


class VerificationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True)
class AuditVerification:
    status: VerificationStatus
    blocks_checked: int
    events_checked: int
    reason: str


def _result(
    status: VerificationStatus,
    blocks_checked: int,
    events_checked: int,
    reason: str,
) -> AuditVerification:
    return AuditVerification(
        status=status,
        blocks_checked=blocks_checked,
        events_checked=events_checked,
        reason=reason,
    )


def verify_tenant_audit_history(
    organization_id: uuid.UUID,
    *,
    using: str = "default",
) -> AuditVerification:
    blocks_checked = 0
    events_checked = 0

    with tenant_transaction(organization_id, using=using):
        blocks = list(
            AuditMerkleBlock.objects.using(using)
            .filter(organization_id=organization_id)
            .order_by("block_sequence")
        )
        head = (
            AuditChainHead.objects.using(using)
            .filter(organization_id=organization_id)
            .first()
        )

        if not blocks:
            return _result(
                VerificationStatus.INCOMPLETE,
                blocks_checked,
                events_checked,
                "No sealed audit chain material exists.",
            )

        if head is None:
            return _result(
                VerificationStatus.INCOMPLETE,
                blocks_checked,
                events_checked,
                "The tenant chain head is missing.",
            )

        previous_block_hash = None

        for expected_sequence, block in enumerate(blocks, start=1):
            block_events = list(
                AuditEvent.objects.using(using)
                .filter(
                    organization_id=organization_id,
                    batch_block_id=block.id,
                )
                .order_by("batch_position")
            )

            if len(block_events) != block.event_count:
                return _result(
                    VerificationStatus.INCOMPLETE,
                    blocks_checked,
                    events_checked,
                    "A sealed block is missing committed event material.",
                )

            if block.block_sequence != expected_sequence:
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Block sequence continuity failed.",
                )

            if block.algorithm_version != ALGORITHM_VERSION or (
                block.canonicalization_version != CANONICALIZATION_VERSION
            ):
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "A block uses unexpected cryptographic versions.",
                )

            if block.previous_block_hash != previous_block_hash:
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Previous-block linkage failed.",
                )

            expected_positions = list(range(len(block_events)))
            actual_positions = [event.batch_position for event in block_events]
            canonical_order = sorted(
                block_events,
                key=lambda event: (event.occurred_at, event.id),
            )

            if actual_positions != expected_positions or (
                block_events != canonical_order
            ):
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Event membership order failed.",
                )

            if (
                block.first_event_id != block_events[0].id
                or block.last_event_id != block_events[-1].id
            ):
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Block event boundaries failed.",
                )

            leaf_hashes = []

            try:
                for event in block_events:
                    envelope = _event_envelope(
                        (
                            event.id,
                            event.organization_id,
                            event.occurred_at,
                            event.actor_user_id,
                            event.event_type,
                            event.entity_type,
                            event.entity_id,
                            event.data,
                        )
                    )
                    leaf_hash = hash_leaf(envelope)

                    if event.node_hash != leaf_hash.hex():
                        return _result(
                            VerificationStatus.INVALID,
                            blocks_checked,
                            events_checked,
                            "A committed event leaf hash failed.",
                        )

                    leaf_hashes.append(leaf_hash)

                merkle_root = merkle_root_from_hashes(leaf_hashes).hex()
                block_envelope = build_block_envelope(
                    organization_id=str(organization_id),
                    block_sequence=block.block_sequence,
                    event_count=block.event_count,
                    first_event_id=str(block.first_event_id),
                    last_event_id=str(block.last_event_id),
                    merkle_root_hex=merkle_root,
                    previous_block_hash=block.previous_block_hash,
                )
                block_hash = hash_block(block_envelope).hex()
            except (TypeError, ValueError):
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Committed audit material is not canonicalizable.",
                )

            if block.merkle_root != merkle_root:
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Merkle root verification failed.",
                )

            if block.block_hash != block_hash:
                return _result(
                    VerificationStatus.INVALID,
                    blocks_checked,
                    events_checked,
                    "Block hash verification failed.",
                )

            blocks_checked += 1
            events_checked += len(block_events)
            previous_block_hash = block.block_hash

        if (
            head.last_block_sequence != blocks[-1].block_sequence
            or head.last_block_hash != blocks[-1].block_hash
        ):
            return _result(
                VerificationStatus.INVALID,
                blocks_checked,
                events_checked,
                "The chain head does not match the final block.",
            )

        if (
            AuditEvent.objects.using(using)
            .filter(
                organization_id=organization_id,
                batch_block_id__isnull=True,
            )
            .exists()
        ):
            return _result(
                VerificationStatus.INCOMPLETE,
                blocks_checked,
                events_checked,
                "The tenant has audit events awaiting sealing.",
            )

    return _result(
        VerificationStatus.VALID,
        blocks_checked,
        events_checked,
        "All committed audit chain material verified.",
    )
