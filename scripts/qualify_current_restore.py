"""Additive local DB/object restore scaffold; source-catalog gate stays explicit.

No operation occurs without --run-local-only and a passed export receipt.
Never uses SSH, a live bucket, key rotation or plaintext host dump files.
"""

import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from current_restore_catalog import SQL as CATALOG
from prepare_current_restore_export import KEY, ROOT
from qualify_release_renderer import cleanup_owned

EXTRACT = """import hashlib,io,json,sys,tarfile
from pathlib import Path
from uuid import UUID
root=Path("/restore")
assert root.exists()
objects=[];manifest=None;total=0
with tarfile.open(fileobj=sys.stdin.buffer,mode="r|") as archive:
 for item in archive:
  assert item.isfile() and not item.issym() and not item.islnk()
  assert item.size<=16*1048576
  total+=item.size
  assert total<=128*1048576
  source=archive.extractfile(item)
  content=source.read(item.size+1)
  assert len(content)==item.size
  if item.name=="manifest.json":
   assert manifest is None and hashlib.sha256(content).hexdigest()==sys.argv[1]
   manifest=json.loads(content)
   (root/"manifest.json").write_bytes(content)
  else:
   assert item.name.startswith("objects/") and item.name.endswith(".pdf")
   identity=item.name[len("objects/"):-4]
   assert str(UUID(identity))==identity and identity not in objects
   (root/(identity+".pdf")).write_bytes(content)
   objects.append(identity)
assert manifest["schema"]=="qualification.local_report_restore_export.v1"
assert len(manifest["objects"])==2 and len(objects)==2
assert {a["artifact_id"] for a in manifest["objects"]}==set(objects)
for a in manifest["objects"]:
 for key in ("artifact_id","organization_id","report_id","snapshot_id","request_id","pack_id","completion_id"):
  assert str(UUID(a[key]))==a[key]
 content=(root/(a["artifact_id"]+".pdf")).read_bytes()
 assert len(content)==a["size_bytes"] and hashlib.sha256(content).hexdigest()==a["sha256"]
 assert a["object_key"]=="organizations/"+a["organization_id"]+"/assessments/"+a["snapshot_id"]+"/reports/"+a["report_id"]+".pdf"
 destination=root/"private"/a["object_key"]
 destination.parent.mkdir(parents=True,exist_ok=True)
 destination.write_bytes(content)
print(json.dumps({"strict_manifest_and_objects":2,"plaintext_location":"container_tmpfs_only"}))
"""


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def decrypt_into(custody, expected_sha, command):
    path = custody["encrypted_path"]
    if (
        custody.get("distribution") != "Ubuntu"
        or custody.get("key_copied") is not False
        or custody.get("sha256") != expected_sha
        or not path.startswith(
            "/home/alexg-anarchi/stewardence-backups/current-candidate-"
        )
        or not path.endswith(".age")
    ):
        raise RuntimeError("Approved ciphertext custody binding required")
    if (
        PurePosixPath(path).parent
        != PurePosixPath("/home/alexg-anarchi/stewardence-backups")
        or re.fullmatch(
            r"current-candidate-[0-9a-f-]{36}\.(dump|objects\.tar)\.age",
            PurePosixPath(path).name,
        )
        is None
    ):
        raise RuntimeError("Ciphertext custody path must be an exact approved child")
    reader = "import hashlib,pathlib,sys;data=pathlib.Path(sys.argv[1]).read_bytes();assert len(data)<=201*1048576;assert hashlib.sha256(data).hexdigest()==sys.argv[2];sys.stdout.buffer.write(data)"
    processes = []
    try:
        cipher = subprocess.Popen(
            [
                "wsl",
                "-d",
                "Ubuntu",
                "--exec",
                "python3",
                "-c",
                reader,
                path,
                expected_sha,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(cipher)
        decrypt = subprocess.Popen(
            ["age", "-d", "-i", str(KEY)],
            stdin=cipher.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(decrypt)
        cipher.stdout.close()
        cipher.stdout = None
        target = subprocess.Popen(
            command,
            stdin=decrypt.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(target)
        decrypt.stdout.close()
        decrypt.stdout = None
        output, _ = target.communicate(timeout=120)
        decrypt.communicate(timeout=10)
        cipher.communicate(timeout=10)
        if any(item.returncode != 0 for item in processes):
            raise RuntimeError(
                "Private decrypt/restore pipeline failed; diagnostics suppressed"
            )
        return output
    finally:
        for item in processes:
            if item.poll() is None:
                item.kill()
                item.wait(timeout=5)


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--run-local-only":
        raise SystemExit(
            "Usage: --run-local-only followed by an explicit passed export-summary.json path"
        )
    export_path = Path(sys.argv[2]).resolve()
    if (
        not export_path.is_relative_to(
            (ROOT / "evidence/current-restore-export").resolve()
        )
        or export_path.name != "export-summary.json"
    ):
        raise RuntimeError("Exact local export receipt location required")
    export = json.loads(export_path.read_text(encoding="utf-8"))
    if (
        export.get("schema") != "qualification.current_candidate_export.v1"
        or export.get("passed") is not True
        or export.get("production_touched") is not False
        or not KEY.is_file()
    ):
        raise RuntimeError("Passed local export and existing key required")
    qualifier = Path(export["qualifier_directory"]).resolve()
    if (
        qualifier.parent != (ROOT / "evidence").resolve()
        or re.fullmatch(r"[0-9]{8}T[0-9]{6}\.[0-9]{6}Z", qualifier.name) is None
    ):
        raise RuntimeError("Exact disposable source qualification directory required")
    manifest_path = qualifier / "source-manifest.json"
    if (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        != export["source_manifest_sha256"]
    ):
        raise RuntimeError("Export source manifest changed")
    source = qualifier / "build-context/source"
    for relative, expected in json.loads(
        manifest_path.read_text(encoding="utf-8")
    ).items():
        candidate = (source / relative).resolve()
        if (
            not candidate.is_relative_to(source.resolve())
            or hashlib.sha256(candidate.read_bytes()).hexdigest() != expected
        ):
            raise RuntimeError("Frozen export source unavailable or changed")
    name = "stewardence-current-restore-" + uuid.uuid4().hex[:12]
    db_name, app_name = name + "-db", name + "-app"
    run = (
        ROOT
        / "evidence/current-restore"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    run.mkdir(parents=True)
    result = {
        "schema": "qualification.current_candidate_restore.v1",
        "passed": False,
        "production_touched": False,
        "source_catalog_comparison_qualified": False,
        "private_http_replay_qualified": False,
        "restore_qualified": False,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "export_summary_sha256": hashlib.sha256(export_path.read_bytes()).hexdigest(),
    }
    ownership = {
        "network": name,
        "containers": [db_name, app_name],
        "scope": "isolated_synthetic_restore_only",
        "production_touched": False,
        "deployment_parity": False,
    }
    (run / "ownership.json").write_text(
        json.dumps(ownership, indent=2), encoding="utf-8"
    )
    try:
        image = name + ":app"
        with (run / "build.log").open("w", encoding="utf-8") as log:
            docker(
                "build",
                "-t",
                image,
                "-f",
                str(source / "Dockerfile"),
                str(source),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        app_id = docker(
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            image,
            capture_output=True,
            text=True,
        ).stdout.strip()
        pg_id = docker(
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "postgres:18.6",
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not all(
            re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in (app_id, pg_id)
        ):
            raise RuntimeError("Immutable restore image identities required")
        (run / "image-identities.json").write_text(
            json.dumps({"app": app_id, "postgres": pg_id}, indent=2)
        )
        docker(
            "network",
            "create",
            "--internal",
            "--label",
            "stewardence.release-qualification=" + name,
            name,
            stdout=subprocess.DEVNULL,
        )
        docker(
            "run",
            "-d",
            "--name",
            db_name,
            "--label",
            "stewardence.release-qualification=" + name,
            "--network",
            name,
            "--network-alias",
            "restore-db",
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/var/lib/postgresql:rw,size=512m",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=restored",
            pg_id,
            stdout=subprocess.DEVNULL,
        )
        for _ in range(60):
            response = subprocess.run(
                [
                    "docker",
                    "exec",
                    db_name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    "restored",
                ],
                capture_output=True,
                check=False,
            )
            if response.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable restore database readiness failed")
        ddl = (
            "CREATE ROLE agentledger_owner NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;"
            + "".join(
                "CREATE ROLE " + role + " NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT;"
                for role in (
                    "agentledger_app",
                    "agentledger_worker",
                    "agentledger_billing_admission",
                )
            )
        )
        docker(
            "exec",
            db_name,
            "psql",
            "-U",
            "postgres",
            "-d",
            "restored",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            ddl,
            capture_output=True,
        )
        decrypt_into(
            export["database"]["custody"],
            export["database"]["sha256"],
            [
                "docker",
                "exec",
                "-i",
                db_name,
                "pg_restore",
                "-U",
                "postgres",
                "-d",
                "restored",
                "--exit-on-error",
            ],
        )
        catalog = json.loads(
            docker(
                "exec",
                db_name,
                "psql",
                "-U",
                "postgres",
                "-d",
                "restored",
                "-Atqc",
                CATALOG,
                capture_output=True,
                text=True,
            ).stdout
        )
        assert len(catalog["roles"]) == 4 and all(
            not role[1] and not role[2] and not role[3] for role in catalog["roles"]
        )
        fingerprint = hashlib.sha256(
            json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        result.update(
            restored_catalog_sha256=fingerprint,
            restored_tables=len(catalog["tables"]),
            restored_migrations=len(catalog["migrations"]),
            four_roles_no_superuser_or_bypass=True,
            owner_nologin=True,
        )
        catalog_contract = hashlib.sha256(CATALOG.encode()).hexdigest()
        result["catalog_contract_sha256"] = catalog_contract
        if export.get("source_catalog_sha256"):
            if export.get("source_catalog_contract_sha256") != catalog_contract:
                raise RuntimeError("Source catalog protocol changed")
            if export["source_catalog_sha256"] != fingerprint:
                raise RuntimeError("Restored catalog does not match original source")
            result["source_catalog_comparison_qualified"] = True
        else:
            result["source_catalog_limitation"] = (
                "Export predates original catalog capture; restored-only fingerprint is not comparison proof"
            )
        # Only the isolated application's LOGIN capability is activated after
        # restoring and fingerprinting. No new privileges or membership.
        docker(
            "exec",
            db_name,
            "psql",
            "-U",
            "postgres",
            "-d",
            "restored",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "ALTER ROLE agentledger_app LOGIN;",
            capture_output=True,
        )
        environment = [
            "DJANGO_SETTINGS_MODULE=agentledger.settings.production",
            "DJANGO_SECRET_KEY=qualification-build-only-abcABC0123456789-not-runtime-authority",
            "DATABASE_URL=postgresql://agentledger_app@restore-db:5432/restored",
            "CURRENT_RESTORE_BOOTSTRAP_DATABASE_URL=postgresql://postgres@restore-db:5432/restored",
            "CURRENT_RESTORE_ISOLATED=1",
            "ALLOWED_HOSTS=testserver",
            "CSRF_TRUSTED_ORIGINS=https://testserver",
            "REPORTS_BUCKET_NAME=qualification-unreachable",
            "REPORTS_BUCKET_ENDPOINT=https://localhost",
            "REPORTS_BUCKET_ACCESS_KEY_ID=qualification-noncredential",
            "REPORTS_BUCKET_SECRET_ACCESS_KEY=qualification-noncredential",
            "REPORT_RENDERER_URL=http://unreachable:8080",
        ]
        env_args = [part for value in environment for part in ("-e", value)]
        # The application image holds only strict extracted object data in RAM;
        # no key enters it and no external bucket is configured or contacted.
        docker(
            "run",
            "-d",
            "--init",
            "--name",
            app_name,
            "--label",
            "stewardence.release-qualification=" + name,
            "--network",
            name,
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/restore:rw,size=128m,mode=0700,uid=10001,gid=10001",
            *env_args,
            app_id,
            "/app/.venv/bin/python",
            "-c",
            "import time; time.sleep(600)",
            stdout=subprocess.DEVNULL,
        )
        decoded = decrypt_into(
            export["objects"]["custody"],
            export["objects"]["sha256"],
            [
                "docker",
                "exec",
                "-i",
                app_name,
                "/app/.venv/bin/python",
                "-c",
                EXTRACT,
                export["private_manifest_sha256"],
            ],
        )
        if json.loads(decoded)["strict_manifest_and_objects"] != 2:
            raise RuntimeError("Strict restored object completeness failed")
        probe_path = ROOT / "scripts/current_restored_access_probe.py"
        result["access_probe_sha256"] = hashlib.sha256(
            probe_path.read_bytes()
        ).hexdigest()
        probe = docker(
            "exec",
            "-i",
            app_name,
            "/app/.venv/bin/python",
            "-c",
            "import sys;exec(compile(sys.stdin.read(),'<restore-access-probe>','exec'))",
            input=probe_path.read_bytes(),
            capture_output=True,
            timeout=120,
        )
        access = json.loads(probe.stdout)
        if access.get("passed") is not True:
            raise RuntimeError("Restored actual-role private access probe failed")
        (run / "private-access-results.json").write_text(
            json.dumps(access, indent=2), encoding="utf-8"
        )
        result["private_http_replay_qualified"] = True
        result["restore_qualified"] = result["source_catalog_comparison_qualified"]
        result.update(
            database_stream_restored=True,
            strict_ram_objects_restored=2,
            plaintext_host_files=False,
            key_copied=False,
            passed=True,
        )
        # A prior export without source catalog still cannot establish an
        # original-vs-restored privilege comparison, even when replay passes.
    except Exception as error:
        result["error_type"] = type(error).__name__
        raise
    finally:
        cleanup = [
            cleanup_owned(value, "container", name) for value in (app_name, db_name)
        ]
        cleanup.append(cleanup_owned(name, "network", name))
        verified = all(item["passed"] for item in cleanup)
        (run / "cleanup.json").write_text(
            json.dumps({"passed": verified, "resources": cleanup}, indent=2)
        )
        result["cleanup_verified"] = verified
        result["passed"] = result["passed"] and verified
        result["restore_qualified"] = result["restore_qualified"] and verified
        (run / "restore-summary.json").write_text(json.dumps(result, indent=2))
        if not verified and sys.exc_info()[0] is None:
            raise RuntimeError("Fresh restore cleanup incomplete")
    print(
        json.dumps(
            {
                "evidence_directory": str(run),
                "bounded_restore_stage_passed": result["passed"],
                "restore_qualified": result["restore_qualified"],
                "production_touched": False,
            }
        )
    )


if __name__ == "__main__":
    main()
