"""Actual app-role review-pack read isolation; synthetic local PDFs only."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from django.urls import reverse

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.snapshots import create_assessment_snapshot
from apps.jobs.worker import JobExecution, execute_claimed_job
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.artifact_services import persist_pdf_artifact
from apps.reports.models import Report, ReportArtifact
from apps.reports.services import create_report
from apps.reviews.models import ArtifactRequest
from tests.conftest import _roi_inputs
from tests.test_review_pack_lifecycle import (
    claimed,
    handler,
    request,
)
from tests.test_review_pack_lifecycle import (
    enabled as enabled,
)
from tests.test_review_pack_lifecycle import (
    pack_context as pack_context,
)
from tests.test_standard_checkout_route_durability import actual_app_default

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def stored_reports(pack_context, enabled, tmp_path, report_context):
    staged = request(pack_context)
    job = claimed(pack_context)
    wrapped = handler(tmp_path)
    execute_claimed_job(
        JobExecution(job=job, worker_id="review-qualification"),
        wrapped,
        using="worker_runtime",
    )
    owner, org, snapshot, _ = pack_context
    ordinary_snapshot = create_assessment_snapshot(
        organization_id=org.id,
        created_by_id=owner.id,
        assessed_item_id=report_context[3].id,
        roi_inputs=_roi_inputs(),
        captured_at=snapshot.captured_at + timedelta(seconds=1),
        previous_snapshot=snapshot,
    )
    ordinary = create_report(
        organization_id=org.id,
        assessment_snapshot_id=ordinary_snapshot.id,
        created_by_id=owner.id,
    )
    assert ordinary.id != staged.report_id
    persist_pdf_artifact(
        report=ordinary,
        pdf_bytes=b"%PDF-1.7\nordinary\n%%EOF\n",
        storage=wrapped.delegate.storage,
    )
    return owner, org, staged, ordinary, wrapped.delegate.storage


def member(org, role):
    user = get_user_model().objects.create_user(f"{role}@read-authority.example")
    OrganizationMember.objects.create(organization=org, user=user, role=role)
    return user


@pytest.mark.parametrize("role", ["viewer", "assessor"])
def test_hidden_request_cannot_turn_review_pack_into_ordinary_report(
    stored_reports, role
):
    _, org, staged, ordinary, _ = stored_reports
    user = member(org, role)
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        assert (
            not ArtifactRequest.objects.using("app_runtime")
            .filter(report_id=staged.report_id)
            .exists()
        )
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute("SELECT current_user")
            assert cursor.fetchone()[0] == "agentledger_app"
            cursor.execute(
                "SELECT app_private.report_read_allowed(%s,%s)",
                [staged.report_id, org.id],
            )
            assert cursor.fetchone()[0] is False
            cursor.execute("SELECT id FROM reports WHERE id=%s", [staged.report_id])
            assert cursor.fetchall() == []
            cursor.execute(
                "SELECT id FROM report_artifacts WHERE report_id=%s", [staged.report_id]
            )
            assert cursor.fetchall() == []
        assert Report.objects.using("app_runtime").filter(pk=ordinary.id).exists()
        assert (
            ReportArtifact.objects.using("app_runtime")
            .filter(report_id=ordinary.id)
            .exists()
        )


@pytest.mark.parametrize("role", ["viewer", "assessor"])
def test_routed_nonowner_reads_hide_pack_before_storage(
    stored_reports, role, client, settings, monkeypatch
):
    _, org, staged, ordinary, storage = stored_reports
    user = member(org, role)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    settings.ALLOWED_HOSTS = ["testserver"]
    # Organization subscription is one-to-one and belongs to the owner.
    # Isolate report read authorization: billing redirect is a separate guard;
    # retain authentication and actual tenant/identity middleware and routes.
    settings.MIDDLEWARE = [
        entry
        for entry in settings.MIDDLEWARE
        if not entry.endswith("BillingEntitlementMiddleware")
    ]

    def forbidden_storage():
        pytest.fail("Denied review-pack download reached object storage")

    monkeypatch.setattr("apps.reports.views._report_storage", forbidden_storage)
    with actual_app_default():
        history = client.get(reverse("reports:history"))
        assert history.status_code == 200
        assert staged.report_id not in [row["id"] for row in history.context["rows"]]
        assert ordinary.id in [row["id"] for row in history.context["rows"]]
        for route in ["detail", "download"]:
            assert (
                client.get(
                    reverse(f"reports:{route}", kwargs={"report_id": staged.report_id})
                ).status_code
                == 404
            )
        assert (
            client.get(
                reverse("reports:detail", kwargs={"report_id": ordinary.id})
            ).status_code
            == 200
        )
        monkeypatch.setattr("apps.reports.views._report_storage", lambda: storage)
        ordinary_pdf = client.get(
            reverse("reports:download", kwargs={"report_id": ordinary.id})
        )
        assert ordinary_pdf.status_code == 200 and ordinary_pdf.content.startswith(
            b"%PDF-"
        )


def test_owner_reads_pack_and_ordinary_report_with_actual_app_role(
    stored_reports, client, settings, monkeypatch
):
    owner, org, staged, ordinary, storage = stored_reports
    client.force_login(owner)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    settings.ALLOWED_HOSTS = ["testserver"]
    monkeypatch.setattr("apps.reports.views._report_storage", lambda: storage)
    with (
        identity_transaction(owner.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        assert Report.objects.using("app_runtime").filter(pk=staged.report_id).exists()
        assert (
            ReportArtifact.objects.using("app_runtime")
            .filter(report_id=staged.report_id)
            .exists()
        )
    with actual_app_default():
        history = client.get(reverse("reports:history"))
        assert history.status_code == 200
        assert {staged.report_id, ordinary.id}.issubset(
            {row["id"] for row in history.context["rows"]}
        )
        assert (
            client.get(
                reverse("reports:detail", kwargs={"report_id": staged.report_id})
            ).status_code
            == 200
        )
        response = client.get(
            reverse("reports:download", kwargs={"report_id": staged.report_id})
        )
        assert response.status_code == 200 and response.content.startswith(b"%PDF-")


def test_owner_identity_cannot_read_original_pack_in_other_tenant_context(
    stored_reports,
):
    owner, _, staged, _, _ = stored_reports
    other = Organization.objects.create(name="Other read-authority tenant")
    OrganizationMember.objects.create(organization=other, user=owner, role="owner")
    with (
        identity_transaction(owner.id, using="app_runtime"),
        tenant_transaction(other.id, using="app_runtime"),
    ):
        assert (
            not Report.objects.using("app_runtime").filter(pk=staged.report_id).exists()
        )
        assert (
            not ReportArtifact.objects.using("app_runtime")
            .filter(report_id=staged.report_id)
            .exists()
        )
