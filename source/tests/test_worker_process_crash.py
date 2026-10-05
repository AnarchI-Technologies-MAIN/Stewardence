"""Actual SIGKILL qualification in the disposable Linux test container.

Synthetic report bytes and local storage only; no live provider/object service.
"""

import os
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import pytest
from django.db import connections

from apps.jobs.models import BackgroundJob, RecoveryReceipt
from apps.jobs.queue import recover_expired_jobs
from apps.jobs.receipts import verify_recovery_receipt
from apps.jobs.worker import drain_queue
from apps.reports.jobs import ReportGenerationHandler, ensure_report_generation_job
from apps.reports.models import ReportArtifact
from apps.reports.services import create_report
from apps.reports.storage import LocalPrivateReportStorage, build_pdf_object_key

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")
PDF = b"%PDF-1.4\nsynthetic-crash-qualification\n%%EOF"

CHILD = r"""
import os, signal,json
from pathlib import Path
from datetime import timedelta
import django
django.setup()
from apps.jobs import worker
from apps.jobs.queue import claim_next_job
from apps.reports.models import Report
from apps.reports.storage import LocalPrivateReportStorage, build_pdf_object_key
from apps.reports.artifact_services import persist_pdf_artifact
stage=os.environ['CRASH_STAGE']; root=os.environ['CRASH_ROOT']
storage=LocalPrivateReportStorage(root=root)
pdf=b'%PDF-1.4\nsynthetic-crash-qualification\n%%EOF'
active_job=None
def crash(outcome=None):
 from django.db import connections
 with connections['worker_runtime'].cursor() as c:
  c.execute('SELECT pg_backend_pid(),current_user,'
   'current_setting(\'transaction_isolation\')')
  backend,role,isolation=c.fetchone()
 Path(root,'kill-barrier.json').write_text(json.dumps({'stage':stage,'outcome':outcome,
  'job_id':str(active_job.id),'process_id':os.getpid(),'database_backend':backend,
  'database_role':role,'isolation':isolation}))
 os.kill(os.getpid(),signal.SIGKILL)
worker.claim_next_job=lambda worker_id,using:claim_next_job(
 worker_id,using=using,lease=timedelta(seconds=1))
class Handler:
 def prepare(self,job):
  global active_job
  active_job=job
  if stage=='claimed': crash()
  return Report.objects.using('worker_runtime').get(id=job.payload['report_id'])
 def execute_external(self,report,heartbeat):
  key=build_pdf_object_key(organization_id=report.organization_id,assessment_snapshot_id=report.assessment_snapshot_id,report_id=report.id)
  storage.put(key=key,content=pdf,content_type='application/pdf')
  if stage=='external': crash()
  return report
 def persist(self,job,report):
  persist_pdf_artifact(report=report,pdf_bytes=pdf,storage=storage,using='worker_runtime')
  if stage=='persistence': crash()
if stage=='before_commit':
 original=worker.record_recovery_receipt
 def record(*a,**kw):
  original(*a,**kw)
  if a[1]=='completed': crash(outcome='completed')
 worker.record_recovery_receipt=record
worker.drain_queue('terminated-process',lambda kind:Handler(),
 using='worker_runtime',max_jobs=1)
crash()
"""


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="SIGKILL qualification runs in Linux qualification image",
)
@pytest.mark.parametrize(
    "stage", ["claimed", "external", "persistence", "before_commit", "after_commit"]
)
def test_actual_process_termination_and_independent_recovery(
    stage, tmp_path, report_context
):
    user, org, _, _, snapshot = report_context
    report = create_report(
        organization_id=org.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    job = ensure_report_generation_job(report=report)
    BackgroundJob.objects.filter(pk=job.id).update(priority=-100)
    env = os.environ.copy()
    for variable in (
        "DATABASE_URL",
        "OWNER_DATABASE_URL",
        "APP_DATABASE_URL",
        "WORKER_DATABASE_URL",
    ):
        parts = urlsplit(env[variable])
        env[variable] = urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                "/" + connections["default"].settings_dict["NAME"],
                parts.query,
                parts.fragment,
            )
        )
    env.update(CRASH_STAGE=stage, CRASH_ROOT=str(tmp_path))
    killed = subprocess.run(
        [sys.executable, "-c", CHILD], env=env, capture_output=True, timeout=30
    )
    assert killed.returncode == -9, "Child must terminate by SIGKILL, not setup error"
    import json

    barrier = json.loads((tmp_path / "kill-barrier.json").read_text())
    assert barrier["stage"] == stage and barrier["job_id"] == str(job.id)
    assert barrier["process_id"] > 0
    assert barrier["database_role"] == "agentledger_worker"
    assert barrier["isolation"] == "read committed"
    if stage == "before_commit":
        assert barrier["outcome"] == "completed"
    # Process exit alone does not prove PostgreSQL has noticed socket loss and
    # rolled back the uncommitted persistence transaction. Observe that boundary.
    deadline = time.monotonic() + 5
    backend_present = True
    while backend_present and time.monotonic() < deadline:
        with connections["default"].cursor() as c:
            c.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)",
                [barrier["database_backend"]],
            )
            backend_present = c.fetchone()[0]
        if backend_present:
            time.sleep(0.01)
    assert not backend_present, "Killed worker database backend must disappear"
    job.refresh_from_db()
    if stage == "after_commit":
        assert job.status == "completed"
        assert ReportArtifact.objects.filter(report=report).count() == 1
        assert verify_recovery_receipt(RecoveryReceipt.objects.get(job=job))
        assert recover_expired_jobs() == 0
        return
    assert job.status == "running"
    assert job.attempts == 1 and job.locked_by == "terminated-process"
    assert job.claim_token is not None
    with connections["default"].cursor() as c:
        c.execute(
            "SELECT lock_expires_at-clock_timestamp() FROM background_jobs WHERE id=%s",
            [job.id],
        )
        assert c.fetchone()[0] <= __import__("datetime").timedelta(seconds=1)
    assert not ReportArtifact.objects.filter(report=report).exists()
    assert not RecoveryReceipt.objects.filter(job=job).exists()
    storage = LocalPrivateReportStorage(root=tmp_path)
    key = build_pdf_object_key(
        organization_id=org.id, assessment_snapshot_id=snapshot.id, report_id=report.id
    )
    if stage != "claimed":
        assert storage.get(key=key) == PDF
    # Observe real database-clock expiry separately from the recovery UPDATE.
    deadline = time.monotonic() + 5
    expired_lease = False
    while not expired_lease and time.monotonic() < deadline:
        with connections["default"].cursor() as c:
            c.execute(
                "SELECT lock_expires_at<clock_timestamp() "
                "FROM background_jobs WHERE id=%s",
                [job.id],
            )
            expired_lease = c.fetchone()[0]
        if not expired_lease:
            time.sleep(0.01)
    assert expired_lease, "Committed original claim must expire without lease rewriting"
    # The recoverer count is global; this isolated case expects one eligible job.
    deadline = time.monotonic() + 5
    recovered = 0
    while not recovered and time.monotonic() < deadline:
        recovered = recover_expired_jobs(using="worker_runtime")
        if not recovered:
            time.sleep(0.1)
    assert recovered == 1, (
        "Terminated worker must become recoverable within five seconds"
    )
    assert recover_expired_jobs(using="worker_runtime") == 0
    job.refresh_from_db()
    assert job.status == "queued" and job.attempts == 1
    assert RecoveryReceipt.objects.filter(job=job).count() == 1
    expired = RecoveryReceipt.objects.get(job=job)
    assert expired.payload[
        "reason_code"
    ] == "lease_expired" and verify_recovery_receipt(expired)

    class Renderer:
        def render(self, context):
            return PDF

    handler = ReportGenerationHandler(
        renderer=Renderer(), storage=storage, using="worker_runtime"
    )
    assert (
        drain_queue(
            "independent-recoverer",
            lambda kind: handler,
            using="worker_runtime",
            max_jobs=1,
        )
        == 1
    )
    job.refresh_from_db()
    assert job.status == "completed" and job.attempts == 2
    assert ReportArtifact.objects.filter(report=report).count() == 1
    assert RecoveryReceipt.objects.filter(job=job).count() == 2
    assert all(
        verify_recovery_receipt(r) for r in RecoveryReceipt.objects.filter(job=job)
    )
    assert storage.get(key=key) == PDF
