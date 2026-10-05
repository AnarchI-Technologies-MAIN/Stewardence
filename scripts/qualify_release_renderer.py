"""Opt-in local release-image qualification; no provider, database or deployment.

Run only in the parent's serialized qualification slot. This harness builds
both actual product Dockerfiles, rather than the combined qualification image.
"""

import ast
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], check=True, **kwargs)


def cleanup_owned(name, kind, run_label, label_key="stewardence.release-qualification"):
    """Exact name and exact label, followed by a successful absence query."""
    inspect = ["docker"]
    if kind == "network":
        inspect += ["network"]
    inspect += ["inspect", "--format"]
    labels = ".Labels" if kind == "network" else ".Config.Labels"
    inspect += ["{{index " + labels + ' "' + label_key + '"}}', name]
    observed = subprocess.run(inspect, capture_output=True, text=True, check=False)
    removed = None
    mismatch = False
    if observed.returncode == 0:
        if observed.stdout.strip() == run_label:
            remove = (
                ["docker", "network", "rm", name]
                if kind == "network"
                else ["docker", "rm", "-f", name]
            )
            removed = subprocess.run(
                remove, capture_output=True, text=True, check=False
            )
        if observed.stdout.strip() != run_label:
            mismatch = True
    listing = (
        ["docker", "network", "ls"] if kind == "network" else ["docker", "ps", "-a"]
    )
    listing += ["--format", "{{.Name}}" if kind == "network" else "{{.Names}}"]
    after = subprocess.run(listing, capture_output=True, text=True, check=False)
    absent = after.returncode == 0 and name not in after.stdout.splitlines()
    return {
        "name": name,
        "kind": kind,
        "inspect_returncode": observed.returncode,
        "label_matched": observed.returncode == 0 and not mismatch,
        "label_mismatch": mismatch,
        "remove_returncode": removed.returncode if removed is not None else None,
        "absence_query_returncode": after.returncode,
        "absent": absent,
        "passed": absent
        and not mismatch
        and (removed is None or removed.returncode == 0),
    }


def functions(source, names):
    tree = ast.parse(source.read_text(encoding="utf-8"))
    return "\n\n".join(
        ast.unparse(node)
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    )


def client_script(source):
    # Frozen synthetic fixture bodies create no ORM rows/issued receipts.
    helpers = "\n\n".join(
        [
            functions(source / "tests/test_capture_contract.py", {"record", "args"}),
            functions(
                source / "tests/test_capture_review_renderer.py", {"capture_projection"}
            ),
            functions(
                source / "tests/test_capture_v4_renderer.py",
                {"v4_projection", "add_statements"},
            ),
        ]
    )
    return (
        """import hashlib, importlib.util, json, os, time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4
import django
django.setup()
assert os.getuid() == 10001
assert importlib.util.find_spec("renderer") is None
assert importlib.util.find_spec("pytest") is None
from apps.assessments.capture_v1 import build_capture_payloads
from apps.inventory.provenance import DECLARED, INVENTORY_FACT_FIELDS, UNKNOWN
from apps.reviews.capture_context import digest
from apps.reviews.capture_context_v3 import build_capture_v4_pack_context
from apps.reviews.capture_event_v2 import validate_frozen_capture_selection
from apps.reviews.proposals_v1 import APPLICABILITY_VERSION, build_review_proposals
from apps.reports.render_client import HTTPReportRenderer, ReportRenderError
"""
        + helpers
        + """
original_args = args
def args(industry):
    pins = original_args(industry)
    if industry == "accounting_bookkeeping":
        row = pins["inventory_records"][0]
        for key, value in {"data_categories":["payroll"],"capabilities":["external_transfer"],"human_approval":False}.items():
            row[key], row["provenance"][key] = value, "Declared"
    return pins
results=[]
renderer=HTTPReportRenderer(base_url="http://release-renderer:8080",timeout_seconds=70)
for industry in ("other","accounting_bookkeeping"):
    metadata, projection=v4_projection(industry)
    add_statements(projection)
    context=build_capture_v4_pack_context(metadata,projection)
    if industry == "accounting_bookkeeping":
        assert any(e["proposal"]["source"]["class"] == "accounting_fail" for e in projection["selected_proposals"])
    start=time.monotonic()
    pdf=renderer.render(context)
    elapsed=time.monotonic()-start
    stem=Path("/qualification")/industry
    stem.with_suffix(".pdf").write_bytes(pdf)
    stem.with_suffix(".json").write_text(json.dumps(context,ensure_ascii=False),encoding="utf-8")
    results.append({"industry":industry,"elapsed_seconds":elapsed,"pdf_bytes":len(pdf),"pdf_sha256":hashlib.sha256(pdf).hexdigest(),"context_sha256":digest(context),"context_bytes":len(json.dumps(context,ensure_ascii=False,separators=(",",":")).encode()),"transport":"actual_app_HTTPReportRenderer_to_actual_renderer_v1_render","database_issuance":False})
try:
    renderer.render({"context_version":"unadmitted_unknown"})
    raise AssertionError("Malformed HTTP render payload was admitted")
except ReportRenderError as error:
    assert "HTTP 422" in str(error)
Path("/qualification/http-results.json").write_text(json.dumps(results,indent=2))
print(json.dumps({"actual_app_uid":os.getuid(),"renderer_package_absent":True,"pytest_absent":True,"http_specimens":len(results)}))
"""
    )


def main():
    if sys.argv[1:] != ["--run-local-only"]:
        raise SystemExit(
            "Explicit --run-local-only is required; coordinate the qualification slot first"
        )
    name = "stewardence-release-" + uuid.uuid4().hex[:12]
    run = (
        ROOT
        / "evidence"
        / "release-renderer"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    source = run / "source"
    source.parent.mkdir(parents=True)
    shutil.copytree(
        ROOT / "source",
        source,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", ".pytest_cache", ".env*"
        ),
    )
    manifest = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*"))
        if p.is_file()
    }
    (run / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    client_path = run / "client.py"
    client_path.write_text(client_script(source), encoding="utf-8")
    app_image, renderer_image = name + ":app", name + ":renderer"
    renderer_name, app_name = name + "-renderer", name + "-app"
    check_name, verifier_name = name + "-check", name + "-verifier"
    ownership = {
        "network": name,
        "containers": [renderer_name, app_name, check_name, verifier_name],
        "images": [app_image, renderer_image],
        "production_touched": False,
        "scope": "synthetic_no_database_issuance",
        "deployment_parity": False,
        "renderer_profile": {
            "memory": "1g",
            "pids": 512,
            "init": True,
            "read_only": False,
            "custom_seccomp": False,
            "cap_drop_all": False,
            "no_new_privileges": False,
        },
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "client_sha256": hashlib.sha256(client_path.read_bytes()).hexdigest(),
        "dockerfile_sha256": {
            key: manifest[key] for key in ("Dockerfile", "Dockerfile.renderer")
        },
    }
    (run / "ownership.json").write_text(json.dumps(ownership, indent=2))
    renderer_started = False
    environment = [
        "DJANGO_SETTINGS_MODULE=agentledger.settings.production",
        "DJANGO_SECRET_KEY=qualification-build-only-abcABC0123456789-not-runtime-authority",
        "DATABASE_URL=postgresql://qualification:qualification@127.0.0.1:1/unreachable",
        "ALLOWED_HOSTS=localhost",
        "CSRF_TRUSTED_ORIGINS=https://localhost",
        "REPORTS_BUCKET_NAME=qualification",
        "REPORTS_BUCKET_ENDPOINT=https://localhost",
        "REPORTS_BUCKET_ACCESS_KEY_ID=qualification-noncredential",
        "REPORTS_BUCKET_SECRET_ACCESS_KEY=qualification-noncredential",
        "REPORT_RENDERER_URL=http://release-renderer:8080",
    ]
    env_args = [item for value in environment for item in ("-e", value)]
    try:
        with (run / "build.log").open("w", encoding="utf-8") as log:
            for image, dockerfile in (
                (app_image, "Dockerfile"),
                (renderer_image, "Dockerfile.renderer"),
            ):
                docker(
                    "build",
                    "-t",
                    image,
                    "-f",
                    str(source / dockerfile),
                    str(source),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
        image_ids = {}
        for image in (app_image, renderer_image):
            resolved = docker(
                "image",
                "inspect",
                "--format",
                "{{.Id}}",
                image,
                capture_output=True,
                text=True,
            )
            image_ids[image] = resolved.stdout.strip()
            if not image_ids[image].startswith("sha256:"):
                raise ValueError("Immutable image identity required")
        (run / "image-identities.json").write_text(
            json.dumps(image_ids, indent=2), encoding="utf-8"
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
            "--init",
            "--name",
            renderer_name,
            "--label",
            "stewardence.release-qualification=" + name,
            "--network",
            name,
            "--network-alias",
            "release-renderer",
            "--memory",
            "1g",
            "--pids-limit",
            "512",
            renderer_image,
            stdout=subprocess.DEVNULL,
        )
        renderer_started = True
        with (run / "qualification.log").open("w", encoding="utf-8") as log:
            # Native browser permissions and module isolation in actual image.
            probe = """import importlib.util, json, os, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
from renderer.capture_pack_v4_schema import validate_capture_v4_render_payload
assert os.getuid()==10001
assert importlib.util.find_spec("apps") is None
assert os.access("/work/output",os.W_OK)
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,chromium_sandbox=False)
 assert browser.is_connected()
 browser.close()
deadline=time.monotonic()+10
while True:
 try:
  with urllib.request.urlopen("http://127.0.0.1:8080/healthz",timeout=1) as response:
   assert response.status==200
  break
 except OSError:
  if time.monotonic()>=deadline:
   raise
  time.sleep(0.1)
print(json.dumps({"renderer_uid":os.getuid(),"apps_absent":True,"output_writable":True,"actual_headless_launch_and_close":True}))"""
            docker(
                "exec",
                renderer_name,
                "/app/.venv/bin/python",
                "-c",
                probe,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            docker(
                "run",
                "--rm",
                "--init",
                "--name",
                check_name,
                "--label",
                "stewardence.release-qualification=" + name,
                "--network",
                name,
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                *env_args,
                app_image,
                "/app/.venv/bin/python",
                "manage.py",
                "check",
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            docker(
                "run",
                "--rm",
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
                "--mount",
                "type=bind,source=" + str(run) + ",target=/qualification",
                *env_args,
                app_image,
                "/app/.venv/bin/python",
                "/qualification/client.py",
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            # Parse saved PDFs with actual renderer dependencies, not app tools.
            verify = """import json
from pathlib import Path
from pypdf import PdfReader
for industry in ("other","accounting_bookkeeping"):
 text=" ".join(" ".join(p.extract_text() or "" for p in PdfReader(Path("/qualification")/(industry+".pdf")).pages).split())
 assert "Risk: not assessed" in text and "Benefit model: not supplied" in text
 assert "disposition: act" in text and "execution: completion_recorded" in text
 assert "Original outcome: UNKNOWN" in text
print(json.dumps({"semantic_pdf_checks":2,"scope":"synthetic_not_admitted"}))"""
            docker(
                "run",
                "--rm",
                "--init",
                "--name",
                verifier_name,
                "--network",
                name,
                "--label",
                "stewardence.release-qualification=" + name,
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--mount",
                "type=bind,source=" + str(run) + ",target=/qualification,readonly",
                renderer_image,
                "/app/.venv/bin/python",
                "-c",
                verify,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        (run / "result.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "production_touched": False,
                    "database_issuance": False,
                }
            )
        )
    except Exception as error:
        (run / "result.json").write_text(
            json.dumps(
                {
                    "passed": False,
                    "error_type": type(error).__name__,
                    "production_touched": False,
                }
            )
        )
        raise
    finally:
        if renderer_started:
            with (run / "renderer.log").open("w", encoding="utf-8") as log:
                subprocess.run(
                    ["docker", "logs", renderer_name],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            with (run / "renderer-inspect.json").open("w", encoding="utf-8") as state:
                subprocess.run(
                    ["docker", "inspect", "--format", "{{json .State}}", renderer_name],
                    stdout=state,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
        cleanup = [
            cleanup_owned(container, "container", name)
            for container in ownership["containers"]
        ]
        cleanup.append(cleanup_owned(name, "network", name))
        cleanup_passed = all(item["passed"] for item in cleanup)
        (run / "cleanup.json").write_text(
            json.dumps({"passed": cleanup_passed, "resources": cleanup}, indent=2),
            encoding="utf-8",
        )
        result_path = run / "result.json"
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["cleanup_verified"] = cleanup_passed
            result["passed"] = result["passed"] and cleanup_passed
            result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not cleanup_passed and sys.exc_info()[0] is None:
            raise RuntimeError(
                "Release qualification cleanup failed; inspect cleanup receipt"
            )
    print(str(run))


if __name__ == "__main__":
    main()
