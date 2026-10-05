from __future__ import annotations

import uuid

from django.db import connections, transaction
from django.utils import timezone

from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import verify_snapshot
from apps.audit.append import append_audit_event
from apps.audit.events import EVENT_REPORT_GENERATED

from .models import Report


class ReportCreationError(ValueError):
    pass


def format_report_identifier(year: int, sequence: int) -> str:
    if year < 2000 or year > 9999:
        raise ReportCreationError("Report identifier year is unsupported")
    if sequence < 1:
        raise ReportCreationError("Report sequence must be positive")
    return f"AL-{year:04d}-{sequence:06d}"


def create_report(
    *,
    organization_id,
    assessment_snapshot_id,
    created_by_id,
    using: str = "default",
) -> Report:
    try:
        organization_id = uuid.UUID(str(organization_id))
        assessment_snapshot_id = uuid.UUID(str(assessment_snapshot_id))
        created_by_id = uuid.UUID(str(created_by_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise ReportCreationError("Report identities must use UUID values") from error

    with transaction.atomic(using=using):
        return _create_report(
            organization_id=organization_id,
            assessment_snapshot_id=assessment_snapshot_id,
            created_by_id=created_by_id,
            using=using,
        )


def _create_report(
    *,
    organization_id: uuid.UUID,
    assessment_snapshot_id: uuid.UUID,
    created_by_id: uuid.UUID,
    using: str,
) -> Report:
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [str(assessment_snapshot_id)],
        )

    existing = (
        Report.objects.using(using)
        .filter(
            organization_id=organization_id,
            assessment_snapshot_id=assessment_snapshot_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    snapshot = (
        AssessmentSnapshot.objects.using(using)
        .select_related("organization")
        .filter(
            id=assessment_snapshot_id,
            organization_id=organization_id,
        )
        .first()
    )
    if snapshot is None:
        raise ReportCreationError(
            "Assessment snapshot does not belong to this organization"
        )
    if not verify_snapshot(snapshot):
        raise ReportCreationError("Assessment snapshot hash verification failed")

    with connections[using].cursor() as cursor:
        cursor.execute("SELECT nextval('report_identifier_sequence')")
        sequence = cursor.fetchone()[0]

    identifier_year = timezone.now().year
    report = Report.objects.using(using).create(
        organization_id=organization_id,
        assessment_snapshot_id=assessment_snapshot_id,
        sequence=sequence,
        identifier_year=identifier_year,
        report_identifier=format_report_identifier(
            identifier_year,
            sequence,
        ),
        organization_display_name=snapshot.organization.name,
        created_by_id=created_by_id,
    )
    append_audit_event(
        organization_id=organization_id,
        actor_user_id=created_by_id,
        event_type=EVENT_REPORT_GENERATED,
        entity_type="report",
        entity_id=report.id,
        data={
            "assessment_snapshot_id": str(snapshot.id),
            "report_identifier": report.report_identifier,
        },
        using=using,
    )
    return report
