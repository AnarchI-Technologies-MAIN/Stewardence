from __future__ import annotations

from django.db import connections, transaction

from .models import Report, ReportArtifact
from .storage import (
    PDF_CONTENT_TYPE,
    PrivateReportStorage,
    ReportStorageError,
    build_pdf_object_key,
    sha256_hex,
    validate_pdf_bytes,
)


class ReportArtifactError(ValueError):
    pass


def persist_pdf_artifact(
    *,
    report: Report,
    pdf_bytes: bytes,
    storage: PrivateReportStorage,
    using: str = "default",
) -> ReportArtifact:
    validate_pdf_bytes(pdf_bytes)

    key = build_pdf_object_key(
        organization_id=report.organization_id,
        assessment_snapshot_id=report.assessment_snapshot_id,
        report_id=report.id,
    )
    digest = sha256_hex(pdf_bytes)

    uploaded = False

    try:
        with transaction.atomic(using=using):
            # Serialize artifact materialization for exactly one report.
            with connections[using].cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    [f"report-artifact:{report.id}"],
                )

            existing = (
                ReportArtifact.objects.using(using)
                .filter(
                    organization_id=report.organization_id,
                    report_id=report.id,
                )
                .first()
            )

            if existing is not None:
                if (
                    existing.object_key == key
                    and existing.content_type == PDF_CONTENT_TYPE
                    and existing.sha256 == digest
                    and existing.size_bytes == len(pdf_bytes)
                ):
                    return existing

                raise ReportArtifactError(
                    "Report already has different persisted artifact metadata"
                )

            storage.put(
                key=key,
                content=pdf_bytes,
                content_type=PDF_CONTENT_TYPE,
            )
            uploaded = True

            return ReportArtifact.objects.using(using).create(
                organization_id=report.organization_id,
                report_id=report.id,
                assessment_snapshot_id=report.assessment_snapshot_id,
                object_key=key,
                content_type=PDF_CONTENT_TYPE,
                sha256=digest,
                size_bytes=len(pdf_bytes),
            )

    except Exception:
        if uploaded:
            storage.delete(key=key)
        raise


def read_verified_pdf_artifact(
    *,
    artifact: ReportArtifact,
    storage: PrivateReportStorage,
) -> bytes:
    try:
        content = storage.get(key=artifact.object_key)
    except ReportStorageError:
        raise

    validate_pdf_bytes(content)

    if len(content) != artifact.size_bytes:
        raise ReportStorageError("Stored report size verification failed")

    if sha256_hex(content) != artifact.sha256:
        raise ReportStorageError("Stored report hash verification failed")

    return content
