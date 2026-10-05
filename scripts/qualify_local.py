"""Disposable local PostgreSQL qualification; never connects to production."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from qualify_release_renderer import cleanup_owned

ROOT = Path(__file__).resolve().parents[1]


def command(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def main():
    restore_export = "--restore-export" in sys.argv[1:]
    http_renderer = "--http-renderer" in sys.argv[1:] or restore_export
    test_arguments = [
        value
        for value in sys.argv[1:]
        if value not in {"--http-renderer", "--restore-export"}
    ]
    if restore_export and test_arguments != ["tests/test_capture_v4_restore_export.py"]:
        raise ValueError("Restore export admits only the exact held fixture")
    for argument in test_arguments:
        if argument.startswith("tests/"):
            test_path = ROOT / "source" / argument.split("::", 1)[0]
            if not test_path.exists():
                raise ValueError("Qualification test path does not exist: " + argument)
    name = "stewardence-local-" + uuid.uuid4().hex[:10]
    image = "stewardence-local-qualification:" + name
    (ROOT / "evidence").mkdir(exist_ok=True)
    run_dir = ROOT / "evidence" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir.mkdir()
    build_context = run_dir / "build-context"
    build_context.mkdir()
    shutil.copytree(
        ROOT / "source",
        build_context / "source",
        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache"),
    )
    shutil.copy2(
        ROOT / "Dockerfile.qualification", build_context / "Dockerfile.qualification"
    )
    shutil.copy2(ROOT / ".dockerignore", build_context / ".dockerignore")
    source_hashes = {
        str(p.relative_to(build_context / "source")): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in sorted((build_context / "source").rglob("*"))
        if p.is_file()
    }
    (run_dir / "source-manifest.json").write_text(
        json.dumps(source_hashes, indent=2), encoding="utf-8"
    )
    app_name = name + "-app"
    ownership = {
        "run_name": name,
        "app_name": app_name,
        "db_name": name + "-db",
        "network_name": name,
        "production_touched": False,
    }
    if restore_export:
        operator_id = os.environ.get("STEWARDENCE_RESTORE_EXPORT_OPERATOR_ID", "")
        if str(uuid.UUID(operator_id)) != operator_id:
            raise ValueError("Exact restore-export operator identity required")
        ownership.update(restore_export=True, restore_export_operator_id=operator_id)
    (run_dir / "ownership.json").write_text(
        json.dumps(ownership, indent=2), encoding="utf-8"
    )
    created_network = False
    created_db = False
    renderer_name = name + "-renderer"
    renderer_image = image + "-renderer"
    renderer_started = False
    http_environment = []
    coverage_requested = any(
        value == "--cov" or value.startswith("--cov=") for value in test_arguments
    )
    coverage_environment = (
        ["-e", "COVERAGE_FILE=/qualification-evidence/coverage-data"]
        if coverage_requested
        else []
    )
    if http_renderer:
        ownership.update(
            http_renderer=True,
            renderer_name=renderer_name,
            deployment_parity=False,
            harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            cleanup_harness_sha256=hashlib.sha256(
                (ROOT / "scripts/qualify_release_renderer.py").read_bytes()
            ).hexdigest(),
        )
        (run_dir / "ownership.json").write_text(
            json.dumps(ownership, indent=2), encoding="utf-8"
        )
    try:
        with (run_dir / "build.log").open("w", encoding="utf-8") as log:
            command(
                "build",
                "-t",
                image,
                "-f",
                str(build_context / "Dockerfile.qualification"),
                str(build_context),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            if http_renderer:
                command(
                    "build",
                    "-t",
                    renderer_image,
                    "-f",
                    str(build_context / "source/Dockerfile.renderer"),
                    str(build_context / "source"),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        command(
            "network",
            "create",
            "--internal",
            "--label",
            "stewardence.qualification.run=" + name,
            name,
            stdout=subprocess.DEVNULL,
        )
        created_network = True
        command(
            "run",
            "-d",
            "--name",
            name + "-db",
            "--label",
            "stewardence.qualification.run=" + name,
            "--network",
            name,
            "--network-alias",
            "qualification-db",
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--tmpfs",
            "/var/lib/postgresql:rw,size=512m",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            "POSTGRES_DB=qualification",
            "postgres:18.6",
            stdout=subprocess.DEVNULL,
        )
        created_db = True
        for _ in range(60):
            r = subprocess.run(
                [
                    "docker",
                    "exec",
                    name + "-db",
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    "qualification",
                ],
                capture_output=True,
                check=False,
            )
            if r.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable database readiness failed")
        if http_renderer:
            renderer_id = command(
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                renderer_image,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if not renderer_id.startswith("sha256:"):
                raise RuntimeError("Immutable renderer image identity required")
            (run_dir / "http-renderer.json").write_text(
                json.dumps(
                    {
                        "image": renderer_image,
                        "image_id": renderer_id,
                        "dockerfile_sha256": source_hashes["Dockerfile.renderer"],
                        "source_manifest_sha256": hashlib.sha256(
                            (run_dir / "source-manifest.json").read_bytes()
                        ).hexdigest(),
                        "deployment_parity": False,
                        "profile": {
                            "memory": "1g",
                            "pids": 512,
                            "init": True,
                            "read_only": False,
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            command(
                "run",
                "-d",
                "--init",
                "--name",
                renderer_name,
                "--label",
                "stewardence.qualification.run=" + name,
                "--network",
                name,
                "--network-alias",
                "qualification-renderer",
                "--memory",
                "1g",
                "--pids-limit",
                "512",
                renderer_id,
                stdout=subprocess.DEVNULL,
            )
            renderer_started = True
            health = "import urllib.request; response=urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=1); assert response.status==200"
            for _ in range(40):
                ready = subprocess.run(
                    [
                        "docker",
                        "exec",
                        renderer_name,
                        "/app/.venv/bin/python",
                        "-c",
                        health,
                    ],
                    capture_output=True,
                    check=False,
                )
                if ready.returncode == 0:
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("Isolated HTTP renderer readiness failed")
            http_environment = [
                "-e",
                "STEWARDENCE_HTTP_RENDER_QUALIFICATION_URL=http://qualification-renderer:8080",
            ]
            if restore_export:
                http_environment += ["-e", "STEWARDENCE_RESTORE_EXPORT_HOLD=1"]
        with (run_dir / "qualification.log").open("w", encoding="utf-8") as log:
            r = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--init",
                    "--name",
                    app_name,
                    "--label",
                    "stewardence.qualification.run=" + name,
                    "--network",
                    name,
                    "--memory",
                    "1g",
                    "--pids-limit",
                    "512",
                    "--mount",
                    "type=bind,source="
                    + str(run_dir)
                    + ",target=/qualification-evidence",
                    "-e",
                    "DATABASE_ADMIN_URL=postgresql://postgres@qualification-db:5432/qualification",
                    "-e",
                    "DJANGO_SETTINGS_MODULE=agentledger.settings.development",
                    "-e",
                    "STEWARDENCE_REAL_PDF_QUALIFICATION=1",
                    *http_environment,
                    *coverage_environment,
                    image,
                    "/app/.venv/bin/python",
                    "scripts/verify_rls.py",
                    *(test_arguments or ["tests"]),
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--junitxml=/qualification-evidence/test-results.xml",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        summary = {
            "exit_code": r.returncode,
            "live_providers_tested": False,
            "production_touched": False,
            "image": image,
        }
        summary["image_id"] = command(
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            image,
            capture_output=True,
            text=True,
        ).stdout.strip()
        summary["evidence_directory"] = str(run_dir)
        summary["test_arguments"] = test_arguments or ["tests"]
        if coverage_requested:
            coverage_xml = run_dir / "coverage.xml"
            summary["coverage"] = {
                "requested": True,
                "xml_present": coverage_xml.is_file(),
                "threshold_qualified": False,
            }
            if coverage_xml.is_file():
                summary["coverage"]["xml_sha256"] = hashlib.sha256(
                    coverage_xml.read_bytes()
                ).hexdigest()
                coverage_root = ET.parse(coverage_xml).getroot()
                summary["coverage"]["line_rate"] = coverage_root.attrib.get("line-rate")
                summary["coverage"]["branch_rate"] = coverage_root.attrib.get(
                    "branch-rate"
                )
                # pytest-cov's exit status includes the configured coverage
                # threshold. A missing XML never qualifies that gate.
                summary["coverage"]["threshold_qualified"] = r.returncode == 0
        if http_renderer:
            summary["http_renderer"] = True
            summary["deployment_parity"] = False
        results = run_dir / "test-results.xml"
        if results.exists():
            cases = list(ET.parse(results).getroot().iter("testcase"))
            summary["test_result_counts"] = {
                "cases": len(cases),
                "failed": sum(case.find("failure") is not None for case in cases),
                "errors": sum(case.find("error") is not None for case in cases),
                "skipped": sum(case.find("skipped") is not None for case in cases),
            }
            summary["test_results_sha256"] = hashlib.sha256(
                results.read_bytes()
            ).hexdigest()
        if r.returncode == 0 and (
            not results.exists() or not summary["test_result_counts"]["cases"]
        ):
            raise RuntimeError("Passing qualification requires named execution results")
        (run_dir / "qualification-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        (ROOT / "evidence/qualification-summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary))
        print(
            "\n".join(
                (run_dir / "qualification.log")
                .read_text(encoding="utf-8")
                .splitlines()[-45:]
            )
        )
        return r.returncode
    finally:
        if http_renderer:
            if renderer_started:
                with (run_dir / "http-renderer.log").open("w", encoding="utf-8") as log:
                    subprocess.run(
                        ["docker", "logs", renderer_name],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
            resources = [
                cleanup_owned(value, "container", name, "stewardence.qualification.run")
                for value in (app_name, renderer_name, name + "-db")
            ]
            resources.append(
                cleanup_owned(name, "network", name, "stewardence.qualification.run")
            )
            cleanup_passed = all(resource["passed"] for resource in resources)
            (run_dir / "cleanup.json").write_text(
                json.dumps(
                    {"passed": cleanup_passed, "resources": resources}, indent=2
                ),
                encoding="utf-8",
            )
            summary_path = run_dir / "qualification-summary.json"
            if summary_path.exists():
                final_summary = json.loads(summary_path.read_text(encoding="utf-8"))
                final_summary["cleanup_verified"] = cleanup_passed
                if not cleanup_passed:
                    final_summary["exit_code"] = 1
                for target in (
                    summary_path,
                    ROOT / "evidence/qualification-summary.json",
                ):
                    target.write_text(
                        json.dumps(final_summary, indent=2), encoding="utf-8"
                    )
            if not cleanup_passed and sys.exc_info()[0] is None:
                raise RuntimeError("HTTP qualification cleanup failed")
        if not http_renderer:
            cleanup_default(run_dir, app_name, name, created_db, created_network)


def cleanup_default(run_dir, app_name, name, created_db, created_network):
    probe = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "stewardence.qualification.run"}}',
            app_name,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    removed_app = False
    if probe.returncode == 0 and probe.stdout.strip() == name:
        cleanup = subprocess.run(
            ["docker", "rm", "-f", app_name], capture_output=True, check=False
        )
        removed_app = cleanup.returncode == 0
    cleanup_result = {
        "app_cleanup_attempted": probe.returncode == 0,
        "owned_app_removed": removed_app,
        "db_cleanup_attempted": created_db,
        "network_cleanup_attempted": created_network,
        "db_cleanup_exit_code": None,
        "network_cleanup_exit_code": None,
    }
    if created_db:
        cleanup_result["db_cleanup_exit_code"] = subprocess.run(
            ["docker", "rm", "-f", name + "-db"], capture_output=True, check=False
        ).returncode
    if created_network:
        cleanup_result["network_cleanup_exit_code"] = subprocess.run(
            ["docker", "network", "rm", name], capture_output=True, check=False
        ).returncode
    (run_dir / "cleanup.json").write_text(
        json.dumps(cleanup_result, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
