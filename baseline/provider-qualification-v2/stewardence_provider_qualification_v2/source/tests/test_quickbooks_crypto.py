import base64
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.integrations.quickbooks_crypto import (
    CredentialError,
    decrypt_credentials,
    encrypt_credentials,
)


@pytest.fixture
def encrypted_config(settings, tmp_path):
    path = tmp_path / "keys.json"
    path.write_text(
        json.dumps(
            {"primary": "one", "keys": {"one": base64.b64encode(b"x" * 32).decode()}}
        )
    )
    path.chmod(0o600)
    settings.QUICKBOOKS_KEY_FILE = str(path)
    return path


def obj():
    return SimpleNamespace(id=uuid4(), organization_id=uuid4(), connected_by_id=uuid4())


def test_aes_roundtrip_random_nonce_and_no_plaintext(encrypted_config):
    connection = obj()
    data = {
        "access_token": "access-private",
        "refresh_token": "refresh-private",
        "realm_id": "12345",
    }
    first = encrypt_credentials(connection, data)
    assert first != encrypt_credentials(connection, data)
    assert "private" not in first and "12345" not in first
    connection.encrypted_credentials = first
    assert decrypt_credentials(connection) == data


@pytest.mark.parametrize("field", ["id", "organization_id", "connected_by_id"])
def test_ciphertext_cannot_move_between_actors_or_workspaces(encrypted_config, field):
    connection = obj()
    connection.encrypted_credentials = encrypt_credentials(
        connection, {"refresh_token": "private"}
    )
    setattr(connection, field, uuid4())
    with pytest.raises(CredentialError):
        decrypt_credentials(connection)


def test_tampering_rejected(encrypted_config):
    connection = obj()
    value = encrypt_credentials(connection, {"refresh_token": "private"})
    version, key, encoded = value.split(".")
    raw = bytearray(base64.b64decode(encoded))
    raw[-1] ^= 1
    connection.encrypted_credentials = ".".join(
        [version, key, base64.b64encode(raw).decode()]
    )
    with pytest.raises(CredentialError):
        decrypt_credentials(connection)


def test_private_file_permissions_required(encrypted_config):
    encrypted_config.chmod(0o644)
    with pytest.raises(CredentialError):
        encrypt_credentials(obj(), {})


def test_key_rotation_reads_old_and_writes_new(encrypted_config):
    connection = obj()
    connection.encrypted_credentials = encrypt_credentials(
        connection, {"realm_id": "123"}
    )
    data = json.loads(encrypted_config.read_text())
    data["keys"]["two"] = base64.b64encode(b"y" * 32).decode()
    data["primary"] = "two"
    encrypted_config.write_text(json.dumps(data))
    assert decrypt_credentials(connection) == {"realm_id": "123"}
    assert encrypt_credentials(connection, {}).startswith("v1.two.")
