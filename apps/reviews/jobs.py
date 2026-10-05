"""Opt-in worker wrapper. Storage readback precedes atomic completion issuance.

The resolver always installs this wrapper; deployment gates remain closed.
Database metadata cannot independently prove the bytes; this wrapper is a
trusted report-worker execution boundary. Identity is checked before rendering.
"""

import json
from dataclasses import dataclass, replace

from django.db import connections

from apps.reports.artifact_services import read_verified_pdf_artifact


@dataclass(frozen=True)
class ReviewReportGenerationHandler:
    delegate: object
    worker_id: str | None = None

    @property
    def persistence_isolation(self):
        return self.delegate.persistence_isolation

    def prepare(self, job):
        with connections[self.delegate.using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.review_pack_projection(%s,%s)",
                [job.id, job.claim_token],
            )
            projection = cursor.fetchone()[0]
        if isinstance(projection, str):
            projection = json.loads(projection)
        if (
            type(projection) is dict
            and projection.get("schema") == "stewardence.review_worker_projection.v3"
        ):
            return self._prepare_capture_v4(job, projection)
        if (
            type(projection) is dict
            and projection.get("schema") == "stewardence.review_worker_projection.v2"
        ):
            return self._prepare_capture(job, projection)
        prepared = self.delegate.prepare(job)
        if projection is None:
            return prepared
        if type(self.worker_id) is not str or not self.worker_id.strip():
            raise ValueError("Review worker identity required before rendering")
        if isinstance(projection, str):
            projection = json.loads(projection)
        if (
            projection["job_id"] != str(job.id)
            or projection["organization_id"] != str(job.organization_id)
            or projection["report_id"] != str(prepared.report_id)
        ):
            raise ValueError("Review projection job binding mismatch")
        from .context import build_pack_context

        return replace(
            prepared,
            report_context=build_pack_context(prepared.report_context, projection),
        )

    def _prepare_capture(self, job, projection):
        from apps.reports.jobs import ReportGenerationPrepared
        from apps.reports.models import Report

        from .capture_context import (
            build_capture_pack_context,
            validate_capture_projection,
        )

        validate_capture_projection(projection)
        if (
            type(self.worker_id) is not str
            or not self.worker_id.strip()
            or projection["job_id"] != str(job.id)
            or projection["organization_id"] != str(job.organization_id)
            or job.job_type != "report_generation"
            or job.payload != {"report_id": projection["report_id"]}
        ):
            raise ValueError("Capture review job binding mismatch")
        report = Report.objects.using(self.delegate.using).get(
            id=projection["report_id"], organization_id=job.organization_id
        )
        pinned = projection["manifest"]["snapshot"]
        if (
            str(report.assessment_snapshot_id) != pinned["snapshot_id"]
            or str(report.created_by_id)
            != projection["snapshot_input"]["created_by_id"]
        ):
            raise ValueError("Capture review report owner binding mismatch")
        metadata = {
            "report_identifier": report.report_identifier,
            "organization_display_name": report.organization_display_name,
            "assessment_date": pinned["captured_at"],
            "assessment_id": pinned["assessment_id"],
            "assessment_version": pinned["assessment_version"],
            "assessment_snapshot_id": pinned["snapshot_id"],
            "input_sha256": pinned["input_sha256"],
            "result_sha256": pinned["result_sha256"],
        }
        return ReportGenerationPrepared(
            job.id,
            job.organization_id,
            report.id,
            build_capture_pack_context(metadata, projection),
        )

    def _prepare_capture_v4(self, job, projection):
        from apps.reports.jobs import ReportGenerationPrepared
        from apps.reports.models import Report

        from .capture_context_v3 import build_capture_v4_pack_context

        if (
            type(self.worker_id) is not str
            or not self.worker_id.strip()
            or projection["job_id"] != str(job.id)
            or projection["organization_id"] != str(job.organization_id)
            or job.job_type != "report_generation"
            or job.payload != {"report_id": projection["report_id"]}
        ):
            raise ValueError("Capture v4 job binding mismatch")
        report = Report.objects.using(self.delegate.using).get(
            id=projection["report_id"], organization_id=job.organization_id
        )
        pinned = projection["manifest"]["snapshot"]
        if (
            str(report.assessment_snapshot_id) != pinned["snapshot_id"]
            or str(report.created_by_id)
            != projection["snapshot_input"]["created_by_id"]
        ):
            raise ValueError("Capture v4 report owner binding mismatch")
        metadata = {
            "report_identifier": report.report_identifier,
            "organization_display_name": report.organization_display_name,
            "assessment_date": pinned["captured_at"],
            "assessment_id": pinned["assessment_id"],
            "assessment_version": pinned["assessment_version"],
            "assessment_snapshot_id": pinned["snapshot_id"],
            "input_sha256": pinned["input_sha256"],
            "result_sha256": pinned["result_sha256"],
        }
        return ReportGenerationPrepared(
            job.id,
            job.organization_id,
            report.id,
            build_capture_v4_pack_context(metadata, projection),
        )

    def execute_external(self, prepared, heartbeat):
        return self.delegate.execute_external(prepared, heartbeat=heartbeat)

    def persist(self, job, result):
        using = self.delegate.using
        # This runs within execute_claimed_job's existing fenced persistence
        # transaction; completion, artifact metadata and queue completion all
        # roll back together on any subsequent error.
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.review_job_target(%s,%s)", [job.id, job.claim_token]
            )
            request_id = cursor.fetchone()[0]
        artifact = self.delegate.persist(job, result)
        if request_id is not None:
            read_verified_pdf_artifact(artifact=artifact, storage=self.delegate.storage)
            with connections[using].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.complete_review_pack(%s,%s,%s,%s,%s)",
                    [request_id, artifact.id, job.id, self.worker_id, job.claim_token],
                )
                cursor.fetchone()
        return artifact
