
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


SUPPORTED_PROFILE_SCHEMA_VERSION = 1
SUPPORTED_MODULES = ("windows.installed_programs",)


def _payload_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_release(payload: Path) -> dict[str, object]:
    profile_path = payload / "collector-profile.json"
    signature_path = payload / "collector-profile.sig"
    public_key_path = payload / "collector-profile-public.pem"
    manifest_path = payload / "collector-modules.json"

    profile_bytes = profile_path.read_bytes()
    signature = base64.b64decode(signature_path.read_text(encoding="utf-8").strip())
    public_key = serialization.load_pem_public_key(public_key_path.read_bytes())

    public_key.verify(
        signature,
        profile_bytes,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    profile = json.loads(profile_bytes.decode("utf-8"))

    if profile.get("profile_schema_version") != SUPPORTED_PROFILE_SCHEMA_VERSION:
        raise RuntimeError(
            "The Stewardence installation profile version is unsupported."
        )

    enabled_modules = tuple(profile.get("enabled_modules", ()))
    if enabled_modules != SUPPORTED_MODULES:
        raise RuntimeError(
            "The Stewardence installation profile requests unsupported sensor modules."
        )

    artifact = profile.get("artifact", {})
    artifact_name = artifact.get("name")

    if not isinstance(artifact_name, str) or not artifact_name:
        raise RuntimeError("The Stewardence installation profile has no sensor artifact.")

    collector_path = payload / artifact_name

    if _sha256(collector_path) != artifact.get("sha256"):
        raise RuntimeError(
            "The Stewardence sensor executable does not match its signed profile."
        )

    module_manifest = profile.get("module_manifest", {})

    if _sha256(manifest_path) != module_manifest.get("sha256"):
        raise RuntimeError(
            "The Stewardence sensor module manifest does not match its signed profile."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    active = [
        module
        for module in manifest.get("modules", ())
        if module.get("id") == "windows.installed_programs"
        and module.get("available") is True
    ]

    if len(active) != 1:
        raise RuntimeError(
            "The signed Stewardence Windows Installed Programs sensor is unavailable."
        )

    return {
        "collector_path": collector_path,
        "profile": profile,
    }


def _device_id() -> uuid.UUID:
    local_app_data = os.environ.get("LOCALAPPDATA")

    if not local_app_data:
        raise RuntimeError("Windows Local AppData could not be determined.")

    identity_directory = Path(local_app_data) / "Stewardence"
    identity_path = identity_directory / "collector-device-id.txt"
    identity_directory.mkdir(parents=True, exist_ok=True)

    if identity_path.exists():
        value = identity_path.read_text(encoding="utf-8").strip()
        return uuid.UUID(value)

    value = uuid.uuid4()
    identity_path.write_text(
        str(value),
        encoding="utf-8",
        newline="\n",
    )
    return value


def _default_output_directory() -> Path:
    user_profile = os.environ.get("USERPROFILE")

    if not user_profile:
        raise RuntimeError("Windows user profile could not be determined.")

    return Path(user_profile) / "Documents" / "Stewardence"


def run_sensor(output_directory: Path) -> Path:
    payload = _payload_root()
    verified = _verify_release(payload)

    collector_path = verified["collector_path"]
    device_id = _device_id()

    output_directory.mkdir(parents=True, exist_ok=True)

    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_directory / f"stewardence-evidence-{timestamp}.json"

    completed = subprocess.run(
        [
            str(collector_path),
            "--device-id",
            str(device_id),
            "--output",
            str(output_path),
        ],
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            f"The Stewardence sensor exited with code {completed.returncode}."
        )

    if not output_path.is_file():
        raise RuntimeError(
            "The Stewardence sensor completed without producing an evidence bundle."
        )

    print()
    print("StewardSensors scan complete.")
    print(f"Evidence bundle: {output_path}")
    print(f"Bundle SHA-256: {_sha256(output_path)}")
    print()
    print(
        "Review the JSON bundle, then upload it from "
        "Inventory > Collector evidence."
    )

    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="StewardSensors-setup",
        description=(
            "Verify and run the bounded Stewardence Windows sensor package."
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    try:
        output_directory = (
            args.output_directory.resolve()
            if args.output_directory is not None
            else _default_output_directory()
        )
        run_sensor(output_directory)
        return 0
    except Exception as exc:
        print()
        print("StewardSensors could not complete setup or collection.")
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
