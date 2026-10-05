
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

RELEASE_VERSION = "0.2.0"
SETUP_NAME = "StewardSensors-setup.exe"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def run_pyinstaller(
    *,
    repository: Path,
    entrypoint: Path,
    name: str,
    destination: Path,
    console: bool,
    add_data: list[tuple[Path, str]] | None = None,
    add_binary: list[tuple[Path, str]] | None = None,
) -> Path:
    arguments = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--noupx",
        "--onefile",
        "--name",
        name,
        "--paths",
        str(repository),
        "--distpath",
        str(destination),
        "--workpath",
        str(destination / f"build-{name}"),
        "--specpath",
        str(destination),
    ]

    arguments.append("--console" if console else "--windowed")

    for source, target in add_data or []:
        arguments.extend(["--add-data", f"{source};{target}"])

    for source, target in add_binary or []:
        arguments.extend(["--add-binary", f"{source};{target}"])

    arguments.append(str(entrypoint))

    subprocess.run(
        arguments,
        cwd=repository,
        check=True,
    )

    executable = destination / f"{name}.exe"

    if not executable.is_file():
        raise RuntimeError(f"PyInstaller did not produce {executable}")

    return executable


def build_collector(repository: Path, destination: Path) -> Path:
    entrypoint = destination / "collector-entrypoint.py"
    entrypoint.write_text(
        "from collector.__main__ import main\n\nraise SystemExit(main())\n",
        encoding="utf-8",
        newline="\n",
    )

    return run_pyinstaller(
        repository=repository,
        entrypoint=entrypoint,
        name="Stewardence-Collector",
        destination=destination,
        console=True,
    )


def build_setup(
    *,
    repository: Path,
    destination: Path,
    collector_executable: Path,
    manifest: Path,
    profile_path: Path,
    public_key_path: Path,
    signature_path: Path,
) -> Path:
    setup_entrypoint = repository / "collector" / "setup.py"

    return run_pyinstaller(
        repository=repository,
        entrypoint=setup_entrypoint,
        name="StewardSensors-setup",
        destination=destination,
        console=True,
        add_data=[
            (manifest, "."),
            (profile_path, "."),
            (public_key_path, "."),
            (signature_path, "."),
        ],
        add_binary=[
            (collector_executable, "."),
        ],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()

    repository = Path(__file__).resolve().parents[1]
    collector = repository / "collector"
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)

    private_key = serialization.load_pem_private_key(
        args.private_key.read_bytes(),
        password=None,
    )

    public_key_path = collector / "collector-profile-public.pem"
    tracked_public_key = serialization.load_pem_public_key(
        public_key_path.read_bytes()
    )

    if (
        private_key.public_key().public_numbers()
        != tracked_public_key.public_numbers()
    ):
        raise ValueError(
            "Private key does not match the tracked Collector public key"
        )

    with tempfile.TemporaryDirectory() as temporary_name:
        temporary = Path(temporary_name)

        collector_executable = build_collector(
            repository,
            temporary,
        )

        manifest = collector / "collector-modules.json"
        public_der = tracked_public_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        profile = {
            "artifact": {
                "name": collector_executable.name,
                "sha256": sha256(collector_executable),
            },
            "collector_version": RELEASE_VERSION,
            "enabled_modules": ["windows.installed_programs"],
            "module_manifest": {
                "name": manifest.name,
                "sha256": sha256(manifest),
                "version": "1",
            },
            "profile_id": "stewardence-windows-one-shot-mvp",
            "profile_schema_version": 1,
            "public_key_sha256": hashlib.sha256(public_der).hexdigest(),
            "release_version": RELEASE_VERSION,
        }

        profile_path = temporary / "collector-profile.json"
        profile_path.write_bytes(canonical_json(profile))

        signature = private_key.sign(
            profile_path.read_bytes(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

        signature_path = temporary / "collector-profile.sig"
        signature_path.write_text(
            base64.b64encode(signature).decode() + "\n",
            encoding="utf-8",
            newline="\n",
        )

        setup_executable = build_setup(
            repository=repository,
            destination=temporary,
            collector_executable=collector_executable,
            manifest=manifest,
            profile_path=profile_path,
            public_key_path=public_key_path,
            signature_path=signature_path,
        )

        release_path = output / SETUP_NAME
        shutil.copy2(setup_executable, release_path)

        metadata = {
            "asset_name": SETUP_NAME,
            "asset_sha256": sha256(release_path),
            "collector_sha256": profile["artifact"]["sha256"],
            "profile_sha256": sha256(profile_path),
            "public_key_sha256": profile["public_key_sha256"],
            "release_version": RELEASE_VERSION,
        }

        (output / "release-metadata.json").write_bytes(
            canonical_json(metadata)
        )

        print(json.dumps(metadata, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
