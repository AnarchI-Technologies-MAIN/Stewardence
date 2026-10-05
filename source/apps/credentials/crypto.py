from __future__ import annotations

import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AES_256_KEY_BYTES: Final = 32
AES_GCM_NONCE_BYTES: Final = 12
ENVELOPE_VERSION: Final = 1

_DEK_WRAP_DOMAIN: Final = b"agentledger:credential-envelope:dek:v1"
_PAYLOAD_DOMAIN: Final = b"agentledger:credential-envelope:payload:v1"


class CredentialCryptoError(ValueError):
    """Base error for credential-envelope operations."""


class CredentialDecryptionError(CredentialCryptoError):
    """Raised when authenticated credential decryption fails."""


class CredentialKeyError(CredentialCryptoError):
    """Raised when KEK configuration or lifecycle rules are violated."""


@dataclass(frozen=True)
class CredentialEnvelope:
    envelope_version: int
    kek_version: int
    wrapped_dek_nonce: bytes
    wrapped_dek: bytes
    payload_nonce: bytes
    ciphertext: bytes

    def __post_init__(self) -> None:
        if self.envelope_version != ENVELOPE_VERSION:
            raise CredentialCryptoError("Unsupported credential envelope version")

        if self.kek_version < 1:
            raise CredentialCryptoError("KEK version must be positive")

        if len(self.wrapped_dek_nonce) != AES_GCM_NONCE_BYTES:
            raise CredentialCryptoError("Wrapped DEK nonce must be 12 bytes")

        if len(self.payload_nonce) != AES_GCM_NONCE_BYTES:
            raise CredentialCryptoError("Payload nonce must be 12 bytes")

        if len(self.wrapped_dek) <= AES_256_KEY_BYTES:
            raise CredentialCryptoError("Wrapped DEK is invalid")

        if len(self.ciphertext) < 16:
            raise CredentialCryptoError("Credential ciphertext is invalid")


def _identity_bytes(value, *, field_name: str) -> bytes:
    try:
        normalized = uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as error:
        raise CredentialCryptoError(f"{field_name} must be a UUID") from error

    return str(normalized).encode("ascii")


def _aad(
    domain: bytes,
    *,
    tenant_id,
    record_id,
) -> bytes:
    tenant = _identity_bytes(
        tenant_id,
        field_name="tenant_id",
    )
    record = _identity_bytes(
        record_id,
        field_name="record_id",
    )

    return b"|".join(
        (
            domain,
            b"tenant=" + tenant,
            b"record=" + record,
        )
    )


def _validate_kek(key: bytes) -> bytes:
    if not isinstance(key, bytes):
        raise CredentialKeyError("KEKs must be bytes")

    if len(key) != AES_256_KEY_BYTES:
        raise CredentialKeyError("KEKs must be exactly 256 bits")

    return key


def generate_kek() -> bytes:
    return AESGCM.generate_key(bit_length=256)


class VersionedKEKRing:
    def __init__(
        self,
        *,
        keys: Mapping[int, bytes],
        active_version: int,
    ) -> None:
        normalized: dict[int, bytes] = {}

        for version, key in keys.items():
            if not isinstance(version, int) or version < 1:
                raise CredentialKeyError("KEK versions must be positive integers")

            normalized[version] = _validate_kek(key)

        if active_version not in normalized:
            raise CredentialKeyError("Active KEK version must exist in the key ring")

        self._keys = normalized
        self._active_version = active_version

    @property
    def active_version(self) -> int:
        return self._active_version

    @property
    def versions(self) -> frozenset[int]:
        return frozenset(self._keys)

    def key_for_version(self, version: int) -> bytes:
        try:
            return self._keys[version]
        except KeyError as error:
            raise CredentialKeyError(f"KEK version {version} is unavailable") from error

    def add_kek(
        self,
        *,
        version: int,
        key: bytes,
        make_active: bool = False,
    ) -> None:
        if not isinstance(version, int) or version < 1:
            raise CredentialKeyError("KEK versions must be positive integers")

        if version in self._keys:
            raise CredentialKeyError(f"KEK version {version} already exists")

        self._keys[version] = _validate_kek(key)

        if make_active:
            self._active_version = version

    def activate(self, version: int) -> None:
        self.key_for_version(version)
        self._active_version = version

    def remove_kek(
        self,
        version: int,
        *,
        active_envelopes: Iterable[CredentialEnvelope],
    ) -> None:
        if version == self._active_version:
            raise CredentialKeyError("The active KEK cannot be removed")

        self.key_for_version(version)

        if any(envelope.kek_version == version for envelope in active_envelopes):
            raise CredentialKeyError(
                "KEK cannot be removed while an active envelope references it"
            )

        del self._keys[version]


def _wrap_dek(
    *,
    dek: bytes,
    kek: bytes,
    tenant_id,
    record_id,
) -> tuple[bytes, bytes]:
    nonce = os.urandom(AES_GCM_NONCE_BYTES)
    aad = _aad(
        _DEK_WRAP_DOMAIN,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    wrapped = AESGCM(kek).encrypt(
        nonce,
        dek,
        aad,
    )

    return nonce, wrapped


def _unwrap_dek(
    *,
    envelope: CredentialEnvelope,
    kek: bytes,
    tenant_id,
    record_id,
) -> bytes:
    aad = _aad(
        _DEK_WRAP_DOMAIN,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    try:
        dek = AESGCM(kek).decrypt(
            envelope.wrapped_dek_nonce,
            envelope.wrapped_dek,
            aad,
        )
    except InvalidTag as error:
        raise CredentialDecryptionError(
            "Credential envelope authentication failed"
        ) from error

    if len(dek) != AES_256_KEY_BYTES:
        raise CredentialDecryptionError("Credential DEK has an invalid size")

    return dek


def encrypt_credential(
    plaintext: bytes,
    *,
    tenant_id,
    record_id,
    key_ring: VersionedKEKRing,
) -> CredentialEnvelope:
    if not isinstance(plaintext, bytes):
        raise CredentialCryptoError("Credential plaintext must be bytes")

    dek = AESGCM.generate_key(bit_length=256)
    payload_nonce = os.urandom(AES_GCM_NONCE_BYTES)

    payload_aad = _aad(
        _PAYLOAD_DOMAIN,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    ciphertext = AESGCM(dek).encrypt(
        payload_nonce,
        plaintext,
        payload_aad,
    )

    kek_version = key_ring.active_version
    kek = key_ring.key_for_version(kek_version)

    wrapped_dek_nonce, wrapped_dek = _wrap_dek(
        dek=dek,
        kek=kek,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    return CredentialEnvelope(
        envelope_version=ENVELOPE_VERSION,
        kek_version=kek_version,
        wrapped_dek_nonce=wrapped_dek_nonce,
        wrapped_dek=wrapped_dek,
        payload_nonce=payload_nonce,
        ciphertext=ciphertext,
    )


def decrypt_credential(
    envelope: CredentialEnvelope,
    *,
    tenant_id,
    record_id,
    key_ring: VersionedKEKRing,
) -> bytes:
    kek = key_ring.key_for_version(envelope.kek_version)

    dek = _unwrap_dek(
        envelope=envelope,
        kek=kek,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    payload_aad = _aad(
        _PAYLOAD_DOMAIN,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    try:
        return AESGCM(dek).decrypt(
            envelope.payload_nonce,
            envelope.ciphertext,
            payload_aad,
        )
    except InvalidTag as error:
        raise CredentialDecryptionError(
            "Credential ciphertext authentication failed"
        ) from error


def rotate_kek(
    envelope: CredentialEnvelope,
    *,
    tenant_id,
    record_id,
    key_ring: VersionedKEKRing,
) -> CredentialEnvelope:
    old_kek = key_ring.key_for_version(envelope.kek_version)

    dek = _unwrap_dek(
        envelope=envelope,
        kek=old_kek,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    new_version = key_ring.active_version
    new_kek = key_ring.key_for_version(new_version)

    wrapped_dek_nonce, wrapped_dek = _wrap_dek(
        dek=dek,
        kek=new_kek,
        tenant_id=tenant_id,
        record_id=record_id,
    )

    return CredentialEnvelope(
        envelope_version=envelope.envelope_version,
        kek_version=new_version,
        wrapped_dek_nonce=wrapped_dek_nonce,
        wrapped_dek=wrapped_dek,
        payload_nonce=envelope.payload_nonce,
        ciphertext=envelope.ciphertext,
    )


def rotate_compromised_key(
    envelope: CredentialEnvelope,
    *,
    tenant_id,
    record_id,
    key_ring: VersionedKEKRing,
) -> CredentialEnvelope:
    plaintext = decrypt_credential(
        envelope,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )

    return encrypt_credential(
        plaintext,
        tenant_id=tenant_id,
        record_id=record_id,
        key_ring=key_ring,
    )
