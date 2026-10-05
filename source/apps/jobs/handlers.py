from __future__ import annotations

from collections.abc import Callable

from apps.audit.jobs import AuditBatchSealHandler
from apps.jobs.models import BackgroundJob
from apps.jobs.worker import JobHandler
from apps.reports.jobs import ReportGenerationHandler
from apps.reports.render_client import ReportRenderer, build_report_renderer
from apps.reports.storage import (
    PrivateReportStorage,
    build_private_report_storage,
)
from apps.reviews.jobs import ReviewReportGenerationHandler


class UnsupportedJobHandler(ValueError):
    pass


def build_job_handler_resolver(
    *,
    using: str = "default",
    worker_id: str | None = None,
    report_renderer: ReportRenderer | None = None,
    report_storage: PrivateReportStorage | None = None,
) -> Callable[[str], JobHandler]:
    audit_batch_seal_handler = AuditBatchSealHandler(
        using=using,
    )

    def resolve(job_type: str) -> JobHandler:
        if job_type == BackgroundJob.Type.AUDIT_BATCH_SEAL:
            return audit_batch_seal_handler

        if job_type == BackgroundJob.Type.REPORT_GENERATION:
            renderer = report_renderer

            if renderer is None:
                renderer = build_report_renderer()

            storage = report_storage

            if storage is None:
                storage = build_private_report_storage()

            return ReviewReportGenerationHandler(
                worker_id=worker_id,
                delegate=ReportGenerationHandler(
                    renderer=renderer,
                    storage=storage,
                    using=using,
                ),
            )

        raise UnsupportedJobHandler(f"No job handler is registered for {job_type}")

    return resolve
