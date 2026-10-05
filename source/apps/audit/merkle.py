from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

import rfc8785

ALGORITHM_VERSION = "AL-MERKLE-1"
BLOCK_VERSION = "AL-BLOCK-1"
CANONICALIZATION_VERSION = "RFC8785"


class MerkleError(ValueError):
    pass


def sha256(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def canonical_json(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except Exception as error:
        raise MerkleError(
            "Value is not representable as RFC 8785 canonical JSON"
        ) from error


def hash_leaf(event: Mapping[str, Any]) -> bytes:
    return sha256(b"\x00" + canonical_json(dict(event)))


def hash_node(left: bytes, right: bytes) -> bytes:
    if len(left) != 32 or len(right) != 32:
        raise MerkleError("Merkle node children must be 32-byte SHA-256 digests")

    return sha256(b"\x01" + left + right)


def hash_block(block: Mapping[str, Any]) -> bytes:
    return sha256(b"\x02" + canonical_json(dict(block)))


def _largest_power_of_two_less_than(value: int) -> int:
    if value < 2:
        raise MerkleError("Value must be at least 2")

    return 1 << ((value - 1).bit_length() - 1)


def merkle_root_from_hashes(leaf_hashes: Sequence[bytes]) -> bytes:
    count = len(leaf_hashes)

    if count == 0:
        raise MerkleError("Cannot build a Merkle root from zero leaves")

    for leaf_hash in leaf_hashes:
        if len(leaf_hash) != 32:
            raise MerkleError("Merkle leaves must be 32-byte SHA-256 digests")

    if count == 1:
        return leaf_hashes[0]

    split = _largest_power_of_two_less_than(count)

    left = merkle_root_from_hashes(leaf_hashes[:split])
    right = merkle_root_from_hashes(leaf_hashes[split:])

    return hash_node(left, right)


def merkle_root(events: Sequence[Mapping[str, Any]]) -> bytes:
    if not events:
        raise MerkleError("Cannot build a Merkle root from zero events")

    return merkle_root_from_hashes([hash_leaf(event) for event in events])


def build_block_envelope(
    *,
    organization_id: str,
    block_sequence: int,
    event_count: int,
    first_event_id: str,
    last_event_id: str,
    merkle_root_hex: str,
    previous_block_hash: str | None,
) -> dict[str, Any]:
    if block_sequence < 1:
        raise MerkleError("Block sequence must be at least 1")

    if event_count < 1:
        raise MerkleError("Event count must be at least 1")

    if len(merkle_root_hex) != 64:
        raise MerkleError("Merkle root must be a 64-character SHA-256 hex digest")

    if previous_block_hash is not None and len(previous_block_hash) != 64:
        raise MerkleError(
            "Previous block hash must be null or a 64-character SHA-256 hex digest"
        )

    return {
        "version": BLOCK_VERSION,
        "organization_id": organization_id,
        "block_sequence": block_sequence,
        "event_count": event_count,
        "first_event_id": first_event_id,
        "last_event_id": last_event_id,
        "merkle_root": merkle_root_hex,
        "previous_block_hash": previous_block_hash,
    }
