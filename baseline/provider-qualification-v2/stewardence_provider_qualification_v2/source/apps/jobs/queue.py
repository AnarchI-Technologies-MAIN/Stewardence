from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import connections, transaction
from django.db.models.functions import Now

from .models import BackgroundJob

JOB_LEASE = timedelta(minutes=10)
MAX_ATTEMPTS = 5


class LostJobLease(RuntimeError):
    pass


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    organization_id: uuid.UUID
    job_type: str
    payload: dict[str, Any]
    attempts: int
    claim_token: uuid.UUID


def _hydrate_job_payload(value):
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        decoded = json.loads(value)

        if not isinstance(decoded, dict):
            raise ValueError("Background job payload must hydrate to a JSON object")

        return decoded

    raise ValueError("Background job payload must be a JSON object")


def enqueue_job(
    *,
    organization_id,
    job_type: str,
    payload: dict[str, Any],
    priority: int = 100,
    using: str = "default",
) -> BackgroundJob:
    if job_type not in BackgroundJob.Type.values:
        raise ValueError("Unsupported background job type")
    if not isinstance(payload, dict):
        raise ValueError("Background job payload must be a JSON object")
    job = BackgroundJob.objects.using(using).create(
        organization_id=organization_id,
        job_type=job_type,
        payload=payload,
        priority=priority,
        available_at=Now(),
    )
    job.refresh_from_db(using=using)
    return job


def _claimed_job(row) -> ClaimedJob:
    return ClaimedJob(
        id=row[0],
        organization_id=row[1],
        job_type=row[2],
        payload=_hydrate_job_payload(row[3]),
        attempts=row[4],
        claim_token=row[5],
    )


def claim_next_job(
    worker_id: str,
    *,
    using: str = "default",
    lease: timedelta = JOB_LEASE,
) -> ClaimedJob | None:
    claim_token = uuid.uuid4()
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            """
            WITH candidate AS (
                SELECT id
                FROM background_jobs
                WHERE status = 'queued'
                  AND available_at <= clock_timestamp()
                ORDER BY priority, available_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE background_jobs AS job
            SET status = 'running',
                locked_by = %s,
                locked_at = clock_timestamp(),
                lock_expires_at = clock_timestamp() + %s,
                claim_token = %s,
                attempts = job.attempts + 1
            FROM candidate
            WHERE job.id = candidate.id
            RETURNING job.id, job.organization_id, job.job_type,
                      job.payload, job.attempts, job.claim_token
            """,
            [worker_id, lease, claim_token],
        )
        row = cursor.fetchone()
    return _claimed_job(row) if row else None


def complete_job_with_fence(
    *,
    job_id,
    worker_id: str,
    claim_token,
    using: str = "default",
) -> None:
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            """
            UPDATE background_jobs
            SET status = 'completed',
                completed_at = clock_timestamp(),
                available_at = clock_timestamp(),
                locked_at = NULL,
                lock_expires_at = NULL,
                locked_by = NULL,
                claim_token = NULL
            WHERE id = %s
              AND status = 'running'
              AND locked_by = %s
              AND claim_token = %s
              AND lock_expires_at > clock_timestamp()
            """,
            [job_id, worker_id, claim_token],
        )
        if cursor.rowcount != 1:
            raise LostJobLease(str(job_id))


def heartbeat_job_with_fence(
    *,
    job_id,
    worker_id: str,
    claim_token,
    using: str = "default",
    lease: timedelta = JOB_LEASE,
) -> None:
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            """
            UPDATE background_jobs
            SET lock_expires_at = clock_timestamp() + %s
            WHERE id = %s
              AND status = 'running'
              AND locked_by = %s
              AND claim_token = %s
              AND lock_expires_at > clock_timestamp()
            """,
            [lease, job_id, worker_id, claim_token],
        )
        if cursor.rowcount != 1:
            raise LostJobLease(str(job_id))


def fail_job_with_fence(
    *,
    job_id,
    worker_id: str,
    claim_token,
    error_code: str,
    safe_summary: str,
    fingerprint: str,
    using: str = "default",
) -> None:
    if not error_code or not safe_summary or not fingerprint:
        raise ValueError("Safe error code, summary, and fingerprint are required")
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            """
            UPDATE background_jobs
            SET status = CASE WHEN attempts >= 5 THEN 'failed' ELSE 'queued' END,
                available_at = CASE attempts
                    WHEN 1 THEN clock_timestamp() + interval '1 minute'
                    WHEN 2 THEN clock_timestamp() + interval '5 minutes'
                    WHEN 3 THEN clock_timestamp() + interval '30 minutes'
                    WHEN 4 THEN clock_timestamp() + interval '2 hours'
                    ELSE clock_timestamp()
                END,
                completed_at = CASE
                    WHEN attempts >= 5 THEN clock_timestamp()
                    ELSE NULL
                END,
                locked_at = NULL,
                lock_expires_at = NULL,
                locked_by = NULL,
                claim_token = NULL,
                error_code = %s,
                safe_error_summary = %s,
                error_fingerprint = %s
            WHERE id = %s
              AND status = 'running'
              AND locked_by = %s
              AND claim_token = %s
              AND lock_expires_at > clock_timestamp()
            """,
            [
                error_code,
                safe_summary,
                fingerprint,
                job_id,
                worker_id,
                claim_token,
            ],
        )
        if cursor.rowcount != 1:
            raise LostJobLease(str(job_id))


def recover_expired_jobs(*, using: str = "default") -> int:
    with transaction.atomic(using=using), connections[using].cursor() as cursor:
        cursor.execute(
            """
            UPDATE background_jobs
            SET status = CASE WHEN attempts >= 5 THEN 'failed' ELSE 'queued' END,
                available_at = clock_timestamp(),
                completed_at = CASE
                    WHEN attempts >= 5 THEN clock_timestamp()
                    ELSE NULL
                END,
                locked_at = NULL,
                lock_expires_at = NULL,
                locked_by = NULL,
                claim_token = NULL,
                error_code = 'lease_expired',
                safe_error_summary = 'The worker lease expired before completion.',
                error_fingerprint = 'worker_lease_expired'
            WHERE status = 'running'
              AND lock_expires_at < clock_timestamp()
            """
        )
        return cursor.rowcount
