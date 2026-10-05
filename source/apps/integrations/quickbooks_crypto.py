"""AES-256-GCM credentials bound to the connection, workspace and actor."""

import base64
import json
import os
import re
import stat
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.views.decorators.debug import sensitive_variables


class CredentialError(Exception):
    pass


@sensitive_variables()
def load_private_json(path):
    try:
        with Path(path).open("rb") as stream:
            mode = os.fstat(stream.fileno())
            if not stat.S_ISREG(mode.st_mode) or mode.st_mode & 0o077:
                raise CredentialError("Private configuration permissions required")
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise CredentialError("Private configuration too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise CredentialError("Private configuration must be an object")
        return result
    except (OSError, ValueError, TypeError):
        raise CredentialError("Private configuration unavailable") from None


@sensitive_variables()
def keyring():
    data = load_private_json(settings.QUICKBOOKS_KEY_FILE)
    try:
        primary = data["primary"]
        keys = {
            name: base64.b64decode(value, validate=True)
            for name, value in data["keys"].items()
        }
        if (
            primary not in keys
            or not 1 <= len(keys) <= 5
            or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", k) for k in keys)
            or any(len(value) != 32 for value in keys.values())
        ):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CredentialError("Invalid encryption key configuration") from None
    return primary, keys


def context(connection):
    return (
        f"qbo-v1|sandbox|{connection.id}|"
        f"{connection.organization_id}|{connection.connected_by_id}"
    ).encode("ascii")


@sensitive_variables()
def encrypt_credentials(connection, data):
    primary, keys = keyring()
    nonce = os.urandom(12)
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    encrypted = AESGCM(keys[primary]).encrypt(nonce, raw, context(connection))
    return "v1." + primary + "." + base64.b64encode(nonce + encrypted).decode("ascii")


@sensitive_variables()
def decrypt_credentials(connection):
    _, keys = keyring()
    try:
        version, name, encoded = connection.encrypted_credentials.split(".", 2)
        if version != "v1":
            raise ValueError
        raw = base64.b64decode(encoded, validate=True)
        decoded = AESGCM(keys[name]).decrypt(raw[:12], raw[12:], context(connection))
        data = json.loads(decoded)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (InvalidTag, KeyError, ValueError, TypeError):
        raise CredentialError("Credentials cannot be authenticated") from None
