from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.assessments.models import AssessmentSnapshot
from apps.organizations.models import OrganizationMember
from apps.jobs.models import BackgroundJob

from .artifact_services import read_verified_pdf_artifact
from .context import build_report_context
from .jobs import ensure_report_generation_job
from .models import Report, ReportArtifact
from .services import create_report
from .storage import ReportStorageError, build_private_report_storage

WRITE_ROLES = {
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
    OrganizationMember.Role.ASSESSOR,
}


def _organization_id(request):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise Http404("Choose a firm before opening a report.")
    return organization_id


def _require_membership(request, organization_id):
    return get_object_or_404(
        OrganizationMember,
        organization_id=organization_id,
        user_id=request.user.id,
    )


def _report_storage():
    root = Path(
        getattr(
            settings,
            "REPORTS_LOCAL_STORAGE_ROOT",
            Path(settings.BASE_DIR) / ".private-reports",
        )
    )
    return build_private_report_storage(root)


@login_required
@require_GET
@transaction.atomic
def report_history_view(request):
    organization_id = _organization_id(request)
    _require_membership(request, organization_id)
    reports = Report.objects.filter(organization_id=organization_id).select_related(
        "assessment_snapshot", "artifact"
    ).order_by("-created_at", "-id")
    page = Paginator(reports, 25).get_page(request.GET.get("page"))
    # Materialize while the tenant transaction is active; never expose storage keys.
    rows = [{"id": report.id, "identifier": report.report_identifier,
             "created_at": report.created_at,
             "assessment_version": report.assessment_snapshot.version,
             "has_pdf": hasattr(report, "artifact")}
            for report in page.object_list]
    response = render(request, "reports/history.html", {"rows": rows, "page": page})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
@transaction.atomic
def generate_report_action(request, snapshot_id):
    organization_id = _organization_id(request)
    membership = _require_membership(request, organization_id)

    if membership.role not in WRITE_ROLES:
        raise PermissionDenied("Your role has read-only access to reports.")

    snapshot = get_object_or_404(
        AssessmentSnapshot,
        id=snapshot_id,
        organization_id=organization_id,
    )

    if snapshot.input_payload.get("snapshot_schema_version") != 1:
        response = HttpResponse(
            "This capture requires the separately admitted frozen-pack workflow.",
            status=409,
        )
        response["Cache-Control"] = "private, no-store"
        return response

    report = create_report(
        organization_id=organization_id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=request.user.id,
    )

    ensure_report_generation_job(report=report)

    return redirect("reports:detail", report_id=report.id)


@login_required
def report_detail_view(request, report_id):
    organization_id = _organization_id(request)
    _require_membership(request, organization_id)

    report = get_object_or_404(
        Report.objects.select_related("assessment_snapshot"),
        id=report_id,
        organization_id=organization_id,
    )

    has_pdf = ReportArtifact.objects.filter(report_id=report.id, organization_id=organization_id).exists()
    job = BackgroundJob.objects.filter(organization_id=organization_id,
        job_type=BackgroundJob.Type.REPORT_GENERATION, payload={"report_id":str(report.id)}
    ).order_by("-created_at", "-id").first()
    status = "PDF is not stored yet."
    if job is not None:
        status = {
            BackgroundJob.Status.QUEUED: "PDF preparation is queued. Your browser report remains available.",
            BackgroundJob.Status.RUNNING: "PDF preparation is in progress. Your browser report remains available.",
            BackgroundJob.Status.FAILED: "PDF preparation stopped safely and requires review. Your browser report remains available.",
            BackgroundJob.Status.COMPLETED: "PDF storage needs reconciliation. Your browser report remains available.",
        }[job.status]
        if job.status == BackgroundJob.Status.QUEUED and job.attempts:
            status = "PDF preparation encountered a temporary issue and is queued for another attempt."
    if report.assessment_snapshot.input_payload.get("snapshot_schema_version") == 2:
        from apps.reviews.models import ArtifactRequest

        admitted = ArtifactRequest.objects.filter(
            report_id=report.id, organization_id=organization_id
        ).select_related("job").first()
        if admitted is None:
            response = HttpResponse(
                "Admitted frozen-pack delivery is unavailable.", status=409
            )
            response["Cache-Control"] = "private, no-store"
            return response
        response = render(
            request, "reports/capture_status.html",
            {
                "report_id": report.id,
                "identifier": report.report_identifier,
                "has_pdf": has_pdf,
                "job_state": admitted.job.status,
                "completion_recorded": hasattr(admitted, "completion"),
            },
        )
        response["Cache-Control"] = "private, no-store"
        return response
    response = render(
        request,
        "reports/detail.html",
        {
            "report": build_report_context(report),
            "report_id": report.id,
            "has_pdf": has_pdf,
            "pdf_status": status,
        },
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def report_download_view(request, report_id):
    organization_id = _organization_id(request)
    _require_membership(request, organization_id)

    artifact = get_object_or_404(
        ReportArtifact.objects.select_related("report", "assessment_snapshot"),
        report_id=report_id,
        organization_id=organization_id,
    )

    if artifact.report.organization_id != organization_id:
        raise Http404("Report not found.")

    if artifact.assessment_snapshot_id != artifact.report.assessment_snapshot_id:
        raise Http404("Report not found.")

    try:
        if artifact.assessment_snapshot.input_payload.get("snapshot_schema_version") == 2:
            from .capture_delivery import require_capture_completion

            require_capture_completion(artifact)
        pdf_bytes = read_verified_pdf_artifact(
            artifact=artifact,
            storage=_report_storage(),
        )
    except ReportStorageError:
        response = HttpResponse(
            "Stored report artifact is unavailable.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
        response["Cache-Control"] = "private, no-store"
        return response

    response = HttpResponse(
        pdf_bytes,
        content_type=artifact.content_type,
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{artifact.report.report_identifier}.pdf"'
    )
    response["Cache-Control"] = "private, no-store"
    response["Content-Length"] = str(artifact.size_bytes)
    return response
