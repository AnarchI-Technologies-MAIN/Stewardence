"""Capture report privacy before association; synthetic bytes are not delivery."""

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from django.urls import reverse

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.artifact_services import persist_pdf_artifact
from apps.reports.models import Report, ReportArtifact
from apps.reports.services import create_report
from apps.reports.storage import LocalPrivateReportStorage
from apps.reviews.models import ArtifactRequest, ReviewLifecycleGate
from apps.reviews.services import freeze_cycle, open_cycle, request_pack_artifact
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def unstaged_capture(capture_context, tmp_path):
    owner, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    with (
        identity_transaction(owner.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        report = create_report(
            organization_id=org.id,
            assessment_snapshot_id=snapshot.id,
            created_by_id=owner.id,
            using="app_runtime",
        )
    storage = LocalPrivateReportStorage(tmp_path)
    # Trusted fixture metadata is deliberately present without admitted delivery.
    artifact = persist_pdf_artifact(
        report=report,
        pdf_bytes=b"%PDF-1.7\nsynthetic privacy fixture\n%%EOF\n",
        storage=storage,
    )
    assert not ArtifactRequest.objects.filter(report_id=report.id).exists()
    return owner, org, report, artifact


def assert_visible(report, artifact, *, actor, org, using, visible):
    with (
        identity_transaction(actor.id, using=using),
        tenant_transaction(org.id, using=using),
        connections[using].cursor() as cursor,
    ):
        cursor.execute("SELECT current_user")
        assert (
            cursor.fetchone()[0]
            == {
                "app_runtime": "agentledger_app",
                "worker_runtime": "agentledger_worker",
            }[using]
        )
        assert Report.objects.using(using).filter(id=report.id).exists() is visible
        assert (
            ReportArtifact.objects.using(using).filter(id=artifact.id).exists()
            is visible
        )


@pytest.mark.parametrize("role", ["viewer", "assessor"])
def test_unassociated_capture_report_is_not_ordinary_tenant_report(
    unstaged_capture, role
):
    owner, org, report, artifact = unstaged_capture
    member = get_user_model().objects.create_user(f"capture-{role}@privacy.example")
    OrganizationMember.objects.create(organization=org, user=member, role=role)
    assert_visible(
        report, artifact, actor=member, org=org, using="app_runtime", visible=False
    )
    assert_visible(
        report, artifact, actor=owner, org=org, using="app_runtime", visible=True
    )


def test_capture_report_foreign_tenant_denied_and_worker_policy_preserved(
    unstaged_capture,
):
    owner, org, report, artifact = unstaged_capture
    foreign = Organization.objects.create(name="Foreign capture organization")
    OrganizationMember.objects.create(organization=foreign, user=owner, role="owner")
    assert_visible(
        report, artifact, actor=owner, org=foreign, using="app_runtime", visible=False
    )
    assert_visible(
        report, artifact, actor=owner, org=org, using="worker_runtime", visible=True
    )
    assert_visible(
        report,
        artifact,
        actor=owner,
        org=foreign,
        using="worker_runtime",
        visible=False,
    )


def owner_client(client, settings, owner, org):
    settings.ALLOWED_HOSTS = ["testserver"]
    client.force_login(owner)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()


def test_unassociated_capture_detail_and_download_fail_before_storage(
    unstaged_capture, client, settings, monkeypatch
):
    owner, org, report, _ = unstaged_capture
    owner_client(client, settings, owner, org)

    def forbidden_storage():
        pytest.fail("Unissued capture delivery reached storage")

    monkeypatch.setattr("apps.reports.views._report_storage", forbidden_storage)
    with actual_app_default():
        detail = client.get(reverse("reports:detail", args=[report.id]))
        download = client.get(reverse("reports:download", args=[report.id]))
    assert detail.status_code == 409
    assert download.status_code == 503
    assert detail["Cache-Control"] == download["Cache-Control"] == "private, no-store"
    assert not ArtifactRequest.objects.filter(report_id=report.id).exists()


def test_admitted_pending_capture_status_never_builds_legacy_roi_context(
    capture_context, client, settings, monkeypatch
):
    owner, org = capture_context
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = True
    ReviewLifecycleGate.objects.update_or_create(id=1, defaults={"enabled": True})
    snapshot = admit(capture_context, preview(capture_context))
    cycle = open_cycle(
        organization_id=org.id,
        actor_id=owner.id,
        input_snapshot_id=snapshot.id,
        using="app_runtime",
    )
    pack = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=org.id,
        actor_id=owner.id,
        expected_revision=1,
        using="app_runtime",
    )
    request = request_pack_artifact(
        pack_id=pack.id, organization_id=org.id, actor_id=owner.id, using="app_runtime"
    )
    owner_client(client, settings, owner, org)

    def forbidden_context(*args, **kwargs):
        pytest.fail("Capture status attempted legacy risk/ROI context")

    monkeypatch.setattr("apps.reports.views.build_report_context", forbidden_context)
    with actual_app_default():
        response = client.get(reverse("reports:detail", args=[request.report_id]))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert "reports/capture_status.html" in [t.name for t in response.templates]
    assert response.context["completion_recorded"] is False
    assert response.context["has_pdf"] is False
    text = response.content.decode()
    assert "No pack completion receipt is recorded" in text
    assert "does not establish verified controls" in text
    assert reverse("reports:download", args=[request.report_id]) not in text
