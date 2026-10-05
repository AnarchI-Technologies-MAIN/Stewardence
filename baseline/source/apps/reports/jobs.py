from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import connections, transaction

from apps.jobs.models import BackgroundJob
from apps.jobs.queue import ClaimedJob, enqueue_job

from .artifact_services import persist_pdf_artifact
from .context import build_report_context
from .models import Report, ReportArtifact
from .render_client import ReportRenderer
from .storage import PrivateReportStorage


class ReportGenerationJobError(ValueError):
    pass


def ensure_report_generation_job(
    *,
    report: Report,
    using: str = "default",
) -> BackgroundJob | None:
    payload = {"report_id": str(report.id)}

    with transaction.atomic(using=using):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [f"report-generation:{report.id}"],
            )

        if (
            ReportArtifact.objects.using(using)
            .filter(
                organization_id=report.organization_id,
                report_id=report.id,
            )
            .exists()
        ):
            return None

        existing = (
            BackgroundJob.objects.using(using)
            .filter(
                organization_id=report.organization_id,
                job_type=BackgroundJob.Type.REPORT_GENERATION,
                payload=payload,
                status__in=(
                    BackgroundJob.Status.QUEUED,
                    BackgroundJob.Status.RUNNING,
                ),
            )
            .order_by("created_at", "id")
            .first()
        )

        if existing is not None:
            return existing

        return enqueue_job(
            organization_id=report.organization_id,
            job_type=BackgroundJob.Type.REPORT_GENERATION,
            payload=payload,
            using=using,
        )


@dataclass(frozen=True)
class ReportGenerationPrepared:
    job_id: uuid.UUID
    organization_id: uuid.UUID
    report_id: uuid.UUID
    report_context: dict[str, Any]


@dataclass(frozen=True)
class ReportGenerationResult:
    job_id: uuid.UUID
    organization_id: uuid.UUID
    report_id: uuid.UUID
    pdf_bytes: bytes


@dataclass(frozen=True)
class ReportGenerationHandler:
    renderer: ReportRenderer
    storage: PrivateReportStorage
    using: str = "default"
    persistence_isolation: str | None = None

    def prepare(
        self,
        job: ClaimedJob,
    ) -> ReportGenerationPrepared:
        if job.job_type != BackgroundJob.Type.REPORT_GENERATION:
            raise ReportGenerationJobError(
                "Report generation handler received the wrong job type"
            )

        if set(job.payload) != {"report_id"}:
            raise ReportGenerationJobError(
                "Report generation payload must contain only report_id"
            )

        try:
            report_id = uuid.UUID(str(job.payload["report_id"]))
        except (TypeError, ValueError) as error:
            raise ReportGenerationJobError(
                "Report generation report_id must be a UUID"
            ) from error

        try:
            report = (
                Report.objects.using(self.using)
                .select_related("assessment_snapshot")
                .get(
                    id=report_id,
                    organization_id=job.organization_id,
                )
            )
        except Report.DoesNotExist as error:
            raise ReportGenerationJobError(
                "Report generation target does not exist"
            ) from error

        return ReportGenerationPrepared(
            job_id=job.id,
            organization_id=job.organization_id,
            report_id=report.id,
            report_context=build_report_context(report),
        )

    def execute_external(
        self,
        prepared: ReportGenerationPrepared,
        heartbeat,
    ) -> ReportGenerationResult:
        heartbeat()
        pdf_bytes = self.renderer.render(prepared.report_context)
        heartbeat()

        return ReportGenerationResult(
            job_id=prepared.job_id,
            organization_id=prepared.organization_id,
            report_id=prepared.report_id,
            pdf_bytes=pdf_bytes,
        )

    def persist(
        self,
        job: ClaimedJob,
        result: ReportGenerationResult,
    ):
        if result.job_id != job.id:
            raise ReportGenerationJobError(
                "Report generation job identity changed during execution"
            )

        if result.organization_id != job.organization_id:
            raise ReportGenerationJobError(
                "Report generation tenant identity changed during execution"
            )

        try:
            report_id = uuid.UUID(str(job.payload["report_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ReportGenerationJobError(
                "Report generation job payload changed during execution"
            ) from error

        if result.report_id != report_id:
            raise ReportGenerationJobError(
                "Report generation report identity changed during execution"
            )

        try:
            report = Report.objects.using(self.using).get(
                id=result.report_id,
                organization_id=job.organization_id,
            )
        except Report.DoesNotExist as error:
            raise ReportGenerationJobError(
                "Report generation target disappeared before persistence"
            ) from error

        return persist_pdf_artifact(
            report=report,
            pdf_bytes=result.pdf_bytes,
            storage=self.storage,
            using=self.using,
        )
