import hashlib

import pytest
import rfc8785

from apps.audit.merkle import (
    ALGORITHM_VERSION,
    BLOCK_VERSION,
    CANONICALIZATION_VERSION,
    MerkleError,
    build_block_envelope,
    canonical_json,
    hash_block,
    hash_leaf,
    hash_node,
    merkle_root,
    merkle_root_from_hashes,
)


def sample_event(event_id: str, event_type: str = "inventory.updated"):
    return {
        "schema_version": 1,
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "event_id": event_id,
        "occurred_at": "2026-09-04T10:26:14.123456Z",
        "actor_user_id": None,
        "event_type": event_type,
        "entity_type": "inventory_item",
        "entity_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "data": {
            "monthly_cost": "49.00",
            "enabled": True,
        },
    }


def test_versions_are_frozen():
    assert ALGORITHM_VERSION == "AL-MERKLE-1"
    assert BLOCK_VERSION == "AL-BLOCK-1"
    assert CANONICALIZATION_VERSION == "RFC8785"


def test_canonical_json_matches_rfc8785():
    value = {
        "z": 1,
        "a": {
            "b": True,
            "a": None,
        },
    }

    assert canonical_json(value) == rfc8785.dumps(value)


def test_leaf_hash_is_domain_separated_sha256():
    event = sample_event("00000000-0000-0000-0000-000000000001")

    expected = hashlib.sha256(b"\x00" + rfc8785.dumps(event)).digest()

    assert hash_leaf(event) == expected


def test_node_hash_uses_raw_digest_bytes_not_hex_text():
    left = bytes.fromhex("11" * 32)
    right = bytes.fromhex("22" * 32)

    expected = hashlib.sha256(b"\x01" + left + right).digest()

    assert hash_node(left, right) == expected

    wrong = hashlib.sha256(
        b"\x01" + left.hex().encode() + right.hex().encode()
    ).digest()

    assert hash_node(left, right) != wrong


def test_block_hash_is_domain_separated_sha256():
    block = build_block_envelope(
        organization_id="11111111-1111-1111-1111-111111111111",
        block_sequence=1,
        event_count=2,
        first_event_id="00000000-0000-0000-0000-000000000001",
        last_event_id="00000000-0000-0000-0000-000000000002",
        merkle_root_hex="ab" * 32,
        previous_block_hash=None,
    )

    expected = hashlib.sha256(b"\x02" + rfc8785.dumps(block)).digest()

    assert hash_block(block) == expected


def test_single_leaf_root_is_leaf_hash():
    event = sample_event("00000000-0000-0000-0000-000000000001")

    assert merkle_root([event]) == hash_leaf(event)


def test_two_leaf_root_is_single_parent_hash():
    first = sample_event("00000000-0000-0000-0000-000000000001")
    second = sample_event("00000000-0000-0000-0000-000000000002")

    expected = hash_node(
        hash_leaf(first),
        hash_leaf(second),
    )

    assert merkle_root([first, second]) == expected


def test_three_leaf_tree_uses_largest_power_of_two_split():
    events = [
        sample_event("00000000-0000-0000-0000-000000000001"),
        sample_event("00000000-0000-0000-0000-000000000002"),
        sample_event("00000000-0000-0000-0000-000000000003"),
    ]

    first_pair = hash_node(
        hash_leaf(events[0]),
        hash_leaf(events[1]),
    )

    expected = hash_node(
        first_pair,
        hash_leaf(events[2]),
    )

    assert merkle_root(events) == expected


def test_five_leaf_tree_uses_four_plus_one_split():
    leaves = [hashlib.sha256(str(index).encode()).digest() for index in range(5)]

    left = hash_node(
        hash_node(leaves[0], leaves[1]),
        hash_node(leaves[2], leaves[3]),
    )

    expected = hash_node(
        left,
        leaves[4],
    )

    assert merkle_root_from_hashes(leaves) == expected


def test_event_field_change_changes_leaf_and_root():
    original = sample_event("00000000-0000-0000-0000-000000000001")
    changed = {
        **original,
        "event_type": "inventory.archived",
    }

    assert hash_leaf(original) != hash_leaf(changed)
    assert merkle_root([original]) != merkle_root([changed])


def test_event_data_change_changes_leaf_and_root():
    original = sample_event("00000000-0000-0000-0000-000000000001")

    changed = {
        **original,
        "data": {
            **original["data"],
            "monthly_cost": "50.00",
        },
    }

    assert hash_leaf(original) != hash_leaf(changed)
    assert merkle_root([original]) != merkle_root([changed])


def test_root_is_order_sensitive():
    first = sample_event("00000000-0000-0000-0000-000000000001")
    second = sample_event("00000000-0000-0000-0000-000000000002")

    assert merkle_root([first, second]) != merkle_root([second, first])


def test_zero_leaf_tree_is_rejected():
    with pytest.raises(MerkleError):
        merkle_root([])


def test_invalid_digest_length_is_rejected():
    with pytest.raises(MerkleError):
        hash_node(b"x", bytes(32))


def test_invalid_block_sequence_is_rejected():
    with pytest.raises(MerkleError):
        build_block_envelope(
            organization_id="11111111-1111-1111-1111-111111111111",
            block_sequence=0,
            event_count=1,
            first_event_id="00000000-0000-0000-0000-000000000001",
            last_event_id="00000000-0000-0000-0000-000000000001",
            merkle_root_hex="ab" * 32,
            previous_block_hash=None,
        )


def test_block_hash_changes_when_previous_block_hash_changes():
    first = build_block_envelope(
        organization_id="11111111-1111-1111-1111-111111111111",
        block_sequence=2,
        event_count=1,
        first_event_id="00000000-0000-0000-0000-000000000002",
        last_event_id="00000000-0000-0000-0000-000000000002",
        merkle_root_hex="ab" * 32,
        previous_block_hash="11" * 32,
    )

    second = {
        **first,
        "previous_block_hash": "22" * 32,
    }

    assert hash_block(first) != hash_block(second)
