"""Explicit local export/encryption stage, not restore or production readiness."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from current_restore_catalog import SQL as CATALOG_SQL
from prepare_current_restore_export import KEY, ROOT, STREAM


def exact_container(name, run_name):
    response = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            '{{.Id}}\n{{.Name}}\n{{index .Config.Labels "stewardence.qualification.run"}}',
            name,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    identity, observed_name, label = response.stdout.strip().splitlines()
    if (
        re.fullmatch(r"[0-9a-f]{64}", identity) is None
        or observed_name != "/" + name
        or label != run_name
    ):
        raise RuntimeError("Exact local export container ownership unavailable")
    return identity


def encrypt_stream(command, target, recipient, limit):
    # A bounded middle process stops oversized plaintext before encryption;
    # plaintext flows only through OS pipes, never host files or diagnostics.
    limiter = "import sys\nremaining=int(sys.argv[1])\nwhile True:\n data=sys.stdin.buffer.read(min(65536,remaining+1))\n if not data: break\n remaining-=len(data)\n if remaining<0: raise SystemExit(3)\n sys.stdout.buffer.write(data)\n"
    processes = []
    try:
        producer = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        processes.append(producer)
        bound = subprocess.Popen(
            [sys.executable, "-c", limiter, str(limit)],
            stdin=producer.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(bound)
        producer.stdout.close()
        producer.stdout = None
        encryption = subprocess.Popen(
            ["age", "-r", recipient, "-o", str(target)],
            stdin=bound.stdout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        processes.append(encryption)
        bound.stdout.close()
        bound.stdout = None
        encryption.communicate(timeout=45)
        bound.communicate(timeout=5)
        producer.communicate(timeout=5)
        if any(process.returncode != 0 for process in processes):
            raise RuntimeError(
                "Bounded private export/encryption pipeline failed; diagnostics suppressed"
            )
        content = target.read_bytes()
        if (
            not content.startswith(b"age-encryption.org/v1")
            or len(content) > limit + 1048576
        ):
            raise RuntimeError("Encrypted export envelope invalid")
        return {
            "file": target.name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def ciphertext_custody(path, expected):
    wsl_path = subprocess.run(
        ["wsl", "-d", "Ubuntu", "--exec", "wslpath", "-u", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    copy = """import hashlib,json,pathlib,sys
source=pathlib.Path(sys.argv[1]);expected=sys.argv[2]
root=pathlib.Path("/home/alexg-anarchi/stewardence-backups")
assert source.name.startswith("current-candidate-") and source.name.endswith(".age")
data=source.read_bytes()
assert len(data)<=201*1048576 and data.startswith(b"age-encryption.org/v1")
assert hashlib.sha256(data).hexdigest()==expected
root.mkdir(mode=0o700,parents=True,exist_ok=True)
destination=root/source.name
with destination.open("xb") as output: output.write(data)
destination.chmod(0o600)
assert hashlib.sha256(destination.read_bytes()).hexdigest()==expected
print(json.dumps({"distribution":"Ubuntu","encrypted_path":str(destination),"sha256":expected,"key_copied":False}))"""
    response = subprocess.run(
        ["wsl", "-d", "Ubuntu", "--exec", "python3", "-c", copy, wsl_path, expected],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    return json.loads(response.stdout)


def main():
    if sys.argv[1:] != ["--run-local-only"]:
        raise SystemExit(
            "Explicit --run-local-only is required; coordinate a serialized qualification slot"
        )
    if not KEY.is_file() or not shutil.which("age") or not shutil.which("age-keygen"):
        raise SystemExit("Existing approved recovery key or age tools unavailable")
    recipient = subprocess.run(
        ["age-keygen", "-y", str(KEY)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    if re.fullmatch(r"age1[0-9a-z]+", recipient) is None:
        raise RuntimeError("Existing encryption recipient invalid")
    operator_id = str(uuid.uuid4())
    run = (
        ROOT
        / "evidence"
        / "current-restore-export"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    run.mkdir(parents=True)
    environment = dict(os.environ)
    environment["STEWARDENCE_RESTORE_EXPORT_OPERATOR_ID"] = operator_id
    process = None
    qualifier_run = None
    result = {
        "schema": "qualification.current_candidate_export.v1",
        "operator_id": operator_id,
        "passed": False,
        "restore_qualified": False,
        "production_touched": False,
        "device_loss_survival": False,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "streamer_sha256": hashlib.sha256(STREAM.encode()).hexdigest(),
    }
    try:
        with (run / "qualifier-output.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "scripts/qualify_local.py"),
                    "--restore-export",
                    "tests/test_capture_v4_restore_export.py",
                ],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            deadline = time.monotonic() + 1200
            ready = None
            ownership = None
            while ready is None:
                if process.poll() is not None:
                    raise RuntimeError(
                        "Held export qualifier ended before ready receipt"
                    )
                for candidate in (ROOT / "evidence").glob("*/ownership.json"):
                    try:
                        observed = json.loads(candidate.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue
                    if observed.get("restore_export_operator_id") == operator_id:
                        qualifier_run, ownership = candidate.parent, observed
                        ready_path = qualifier_run / "restore-export-ready.json"
                        if ready_path.exists():
                            ready = json.loads(ready_path.read_text(encoding="utf-8"))
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Held export qualifier readiness deadline exceeded"
                    )
                if ready is None:
                    time.sleep(0.2)
            if (
                ready.get("schema") != "qualification.local_restore_export_ready.v1"
                or ready.get("objects") != 2
                or ready.get("four_roles_no_bypass") is not True
                or ready.get("restore_qualified") is not False
                or ready.get("production_touched") is not False
                or type(ready.get("total_bytes")) is not int
                or not 0 < ready["total_bytes"] <= 32 * 1048576
            ):
                raise RuntimeError("Local export readiness semantics invalid")
            if (
                re.fullmatch(
                    r"/dev/shm/stewardence-restore-export-[0-9a-f]{32}",
                    ready["ram_directory"],
                )
                is None
                or re.fullmatch(r"[0-9a-f]{64}", ready["private_manifest_sha256"])
                is None
            ):
                raise RuntimeError("Local export RAM identity invalid")
            name = ownership["run_name"]
            if (
                not ownership.get("restore_export")
                or not ownership.get("http_renderer")
                or ownership.get("production_touched") is not False
            ):
                raise RuntimeError("Local export run authority invalid")
            app_id = exact_container(ownership["app_name"], name)
            db_id = exact_container(ownership["db_name"], name)
            catalog = json.loads(
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        db_id,
                        "psql",
                        "-U",
                        "postgres",
                        "-d",
                        "test_qualification",
                        "-Atqc",
                        CATALOG_SQL,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                ).stdout
            )
            catalog_hash = hashlib.sha256(
                json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            result.update(
                source_catalog_sha256=catalog_hash,
                source_catalog_counts={
                    key: len(value or []) for key, value in catalog.items()
                },
                source_catalog_contract_sha256=hashlib.sha256(
                    CATALOG_SQL.encode()
                ).hexdigest(),
                source_role_login_comparison="Excluded intentionally: recovered owner remains NOLOGIN; authority flags and inheritance are compared.",
            )
            prefix = "current-candidate-" + operator_id
            database = encrypt_stream(
                [
                    "docker",
                    "exec",
                    db_id,
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "test_qualification",
                    "--format=custom",
                    "--lock-wait-timeout=10s",
                ],
                run / (prefix + ".dump.age"),
                recipient,
                200 * 1048576,
            )
            objects = encrypt_stream(
                [
                    "docker",
                    "exec",
                    app_id,
                    "/app/.venv/bin/python",
                    "-c",
                    STREAM,
                    ready["ram_directory"],
                    ready["private_manifest_sha256"],
                ],
                run / (prefix + ".objects.tar.age"),
                recipient,
                128 * 1048576,
            )
            database["custody"] = ciphertext_custody(
                run / database["file"], database["sha256"]
            )
            objects["custody"] = ciphertext_custody(
                run / objects["file"], objects["sha256"]
            )
            result.update(
                qualifier_directory=str(qualifier_run),
                app_container_id=app_id,
                database_container_id=db_id,
                database=database,
                objects=objects,
                source_manifest_sha256=hashlib.sha256(
                    (qualifier_run / "source-manifest.json").read_bytes()
                ).hexdigest(),
                private_manifest_sha256=ready["private_manifest_sha256"],
                key_copied=False,
            )
            temporary = qualifier_run / "restore-export-release.pending"
            temporary.write_text(
                json.dumps(
                    {
                        "private_manifest_sha256": ready["private_manifest_sha256"],
                        "database_ciphertext_verified": True,
                        "objects_ciphertext_verified": True,
                    }
                ),
                encoding="utf-8",
            )
            temporary.replace(qualifier_run / "restore-export-release.json")
            if process.wait(timeout=120) != 0:
                raise RuntimeError("Held export qualifier failed after release")
            summary = json.loads(
                (qualifier_run / "qualification-summary.json").read_text(
                    encoding="utf-8"
                )
            )
            cleanup = json.loads(
                (qualifier_run / "cleanup.json").read_text(encoding="utf-8")
            )
            if (
                summary["exit_code"] != 0
                or summary["test_result_counts"]
                != {"cases": 1, "failed": 0, "errors": 0, "skipped": 0}
                or cleanup.get("passed") is not True
                or summary.get("cleanup_verified") is not True
            ):
                raise RuntimeError("Export execution/cleanup qualification incomplete")
            result["passed"] = True
    except Exception as error:
        result["error_type"] = type(error).__name__
        raise
    finally:
        # Do not kill the qualifier and strand its containers: withheld release
        # expires the bounded fixture, allowing its own fenced cleanup to run.
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=200)
            except subprocess.TimeoutExpired:
                result["qualifier_still_running"] = True
                result["passed"] = False
        (run / "export-summary.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "evidence_directory": str(run),
                "export_stage_passed": result["passed"],
                "restore_qualified": False,
                "production_touched": False,
            }
        )
    )


if __name__ == "__main__":
    main()
