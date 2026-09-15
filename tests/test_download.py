
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from django.urls import reverse

from agentledger.downloads import COLLECTOR_RELEASE, POST_MVP_MODULES

REPOSITORY = Path(__file__).resolve().parents[1]


def test_download_page_exposes_single_executable_release(client):
    response = client.get(reverse("download"))

    assert response.status_code == 200

    for text in (
        b"Download StewardSensors",
        b"StewardSensors for Windows",
        b"Windows Installed Programs",
        b"Installation is only an observation",
        b"single Windows executable",
        b"cryptographically signed",
        b"No PowerShell script",
        b"commercial Windows Authenticode",
    ):
        assert text in response.content

    assert b".ps1" not in response.content
    assert b".zip" not in response.content
    assert COLLECTOR_RELEASE["asset_name"] == "StewardSensors-setup.exe"


def test_collector_release_metadata_and_manifest_are_bounded_and_versioned():
    for key in (
        "sha256",
        "executable_sha256",
        "profile_sha256",
        "public_key_sha256",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", COLLECTOR_RELEASE[key])

    assert COLLECTOR_RELEASE["asset_url"].startswith(
        "https://github.com/AnarchI-Technologies-MAIN/stewardence-mvp-v1.8/"
    )

    assert COLLECTOR_RELEASE["asset_url"].endswith(
        "/StewardSensors-setup.exe"
    )

    assert ".zip" not in COLLECTOR_RELEASE["asset_url"]
    assert ".ps1" not in COLLECTOR_RELEASE["asset_url"]

    manifest_path = REPOSITORY / "collector" / "collector-modules.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    available = [
        module
        for module in manifest["modules"]
        if module["available"]
    ]

    unavailable = [
        module
        for module in manifest["modules"]
        if not module["available"]
    ]

    assert manifest["manifest_version"] == "1"

    assert [
        module["id"]
        for module in available
    ] == ["windows.installed_programs"]

    assert {
        module["display_name"]
        for module in unavailable
    } == set(POST_MVP_MODULES)

    assert all(
        module["status"] == "post_mvp_not_available"
        for module in unavailable
    )

    public_key = serialization.load_pem_public_key(
        (
            REPOSITORY
            / "collector"
            / "collector-profile-public.pem"
        ).read_bytes()
    )

    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    assert hashlib.sha256(public_der).hexdigest() == (
        COLLECTOR_RELEASE["public_key_sha256"]
    )


def test_release_builder_no_longer_packages_customer_powershell():
    source = (
        REPOSITORY
        / "scripts"
        / "build_collector_release.py"
    ).read_text(encoding="utf-8")

    assert "StewardSensors-setup.exe" in source
    assert "zipfile" not in source
    assert "Stewardence-Collector.ps1" not in source
    assert "ARCHIVE_NAME" not in source


def test_setup_replaces_customer_powershell_bootstrapper():
    source = (
        REPOSITORY
        / "collector"
        / "setup.py"
    ).read_text(encoding="utf-8")

    assert "collector-profile.json" in source
    assert "collector-profile.sig" in source
    assert "collector-profile-public.pem" in source
    assert "collector-modules.json" in source
    assert "collector-device-id.txt" in source

    assert "VerifyData" not in source
    assert "ExecutionPolicy" not in source
    assert ".ps1" not in source


def test_locked_brand_source_is_byte_stable():
    canonical = (
        REPOSITORY
        / "docs"
        / "brand"
        / "Stewardence-Helix-Orbit-brand-guidelines-v1.0.png"
    )

    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == (
        "6b9ccc46ea2851a85443cdc703724fb43c34df3e7eb5d0ba565dec6c62b71400"
    )
