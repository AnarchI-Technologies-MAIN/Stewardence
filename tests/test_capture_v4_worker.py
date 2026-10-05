"""Actual roles and local private storage; no live provider or deployment claims."""

import os
from io import BytesIO
from urllib.parse import urlsplit
from uuid import UUID

import pytest
from django.contrib.auth import get_user_model
from django.db import connections, transaction
from django.test import Client
from django.urls import reverse
from pypdf import PdfReader

from agentledger.tenancy.context import tenant_transaction
from apps.jobs.core_decisions_v2 import record_capture_decision
from apps.jobs.core_models import DecisionDeskGate, DecisionEvent
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import claim_next_job
from apps.jobs.worker import JobExecution, execute_claimed_job
from apps.organizations.models import OrganizationMember
from apps.reports.jobs import ReportGenerationHandler
from apps.reports.render_client import HTTPReportRenderer
from apps.reports.storage import LocalPrivateReportStorage
from apps.reviews.jobs import ReviewReportGenerationHandler
from apps.reviews.models import (
    BaselineHead,
    CoreProposalAdmissionGate,
    PackCompletion,
    ReviewCycle,
)
from apps.reviews.proposal_admission import issue_capture_proposals
from apps.reviews.services import freeze_cycle, open_cycle, request_pack_artifact
from renderer.render import render_pdf
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_capture_admission import explicit_context as explicit_context
from tests.test_review_pack_lifecycle import enabled as enabled
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["capture_context", "explicit_context", "enabled"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


class ActualRenderer:
    def __init__(self, path):
        self.path = path
        self.context = None
        self.pdf = None

    def render(self, context):
        self.context = context
        qualification_url = os.environ.get("STEWARDENCE_HTTP_RENDER_QUALIFICATION_URL")
        if qualification_url:
            parsed = urlsplit(qualification_url)
            assert parsed.scheme == "http"
            assert parsed.hostname in {"release-renderer", "qualification-renderer"}
            assert parsed.port == 8080 and parsed.path in {"", "/"}
            assert parsed.username is None and parsed.password is None
            assert not parsed.query and not parsed.fragment
            self.pdf = HTTPReportRenderer(base_url=qualification_url).render(context)
        if not qualification_url:
            self.pdf = render_pdf(context, output_directory=self.path)
        return self.pdf


@pytest.mark.parametrize("industry", ["other", "accounting_bookkeeping"])
def test_capture_v4_actual_worker_chromium_private_owner_delivery(
    capture_context, enabled, tmp_path, industry, client, settings, monkeypatch
):
    user, org = capture_context
    org.industry = industry
    org.save(update_fields=["industry"])
    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    settings.DECISION_DESK_ENABLED = True
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    if os.environ.get("STEWARDENCE_HTTP_RENDER_QUALIFICATION_URL"):

        def forbidden_direct_renderer(*args, **kwargs):
            pytest.fail("HTTP qualification bypassed the separate renderer service")

        monkeypatch.setattr(
            "tests.test_capture_v4_worker.render_pdf", forbidden_direct_renderer
        )
        monkeypatch.setattr("renderer.render.render_pdf", forbidden_direct_renderer)
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    DecisionDeskGate.objects.update_or_create(id=1, defaults={"enabled": True})
    snapshot = admit(capture_context, preview(capture_context))
    revision = issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=snapshot.id,
        using="app_runtime",
    )
    prior = None
    event_ids = []
    for kind, state in (("disposition", "act"), ("execution", "completion_recorded")):
        prior = record_capture_decision(
            organization_id=org.id,
            actor_id=user.id,
            revision_id=revision.id,
            proposal_id=UUID(revision.cards[0]["proposal_id"]),
            proposal_sha256=revision.cards[0]["sha256"],
            card_index=0,
            event_kind=kind,
            state=state,
            responsible_label="Named responsible owner",
            expected_previous_event=prior,
            notes="Owner statement is not verified resolution.",
            links=["https://example.invalid/reference"],
            using="app_runtime",
        )
        event_ids.append(prior)
    cycle = open_cycle(
        organization_id=org.id,
        actor_id=user.id,
        input_snapshot_id=snapshot.id,
        using="app_runtime",
    )
    pack = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=org.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )
    assert pack.manifest["schema"] == "stewardence.review_pack.v4"
    assert len(pack.manifest["selected_proposals"]) == len(revision.cards)
    assert {item["event_id"] for item in pack.manifest["selected_decisions"]} == {
        str(value) for value in event_ids
    }
    assert all(
        DecisionEvent.objects.get(id=value).payload["resolution_verified"] is False
        for value in event_ids
    )
    staged = request_pack_artifact(
        pack_id=pack.id,
        organization_id=org.id,
        actor_id=user.id,
        promote_baseline=False,
        using="app_runtime",
    )
    BackgroundJob.objects.filter(id=staged.job_id).update(priority=-100)
    with transaction.atomic(using="worker_runtime"):
        job = claim_next_job("capture-review-qualification", using="worker_runtime")
    assert job is not None and job.id == staged.job_id
    with (
        tenant_transaction(org.id, using="worker_runtime"),
        connections["worker_runtime"].cursor() as cursor,
    ):
        cursor.execute("SELECT current_user,current_setting('transaction_isolation')")
        assert cursor.fetchone() == ("agentledger_worker", "read committed")
    renderer = ActualRenderer(tmp_path / "render")
    delegate = ReportGenerationHandler(
        renderer=renderer,
        storage=LocalPrivateReportStorage(tmp_path / "private"),
        using="worker_runtime",
    )
    handler = ReviewReportGenerationHandler(
        delegate, worker_id="capture-review-qualification"
    )
    execute_claimed_job(
        JobExecution(job=job, worker_id="capture-review-qualification"),
        handler,
        using="worker_runtime",
    )
    assert renderer.context["context_version"] == "AL-REVIEW-PACK-CONTEXT-3"
    assert renderer.context["projection"]["manifest_sha256"] == pack.sha256
    text = " ".join(
        " ".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(renderer.pdf)).pages
        ).split()
    )
    assert "Risk: not assessed" in text and "Benefit model: not supplied" in text
    assert "Generic exposure review" in text and "Low" not in text
    assert "disposition: act" in text and "execution: completion_recorded" in text
    assert "Original outcome: UNKNOWN" in text
    completion = PackCompletion.objects.get(request=staged)
    assert completion.payload["verification"] == "trusted_handler_storage_readback"
    assert completion.payload["baseline_outcome"] == "not_requested"
    assert completion.payload["manifest_sha256"] == pack.sha256
    assert completion.artifact.sha256 == completion.payload["artifact_sha256"]
    assert not BaselineHead.objects.filter(organization=org).exists()
    assert ReviewCycle.objects.get(id=cycle.id).state == "COMPLETED"
    assert BackgroundJob.objects.get(id=job.id).status == "completed"
    settings.ALLOWED_HOSTS = ["testserver"]
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()

    def forbidden_legacy_context(report):
        pytest.fail("Capture delivery invoked the legacy risk/ROI builder")

    monkeypatch.setattr(
        "apps.reports.views.build_report_context", forbidden_legacy_context
    )
    monkeypatch.setattr("apps.reports.views._report_storage", lambda: delegate.storage)
    with actual_app_default():
        pack_page = client.get(
            reverse("reviews:pack-detail", kwargs={"pack_id": pack.id})
        )
        assert pack_page.status_code == 200
        body = pack_page.content.decode()
        assert "All frozen proposals" in body
        assert "disposition: act" in body and "execution: completion_recorded" in body
        assert "Original captured outcome: UNKNOWN" in body
        assert "Verified resolution is not established" in body
        assert all(
            entry["proposal"]["proposal_id"] in body
            for entry in pack.manifest["selected_proposals"]
        )
        assert all(
            entry["proposal"]["proposal_text"] in body
            for entry in pack.manifest["selected_proposals"]
        )
        assert str(event_ids[0]) in body and str(event_ids[1]) in body
        detail = client.get(
            reverse("reports:detail", kwargs={"report_id": staged.report_id})
        )
        assert detail.status_code == 200
        assert "reports/capture_status.html" in [t.name for t in detail.templates]
        assert detail.context["completion_recorded"] is True
        assert detail.context["has_pdf"] is True
        assert "no-store" in detail["Cache-Control"]
        download = client.get(
            reverse("reports:download", kwargs={"report_id": staged.report_id})
        )
        assert download.status_code == 200 and download.content == renderer.pdf
        assert "no-store" in download["Cache-Control"]

    viewer = get_user_model().objects.create_user(
        f"capture-viewer-{industry}@example.invalid"
    )
    OrganizationMember.objects.create(organization=org, user=viewer, role="viewer")
    client.force_login(viewer)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    # Isolate tenant/report privacy from the owner's one-to-one subscription.
    # Authentication, tenant and identity middleware remain active.
    settings.MIDDLEWARE = [
        entry
        for entry in settings.MIDDLEWARE
        if not entry.endswith("BillingEntitlementMiddleware")
    ]
    # A previously used Client retains the owner's original middleware stack.
    # Rebuild it to prove report privacy, not merely a billing redirect.
    viewer_client = Client()
    viewer_client.force_login(viewer)
    session = viewer_client.session
    session["active_organization_id"] = str(org.id)
    session.save()

    def forbidden_storage():
        pytest.fail("Denied capture-pack request reached private storage")

    monkeypatch.setattr("apps.reports.views._report_storage", forbidden_storage)
    with actual_app_default():
        for route in ("detail", "download"):
            denied = viewer_client.get(
                reverse(f"reports:{route}", kwargs={"report_id": staged.report_id})
            )
            assert denied.status_code in (403, 404)
