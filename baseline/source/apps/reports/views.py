from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.assessments.models import AssessmentSnapshot
from apps.organizations.models import OrganizationMember

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

    return render(
        request,
        "reports/detail.html",
        {
            "report": build_report_context(report),
            "report_id": report.id,
        },
    )


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
        pdf_bytes = read_verified_pdf_artifact(
            artifact=artifact,
            storage=_report_storage(),
        )
    except ReportStorageError:
        return HttpResponse(
            "Stored report artifact is unavailable.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )

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
