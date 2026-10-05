from __future__ import annotations
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from django.db import connections, transaction
from django.db.models.functions import Now
from .models import BackgroundJob

JOB_LEASE=timedelta(minutes=10)
MAX_ATTEMPTS=5

class LostJobLease(RuntimeError):
    pass

@dataclass(frozen=True)
class ClaimedJob:
    id:uuid.UUID
    organization_id:uuid.UUID
    job_type:str
    payload:dict[str,Any]
    attempts:int
    claim_token:uuid.UUID
    input_sha256:str|None=None

def _hydrate_job_payload(value):
    if isinstance(value,str): value=json.loads(value)
    if not isinstance(value,dict): raise ValueError('Background job payload must be a JSON object')
    return value

def enqueue_job(*,organization_id,job_type,payload,priority=100,using='default'):
    if job_type not in BackgroundJob.Type.values: raise ValueError('Unsupported background job type')
    if not isinstance(payload,dict): raise ValueError('Background job payload must be a JSON object')
    job=BackgroundJob.objects.using(using).create(organization_id=organization_id,job_type=job_type,
        payload=payload,priority=priority,available_at=Now())
    job.refresh_from_db(using=using)
    return job

def _claimed_job(row):
    return ClaimedJob(row[0],row[1],row[2],_hydrate_job_payload(row[3]),row[4],row[5],row[6])

def claim_next_job(worker_id,*,using='default',lease=JOB_LEASE):
    with transaction.atomic(using=using),connections[using].cursor() as c:
        c.execute('SELECT id,organization_id,job_type,payload,attempts,claim_token,input_sha256 FROM app_private.claim_job(%s,%s,%s)',
            [worker_id,lease,uuid.uuid4()])
        row=c.fetchone()
    return _claimed_job(row) if row else None

def _transition(job_id,worker_id,claim_token,action,using,*,lease=JOB_LEASE,
    error_code=None,safe_summary=None,fingerprint=None,retryable=False):
    with transaction.atomic(using=using),connections[using].cursor() as c:
        c.execute('SELECT app_private.finish_job(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            [job_id,worker_id,claim_token,action,lease,error_code,safe_summary,fingerprint,retryable])
        if c.fetchone()[0] is not True: raise LostJobLease(str(job_id))

def complete_job_with_fence(*,job_id,worker_id,claim_token,using='default'):
    _transition(job_id,worker_id,claim_token,'complete',using)

def heartbeat_job_with_fence(*,job_id,worker_id,claim_token,using='default',lease=JOB_LEASE):
    _transition(job_id,worker_id,claim_token,'heartbeat',using,lease=lease)

def fail_job_with_fence(*,job_id,worker_id,claim_token,error_code,safe_summary,fingerprint,using='default',retryable=False):
    if not error_code or not safe_summary or not fingerprint:
        raise ValueError('Safe error code, summary, and fingerprint are required')
    _transition(job_id,worker_id,claim_token,'fail',using,error_code=error_code,
        safe_summary=safe_summary,fingerprint=fingerprint,retryable=retryable)

def lock_job_for_persistence(*,job_id,worker_id,claim_token,using='default'):
    if not connections[using].in_atomic_block: raise RuntimeError('Persistence fencing requires an active transaction')
    with connections[using].cursor() as c:
        c.execute('SELECT app_private.lock_job_persistence(%s,%s,%s)',[job_id,worker_id,claim_token])
        if c.fetchone()[0] is not True: raise LostJobLease(str(job_id))

def recover_expired_jobs(*,using='default'):
    with transaction.atomic(using=using),connections[using].cursor() as c:
        c.execute('SELECT app_private.recover_jobs()')
        return c.fetchone()[0]
