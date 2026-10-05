"""First paid owner journey; synthetic payment evidence, no provider or worker."""

from uuid import UUID

import pytest
from django.test import Client
from django.urls import resolve, reverse

from apps.assessments.models import (
    AssessmentSnapshot,
    CaptureAdmissionGate,
    SnapshotCaptureReceipt,
)
from apps.billing.entitlements import issue_paid_coverage
from apps.inventory.models import ExplicitDeclarationGate, InventoryItem
from apps.jobs.models import BackgroundJob
from apps.organizations.models import WorkflowProfile
from apps.reports.models import Report, ReportArtifact
from apps.reviews.models import (
    ArtifactRequest,
    PackCompletion,
    PackIdentity,
    ReviewCycle,
    ReviewLifecycleGate,
)
from tests.test_paid_coverage_authority import admitted as admitted
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["admitted"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def test_first_owner_records_reviews_freezes_and_requests_exact_capture(
    admitted, settings, monkeypatch
):
    owner, org, _, payment_evidence = admitted
    # This narrow issuer fixture is not a checkout or live payment qualification.
    issue_paid_coverage(payment_evidence)
    settings.ALLOWED_HOSTS = ["testserver"]
    settings.CORE_EXPLICIT_INVENTORY_ENABLED = True
    settings.DELIBERATE_CAPTURE_ENABLED = True
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = True
    for gate in (ExplicitDeclarationGate, CaptureAdmissionGate, ReviewLifecycleGate):
        gate.objects.update_or_create(id=1, defaults={"enabled": True})
    for model in (
        InventoryItem,
        AssessmentSnapshot,
        SnapshotCaptureReceipt,
        WorkflowProfile,
        Report,
        ReportArtifact,
        ReviewCycle,
        PackIdentity,
        ArtifactRequest,
        PackCompletion,
        BackgroundJob,
    ):
        assert model.objects.count() == 0, model.__name__

    def no_benefit(*args, **kwargs):
        pytest.fail("First deliberate capture invoked legacy ROI")

    monkeypatch.setattr("apps.roi.engine_v2.calculate_roi", no_benefit)
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()

    def post(route, values):
        return client.post(
            route,
            {
                **values,
                "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            },
        )

    with actual_app_default():
        profile_route = reverse("organizations:workflow-profile")
        assert client.get(profile_route).status_code == 200
        response = post(profile_route, {"profile": "business.v1", "name": "Main firm"})
        assert response.status_code == 302, response.content.decode()
        add_route = reverse("inventory:create")
        assert client.get(add_route).status_code == 200
        response = post(
            add_route,
            {
                "display_name": "First workflow helper",
                "declaration_as_of": "2026-01-01",
                "business_purpose": "Prepare draft client summaries for owner review",
            },
        )
        assert response.status_code == 302, response.content.decode()
        detail = client.get(response["Location"])
        assert detail.status_code == 200
        assert b"Unknown" in detail.content

        capture_route = reverse("reviews:capture")
        review = client.get(capture_route)
        assert review.status_code == 200, review.content.decode()
        assert review["Cache-Control"] == "private, no-store"
        token = review.context["form"].initial["preview_token"]
        response = post(capture_route, {"preview_token": token, "confirm": "on"})
        assert response.status_code == 302, response.content.decode()
        snapshot_id = resolve(response["Location"]).kwargs["snapshot_id"]
        snapshot_page = client.get(response["Location"])
        assert snapshot_page.status_code == 200, snapshot_page.content.decode()
        freeze_route = reverse("reviews:freeze", args=[snapshot_id])
        assert freeze_route in snapshot_page.content.decode()
        cycle_id = snapshot_page.context["freeze_form"].initial["cycle_id"]
        response = post(freeze_route, {"cycle_id": str(cycle_id)})
        assert response.status_code == 302, response.content.decode()
        pack_id = resolve(response["Location"]).kwargs["pack_id"]
        pack_page = client.get(response["Location"])
        assert pack_page.status_code == 200, pack_page.content.decode()
        request_route = reverse("reviews:request-artifact", args=[pack_id])
        assert request_route in pack_page.content.decode()
        response = post(request_route, {})
        assert response.status_code == 302, response.content.decode()
        pending = client.get(response["Location"])
        assert pending.status_code == 200, pending.content.decode()
        assert b"Queue admission is not delivery" in pending.content

    assert WorkflowProfile.objects.get(organization=org).created_by_id == owner.id
    assert InventoryItem.objects.filter(organization=org).count() == 1
    snapshot = AssessmentSnapshot.objects.get(id=snapshot_id)
    assert snapshot.input_payload["snapshot_schema_version"] == 2
    assert SnapshotCaptureReceipt.objects.filter(snapshot=snapshot).count() == 1
    assert (
        ReviewCycle.objects.get(id=UUID(str(cycle_id))).input_snapshot_id == snapshot.id
    )
    assert PackIdentity.objects.get(id=pack_id).manifest["snapshot"][
        "snapshot_id"
    ] == str(snapshot.id)
    request = ArtifactRequest.objects.get(pack_id=pack_id)
    assert request.report.assessment_snapshot_id == snapshot.id
    assert request.job.status == BackgroundJob.Status.QUEUED
    assert request.job.attempts == 0
    assert Report.objects.count() == 1
    # The manual declaration and report identity each append an audit event,
    # which admits an audit-seal job in addition to the explicit PDF request.
    jobs = list(BackgroundJob.objects.order_by("id"))
    assert len(jobs) == 3
    assert sorted(job.job_type for job in jobs) == sorted(
        [BackgroundJob.Type.AUDIT_BATCH_SEAL] * 2
        + [BackgroundJob.Type.REPORT_GENERATION]
    )
    assert all(job.organization_id == org.id for job in jobs)
    assert all(job.status == BackgroundJob.Status.QUEUED for job in jobs)
    assert all(job.attempts == 0 and job.locked_by is None for job in jobs)
    assert not PackCompletion.objects.exists()
    assert not ReportArtifact.objects.exists()
