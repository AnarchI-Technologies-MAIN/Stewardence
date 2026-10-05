from __future__ import annotations

import uuid
from dataclasses import dataclass

from apps.jobs.models import BackgroundJob
from apps.jobs.queue import ClaimedJob

from .sealing import seal_tenant_audit_events


class AuditBatchSealJobError(ValueError):
    pass


@dataclass(frozen=True)
class AuditBatchSealPrepared:
    job_id: uuid.UUID
    organization_id: uuid.UUID


@dataclass(frozen=True)
class AuditBatchSealHandler:
    using: str = "default"
    persistence_isolation: str = "repeatable_read"

    def prepare(
        self,
        job: ClaimedJob,
    ) -> AuditBatchSealPrepared:
        if job.job_type != BackgroundJob.Type.AUDIT_BATCH_SEAL:
            raise AuditBatchSealJobError(
                "Audit batch seal handler received the wrong job type"
            )

        if job.payload != {}:
            raise AuditBatchSealJobError(
                "Audit batch seal jobs do not accept payload parameters"
            )

        return AuditBatchSealPrepared(
            job_id=job.id,
            organization_id=job.organization_id,
        )

    def execute_external(
        self,
        prepared: AuditBatchSealPrepared,
        heartbeat,
    ) -> AuditBatchSealPrepared:
        heartbeat()
        return prepared

    def persist(
        self,
        job: ClaimedJob,
        result: AuditBatchSealPrepared,
    ):
        if result.job_id != job.id:
            raise AuditBatchSealJobError(
                "Audit batch seal job identity changed during execution"
            )

        if result.organization_id != job.organization_id:
            raise AuditBatchSealJobError(
                "Audit batch seal tenant identity changed during execution"
            )

        return seal_tenant_audit_events(
            job.organization_id,
            using=self.using,
        )
