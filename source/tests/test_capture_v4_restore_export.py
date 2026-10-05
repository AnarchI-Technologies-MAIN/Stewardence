"""Explicitly gated RAM-only export barrier; no completed restore claim."""

import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import connections

from apps.reports.models import ReportArtifact
from apps.reports.storage import LocalPrivateReportStorage, ReportStorageError
from apps.reviews.models import PackCompletion
from tests.test_capture_admission import capture_context as capture_context
from tests.test_capture_admission import explicit_context as explicit_context
from tests.test_capture_v4_worker import (
    test_capture_v4_actual_worker_chromium_private_owner_delivery as run_journey,
)
from tests.test_review_pack_lifecycle import enabled as enabled

__all__ = ["capture_context", "explicit_context", "enabled"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.mark.skipif(
    os.environ.get("STEWARDENCE_RESTORE_EXPORT_HOLD") != "1",
    reason="Explicit isolated restore-export hold is not requested",
)
def test_two_actual_v4_journeys_hold_database_and_ram_objects_for_encrypted_export(
    capture_context, enabled, client, settings, monkeypatch
):
    assert (
        os.environ.get("STEWARDENCE_HTTP_RENDER_QUALIFICATION_URL")
        == "http://qualification-renderer:8080"
    )
    assert (
        os.environ.get("DJANGO_SETTINGS_MODULE") == "agentledger.settings.development"
    )
    assert os.environ.get("DATABASE_ADMIN_URL", "").startswith(
        "postgresql://postgres@qualification-db:"
    )
    evidence = Path("/qualification-evidence")
    assert evidence.is_dir()
    ram = Path("/dev/shm") / ("stewardence-restore-export-" + uuid4().hex)  # noqa: S108 - unique, private container tmpfs only.
    ram.mkdir(mode=0o700)
    original_middleware = list(settings.MIDDLEWARE)
    for industry in ("other", "accounting_bookkeeping"):
        settings.MIDDLEWARE = list(original_middleware)
        # Rebuild the client: the first journey's viewer privacy phase changes
        # its middleware stack; that change must not weaken the second owner.
        from django.test import Client

        journey_client = Client()
        run_journey(
            capture_context,
            enabled,
            ram / industry,
            industry,
            journey_client,
            settings,
            monkeypatch,
        )
    settings.MIDDLEWARE = original_middleware
    _, org = capture_context
    objects = list(ReportArtifact.objects.filter(organization=org).order_by("id"))
    assert len(objects) == 2
    manifest = []
    for artifact in objects:
        completion = PackCompletion.objects.select_related("request__pack").get(
            artifact=artifact
        )
        assert completion.payload["verification"] == "trusted_handler_storage_readback"
        pack = completion.request.pack
        assert pack.manifest["schema"] == "stewardence.review_pack.v4"
        matches = []
        for industry in ("other", "accounting_bookkeeping"):
            storage = LocalPrivateReportStorage(ram / industry / "private")
            try:
                content = storage.get(key=artifact.object_key)
            except ReportStorageError as error:
                if isinstance(error.__cause__, FileNotFoundError):
                    continue
                raise
            if (
                hashlib.sha256(content).hexdigest() == artifact.sha256
                and len(content) == artifact.size_bytes
            ):
                matches.append(industry)
        assert len(matches) == 1
        manifest.append(
            {
                "artifact_id": str(artifact.id),
                "organization_id": str(org.id),
                "report_id": str(artifact.report_id),
                "snapshot_id": str(artifact.assessment_snapshot_id),
                "request_id": str(completion.request_id),
                "pack_id": str(pack.id),
                "completion_id": str(completion.id),
                "completion_sha256": completion.sha256,
                "manifest_sha256": pack.sha256,
                "object_key": artifact.object_key,
                "sha256": artifact.sha256,
                "size_bytes": artifact.size_bytes,
                "ram_store": matches[0],
            }
        )
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN "
            "('agentledger_owner','agentledger_app','agentledger_worker',"
            "'agentledger_billing_admission') ORDER BY rolname"
        )
        roles = cursor.fetchall()
    assert len(roles) == 4 and all(not row[1] and not row[2] for row in roles)
    private = ram / "manifest.json"
    private.write_text(
        json.dumps(
            {
                "schema": "qualification.local_report_restore_export.v1",
                "objects": manifest,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    private.chmod(0o600)
    ready = {
        "schema": "qualification.local_restore_export_ready.v1",
        "ram_directory": str(ram),
        "objects": len(manifest),
        "total_bytes": sum(item["size_bytes"] for item in manifest),
        "private_manifest_sha256": hashlib.sha256(private.read_bytes()).hexdigest(),
        "four_roles_no_bypass": True,
        "database_issuance": "actual_isolated_synthetic",
        "production_touched": False,
        "restore_qualified": False,
    }
    (evidence / "restore-export-ready.json").write_text(
        json.dumps(ready, indent=2), encoding="utf-8"
    )
    # The parent must export/encrypt while fixture-owned DB rows and RAM stores
    # remain alive, then admit the exact public manifest hash as release proof.
    deadline = time.monotonic() + 180
    release_path = evidence / "restore-export-release.json"
    while not release_path.exists():
        if time.monotonic() >= deadline:
            pytest.fail("Encrypted export was not completed within the bounded hold")
        time.sleep(0.2)
    released = json.loads(release_path.read_text(encoding="utf-8"))
    assert released == {
        "private_manifest_sha256": ready["private_manifest_sha256"],
        "database_ciphertext_verified": True,
        "objects_ciphertext_verified": True,
    }
