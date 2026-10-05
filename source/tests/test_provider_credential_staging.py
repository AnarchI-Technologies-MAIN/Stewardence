"""Exercise credential-file safety without Docker, providers, or production state."""

import importlib.util
import json
import os
import stat
from pathlib import Path
from uuid import uuid4

import pytest

spec = importlib.util.spec_from_file_location(
    "credential_staging",
    Path(__file__).resolve().parents[1] / "ops" / "prepare_provider_credentials.py",
)
staging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(staging)


def payloads():
    return staging.documents(str(uuid4()), "m" * 32, "X" * 32, "x" * 32)


@pytest.mark.parametrize(
    "secret",
    ["", "short", "a" * 4097, "a" * 20 + "\n", "a" * 20 + " ", "a" * 20 + "\x00", None],
)
def test_rejects_malformed_secret_without_echo(secret):
    with pytest.raises(RuntimeError, match="Credential format rejected") as error:
        staging.validate_secret(secret)
    if isinstance(secret, str) and secret:
        assert secret not in str(error.value)


def test_profile_binding_and_read_scopes():
    data = payloads()
    microsoft, xero = data["microsoft.json"], data["xero.json"]
    assert microsoft["owner_user_id"] == xero["owner_user_id"]
    assert not microsoft["enabled"] and not xero["enabled"]
    assert microsoft["tenant_id"] == staging.MICROSOFT_TENANT
    assert xero["require_demo_company"] is True
    assert set(xero["scopes"]) == {
        "offline_access",
        "accounting.settings.read",
        "accounting.reports.profitandloss.read",
    }
    assert all("Write" not in scope for scope in microsoft["scopes"])


def test_each_install_generates_distinct_key():
    assert payloads()["keyring.json"]["keys"] != payloads()["keyring.json"]["keys"]


def test_private_readback_and_no_overwrite(tmp_path):
    data = payloads()
    staging.write_documents(tmp_path, data, os.getuid(), os.getgid())
    original = {}
    for name, expected in data.items():
        path = tmp_path / name
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert json.loads(path.read_bytes()) == expected
        original[name] = path.read_bytes()
    with pytest.raises(FileExistsError):
        staging.write_documents(tmp_path, payloads(), os.getuid(), os.getgid())
    assert {name: (tmp_path / name).read_bytes() for name in original} == original


def test_symlink_cannot_overwrite_target(tmp_path):
    target = tmp_path / "existing"
    target.write_text("keep")
    (tmp_path / "microsoft.json").symlink_to(target)
    with pytest.raises(FileExistsError):
        staging.write_documents(tmp_path, payloads(), os.getuid(), os.getgid())
    assert target.read_text() == "keep"


def test_nonmatching_secret_stops(monkeypatch):
    values = iter(["a" * 32, "b" * 32])
    monkeypatch.setattr(staging.getpass, "getpass", lambda _: next(values))
    with pytest.raises(RuntimeError, match="did not match"):
        staging.confirmed_secret("test")


def test_invalid_owner_stops():
    with pytest.raises(ValueError):
        staging.documents("not-a-uuid", "a" * 32, "X" * 32, "b" * 32)


def test_path_traversal_filename_rejected(tmp_path):
    with pytest.raises(RuntimeError, match="Unexpected credential filename"):
        staging.write_documents(tmp_path, {"../escape": {}}, os.getuid(), os.getgid())
