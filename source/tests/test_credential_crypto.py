from __future__ import annotations

import uuid

import pytest

from apps.credentials.crypto import (
    CredentialDecryptionError,
    CredentialKeyError,
    VersionedKEKRing,
    decrypt_credential,
    encrypt_credential,
    generate_kek,
    rotate_compromised_key,
    rotate_kek,
)


@pytest.fixture
def tenant_id():
    return uuid.uuid4()


@pytest.fixture
def record_id():
    return uuid.uuid4()


@pytest.fixture
def key_ring():
    return VersionedKEKRing(
        keys={1: generate_kek()},
        active_version=1,
    )


def test_round_trip_uses_versioned_kek_and_per_record_envelope(
    tenant_id,
    record_id,
    key_ring,
):
    plaintext = b"connector-ready-test-credential"

    first = encrypt_credential(
        plaintext,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )
    second = encrypt_credential(
        plaintext,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    assert first.kek_version == 1
    assert second.kek_version == 1

    assert first.wrapped_dek != second.wrapped_dek
    assert first.wrapped_dek_nonce != second.wrapped_dek_nonce
    assert first.ciphertext != second.ciphertext
    assert first.payload_nonce != second.payload_nonce

    assert (
        decrypt_credential(
            first,
            tenant_id=tenant_id,
            record_id=record_id,
            key_ring=key_ring,
        )
        == plaintext
    )


def test_wrong_tenant_aad_fails(
    tenant_id,
    record_id,
    key_ring,
):
    envelope = encrypt_credential(
        b"tenant-bound",
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    with pytest.raises(
        CredentialDecryptionError,
        match="authentication failed",
    ):
        decrypt_credential(
            envelope,
            tenant_id=uuid.uuid4(),
            record_id=record_id,
            key_ring=key_ring,
        )


def test_wrong_record_aad_fails(
    tenant_id,
    record_id,
    key_ring,
):
    envelope = encrypt_credential(
        b"record-bound",
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    with pytest.raises(
        CredentialDecryptionError,
        match="authentication failed",
    ):
        decrypt_credential(
            envelope,
            tenant_id=tenant_id,
            record_id=uuid.uuid4(),
            key_ring=key_ring,
        )


def test_wrong_kek_fails_even_when_version_number_matches(
    tenant_id,
    record_id,
    key_ring,
):
    envelope = encrypt_credential(
        b"key-bound",
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    wrong_ring = VersionedKEKRing(
        keys={1: generate_kek()},
        active_version=1,
    )

    with pytest.raises(
        CredentialDecryptionError,
        match="authentication failed",
    ):
        decrypt_credential(
            envelope,
            tenant_id=tenant_id,
            record_id=record_id,
            key_ring=wrong_ring,
        )


def test_normal_rotation_rewraps_dek_without_reencrypting_payload(
    tenant_id,
    record_id,
    key_ring,
):
    plaintext = b"normal-key-rotation"

    original = encrypt_credential(
        plaintext,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    key_ring.add_kek(
        version=2,
        key=generate_kek(),
        make_active=True,
    )

    rotated = rotate_kek(
        original,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    assert rotated.kek_version == 2

    assert rotated.ciphertext == original.ciphertext
    assert rotated.payload_nonce == original.payload_nonce

    assert rotated.wrapped_dek != original.wrapped_dek
    assert rotated.wrapped_dek_nonce != original.wrapped_dek_nonce

    assert (
        decrypt_credential(
            rotated,
            tenant_id=tenant_id,
            record_id=record_id,
            key_ring=key_ring,
        )
        == plaintext
    )

    assert (
        decrypt_credential(
            original,
            tenant_id=tenant_id,
            record_id=record_id,
            key_ring=key_ring,
        )
        == plaintext
    )


def test_compromised_key_rotation_creates_new_dek_and_ciphertext(
    tenant_id,
    record_id,
    key_ring,
):
    plaintext = b"compromised-key-rotation"

    original = encrypt_credential(
        plaintext,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    key_ring.add_kek(
        version=2,
        key=generate_kek(),
        make_active=True,
    )

    rotated = rotate_compromised_key(
        original,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    assert rotated.kek_version == 2

    assert rotated.ciphertext != original.ciphertext
    assert rotated.payload_nonce != original.payload_nonce
    assert rotated.wrapped_dek != original.wrapped_dek
    assert rotated.wrapped_dek_nonce != original.wrapped_dek_nonce

    assert (
        decrypt_credential(
            rotated,
            tenant_id=tenant_id,
            record_id=record_id,
            key_ring=key_ring,
        )
        == plaintext
    )


def test_old_kek_cannot_be_removed_while_active_envelope_references_it(
    tenant_id,
    record_id,
    key_ring,
):
    envelope = encrypt_credential(
        b"still-referenced",
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    key_ring.add_kek(
        version=2,
        key=generate_kek(),
        make_active=True,
    )

    with pytest.raises(
        CredentialKeyError,
        match="active envelope references",
    ):
        key_ring.remove_kek(
            1,
            active_envelopes=[envelope],
        )

    assert 1 in key_ring.versions


def test_old_kek_can_be_removed_after_all_active_envelopes_are_rewrapped(
    tenant_id,
    record_id,
    key_ring,
):
    original = encrypt_credential(
        b"fully-rewrapped",
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    key_ring.add_kek(
        version=2,
        key=generate_kek(),
        make_active=True,
    )

    rotated = rotate_kek(
        original,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    key_ring.remove_kek(
        1,
        active_envelopes=[rotated],
    )

    assert 1 not in key_ring.versions
    assert 2 in key_ring.versions


def test_active_kek_cannot_be_removed(
    key_ring,
):
    with pytest.raises(
        CredentialKeyError,
        match="active KEK",
    ):
        key_ring.remove_kek(
            1,
            active_envelopes=[],
        )


def test_invalid_kek_size_is_rejected():
    with pytest.raises(
        CredentialKeyError,
        match="exactly 256 bits",
    ):
        VersionedKEKRing(
            keys={1: b"too-short"},
            active_version=1,
        )
