"""Separate preview keyring; authenticated binding includes provider and purpose."""

import base64
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .quickbooks_crypto import CredentialError, load_private_json


@sensitive_variables()
def keyring():
    data = load_private_json(settings.PROVIDER_PREVIEW_KEY_FILE)
    try:
        primary = data["active_key_id"]
        keys = {k: base64.b64decode(v, validate=True) for k, v in data["keys"].items()}
        if (
            data.get("schema") != "stewardence.provider-preview-keyring.v1"
            or primary not in keys
            or not 1 <= len(keys) <= 5
            or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", k) for k in keys)
            or any(len(v) != 32 for v in keys.values())
        ):
            raise ValueError
        return primary, keys
    except (KeyError, ValueError, TypeError, AttributeError):
        raise CredentialError("Invalid provider key configuration") from None


def context(obj, purpose):
    return (
        f"provider-v1|{obj.provider}|{obj.environment}|{obj.id}|"
        f"{obj.organization_id}|{obj.connected_by_id}|{purpose}"
    ).encode("ascii")


@sensitive_variables()
def encrypt(obj, data, purpose="tokens"):
    primary, keys = keyring()
    nonce = os.urandom(12)
    raw = json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    encrypted = AESGCM(keys[primary]).encrypt(nonce, raw, context(obj, purpose))
    return "v1." + primary + "." + base64.b64encode(nonce + encrypted).decode()


@sensitive_variables()
def decrypt(obj, encrypted, purpose="tokens"):
    _, keys = keyring()
    try:
        version, name, encoded = encrypted.split(".", 2)
        if version != "v1":
            raise ValueError
        raw = base64.b64decode(encoded, validate=True)
        decoded = AESGCM(keys[name]).decrypt(raw[:12], raw[12:], context(obj, purpose))
        data = json.loads(decoded)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (InvalidTag, KeyError, ValueError, TypeError):
        raise CredentialError("Provider credentials cannot be authenticated") from None
