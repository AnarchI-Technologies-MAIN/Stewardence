from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from agentledger.tenancy.context import tenant_transaction

from .queue import (
    ClaimedJob,
    LostJobLease,
    claim_next_job,
    complete_job_with_fence,
    fail_job_with_fence,
    heartbeat_job_with_fence,
    recover_expired_jobs,
)


class JobHandler(Protocol):
    persistence_isolation: str | None

    def prepare(self, job: ClaimedJob): ...

    def execute_external(self, prepared, heartbeat): ...

    def persist(self, job: ClaimedJob, result): ...


JobHandlerResolver = Callable[[str], JobHandler]


@dataclass(frozen=True)
class JobExecution:
    job: ClaimedJob
    worker_id: str


def execute_claimed_job(
    execution: JobExecution,
    handler: JobHandler,
    *,
    using: str = "default",
) -> None:
    job = execution.job

    with tenant_transaction(job.organization_id, using=using):
        prepared = handler.prepare(job)

    def heartbeat():
        heartbeat_job_with_fence(
            job_id=job.id,
            worker_id=execution.worker_id,
            claim_token=job.claim_token,
            using=using,
        )

    result = handler.execute_external(prepared, heartbeat)

    with tenant_transaction(
        job.organization_id,
        using=using,
        isolation=getattr(
            handler,
            "persistence_isolation",
            None,
        ),
    ):
        handler.persist(job, result)

    complete_job_with_fence(
        job_id=job.id,
        worker_id=execution.worker_id,
        claim_token=job.claim_token,
        using=using,
    )


def _safe_failure_fingerprint(job: ClaimedJob, error: Exception) -> str:
    error_type = f"{type(error).__module__}.{type(error).__qualname__}"
    material = f"{job.job_type}:{error_type}".encode()
    return hashlib.sha256(material).hexdigest()


def drain_queue(
    worker_id: str,
    handler_resolver: JobHandlerResolver,
    *,
    using: str = "default",
    max_jobs: int | None = None,
) -> int:
    if max_jobs is not None and max_jobs < 1:
        raise ValueError("max_jobs must be at least 1")

    recover_expired_jobs(using=using)

    processed = 0

    while max_jobs is None or processed < max_jobs:
        job = claim_next_job(worker_id, using=using)

        if job is None:
            break

        execution = JobExecution(
            job=job,
            worker_id=worker_id,
        )

        try:
            handler = handler_resolver(job.job_type)
            execute_claimed_job(
                execution,
                handler,
                using=using,
            )
        except LostJobLease:
            raise
        except Exception as error:
            fail_job_with_fence(
                job_id=job.id,
                worker_id=worker_id,
                claim_token=job.claim_token,
                error_code="job_execution_failed",
                safe_summary="The background operation failed and may be retried.",
                fingerprint=_safe_failure_fingerprint(job, error),
                using=using,
            )

        processed += 1

    return processed
