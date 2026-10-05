"""Privileged synthetic archive fixtures test read gates, NOT historical issuance.

Past paid coverage is admitted through the isolated billing role. Archived
snapshot/request/completion rows are explicit owner-role fixtures: this does
not claim a review was admitted or a worker ran while coverage was expired.
No immutable coverage, clock, or receipt is changed to manufacture expiry.
"""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import Client
from django.urls import reverse

from agentledger.tenancy.context import identity_transaction
from apps.assessments.capture_contract import build_capture_payloads
from apps.assessments.models import AssessmentSnapshot
from apps.billing.entitlements import (
    issue_paid_coverage,
    paid_subscription_access,
    paid_subscription_export_access,
)
from apps.jobs.models import BackgroundJob
from apps.organizations.models import OrganizationMember
from apps.reports.artifact_services import persist_pdf_artifact
from apps.reports.services import create_report
from apps.reports.storage import LocalPrivateReportStorage
from apps.reviews.capture_context import digest
from apps.reviews.models import (
    ArtifactRequest,
    PackCompletion,
    PackIdentity,
    ReviewCycle,
)
from tests.test_capture_contract import args
from tests.test_paid_coverage_authority import admitted as admitted
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["admitted"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def synthetic_archive(admitted, age_days, path):
    # Default is the isolated bootstrap login, not the actual owner role.
    # This explicit fixture-only role change ends with its transaction.
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cursor:
            cursor.execute("SET LOCAL ROLE agentledger_owner")
        return _synthetic_archive_owner(admitted, age_days, path)


def _synthetic_archive_owner(admitted, age_days, path):
    user, org, subscription, evidence = admitted
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT current_user,clock_timestamp()")
        role, now = cursor.fetchone()
    assert role == "agentledger_owner"
    end = int((now - timedelta(days=age_days)).timestamp())
    issue_paid_coverage(
        {
            **evidence,
            "service_start": end - 86400,
            "service_end": end,
            "paid_at": end - 86300,
        }
    )
    captured_at = now - timedelta(days=age_days + 1)
    pins = args("other")
    pins.update(organization_id=org.id, created_by_id=user.id, captured_at=captured_at)
    pins["inventory_records"][0]["declaration_as_of"] = captured_at.date().isoformat()
    envelope = build_capture_payloads(**pins)
    snapshot_id = pins["assessment_id"]
    snapshot = AssessmentSnapshot.objects.create(
        id=snapshot_id,
        assessment_id=snapshot_id,
        organization=org,
        created_by=user,
        version=1,
        captured_at=captured_at,
        **envelope,
    )
    report = create_report(
        organization_id=org.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    storage = LocalPrivateReportStorage(path)
    pdf = b"%PDF-1.7\nexplicit synthetic archived fixture\n%%EOF\n"
    artifact = persist_pdf_artifact(report=report, pdf_bytes=pdf, storage=storage)
    common = dict(organization=org, created_by=user, created_at=captured_at)
    cycle = ReviewCycle.objects.create(input_snapshot=snapshot, **common)
    # These rows intentionally do not simulate the admission or worker protocol.
    manifest = {
        "schema": "stewardence.review_pack.v3",
        "cycle_id": str(cycle.id),
        "organization_id": str(org.id),
        "baseline_pack_id": None,
        "snapshot": {
            "snapshot_id": str(snapshot.id),
            "assessment_id": str(snapshot.assessment_id),
            "assessment_version": 1,
            "input_sha256": snapshot.input_sha256,
            "result_sha256": snapshot.result_sha256,
            "captured_at": envelope["input_payload"]["captured_at"],
            "snapshot_schema": 2,
            "workflow_profile_id": str(pins["workflow_profile_id"]),
            "workflow_profile": pins["workflow_profile"],
            "workflow_settings_sha256": envelope["input_payload"]["workflow_profile"][
                "settings_sha256"
            ],
            "rules_sha256": digest(envelope["input_payload"]["rulesets"]),
            "configuration_sha256": digest(
                envelope["input_payload"]["risk_configuration"]
            ),
            "engine_versions": envelope["input_payload"]["engine_versions"],
            "capture_contract": "core.capture.declarations.v1",
        },
        "capture": {
            "receipt_id": str(snapshot.id),
            "request_sha256": digest({"fixture": "privileged_archived_read_only"}),
            "contract": "core.capture.declarations.v1",
            "exposure_contract": "core.exposure.declarations.v1",
        },
        "selected_decisions": [],
        "selection_scope": "empty_capture_kernel",
        "artifact_state": "not_created",
        "baseline_promotion": "blocked",
    }
    pack = PackIdentity.objects.create(
        cycle=cycle,
        admitted_revision=1,
        manifest=manifest,
        sha256=digest(manifest),
        **common,
    )
    payload = {"report_id": str(report.id)}
    job = BackgroundJob.objects.create(
        organization=org,
        job_type="report_generation",
        payload=payload,
        input_sha256=digest(payload),
        status="queued",
        attempts=0,
        available_at=now,
    )
    # Privileged synthetic queue projection, not a paid worker admission.
    # Obey INSERT and transition guards; the normal worker must not claim an
    # expired-paid report. No trigger is disabled and no coverage is changed.
    fixture_token = uuid4()
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "UPDATE background_jobs SET status='running',attempts=1,"
            "locked_by='privileged-archive-fixture',claim_token=%s,"
            "locked_at=clock_timestamp(),"
            "lock_expires_at=clock_timestamp()+interval '10 minutes' "
            "WHERE id=%s AND organization_id=%s AND status='queued' AND attempts=0",
            [fixture_token, job.id, org.id],
        )
        assert cursor.rowcount == 1
        cursor.execute(
            "UPDATE background_jobs SET status='completed',"
            "completed_at=clock_timestamp(),"
            "locked_by=NULL,claim_token=NULL,locked_at=NULL,lock_expires_at=NULL "
            "WHERE id=%s AND organization_id=%s AND status='running' AND attempts=1 "
            "AND claim_token=%s AND lock_expires_at>clock_timestamp()",
            [job.id, org.id, fixture_token],
        )
        assert cursor.rowcount == 1
    job.refresh_from_db()
    assert job.status == "completed" and job.attempts == 1
    request = ArtifactRequest.objects.create(
        pack=pack,
        report=report,
        job=job,
        manifest_sha256=pack.sha256,
        promote_baseline=False,
        observed_head_revision=0,
        **common,
    )
    completion = {
        "schema": "stewardence.review_pack_completion.v2",
        "request_id": str(request.id),
        "pack_id": str(pack.id),
        "manifest_sha256": pack.sha256,
        "artifact_id": str(artifact.id),
        "artifact_sha256": artifact.sha256,
        "artifact_bytes": artifact.size_bytes,
        "verification": "trusted_handler_storage_readback",
        "baseline_outcome": "not_requested",
    }
    # The serialized verification label is synthetic fixture content, not a
    # claim of executed historical readback; current worker tests prove that.
    PackCompletion.objects.create(
        request=request,
        artifact=artifact,
        payload=completion,
        sha256=digest(completion),
        **common,
    )
    return user, org, subscription, report, storage, pdf


@pytest.mark.parametrize("age_days,allowed", [(30, True), (91, False)])
def test_genuine_past_paid_interval_retained_owner_read_and_viewer_privacy(
    admitted, age_days, allowed, tmp_path, client, settings, monkeypatch
):
    user, org, subscription, report, storage, pdf = synthetic_archive(
        admitted, age_days, tmp_path
    )
    with identity_transaction(user.id, using="app_runtime"):
        assert not paid_subscription_access(subscription.id, using="app_runtime")
        assert (
            paid_subscription_export_access(subscription.id, using="app_runtime")
            is allowed
        )
    settings.ALLOWED_HOSTS = ["testserver"]
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()

    def forbidden_legacy(report):
        pytest.fail("Archive capture read reached legacy risk/ROI builder")

    monkeypatch.setattr("apps.reports.views.build_report_context", forbidden_legacy)
    monkeypatch.setattr("apps.reports.views._report_storage", lambda: storage)
    with actual_app_default():
        for route in ("detail", "download"):
            response = client.get(
                reverse(f"reports:{route}", kwargs={"report_id": report.id})
            )
            if allowed:
                assert response.status_code == 200
                if route == "detail":
                    assert "reports/capture_status.html" in [
                        t.name for t in response.templates
                    ]
                if route == "download":
                    assert response.content == pdf
            if not allowed:
                assert response.status_code == 302
                assert response.url == reverse("billing:portfolio")
    viewer = get_user_model().objects.create_user(
        f"archive-viewer-{age_days}@example.invalid"
    )
    OrganizationMember.objects.create(organization=org, user=viewer, role="viewer")
    client.force_login(viewer)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    settings.MIDDLEWARE = [
        entry
        for entry in settings.MIDDLEWARE
        if not entry.endswith("BillingEntitlementMiddleware")
    ]
    # The original Client cached its stack during owner reads.
    viewer_client = Client()
    viewer_client.force_login(viewer)
    session = viewer_client.session
    session["active_organization_id"] = str(org.id)
    session.save()

    def forbidden_storage():
        pytest.fail("Denied archived capture read reached storage")

    monkeypatch.setattr("apps.reports.views._report_storage", forbidden_storage)
    with actual_app_default():
        for route in ("detail", "download"):
            assert viewer_client.get(
                reverse(f"reports:{route}", kwargs={"report_id": report.id})
            ).status_code in (403, 404)
