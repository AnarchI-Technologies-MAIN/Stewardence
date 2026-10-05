import copy
from uuid import uuid4
import pytest
from django.db import DatabaseError, transaction, connections
from agentledger.tenancy.context import tenant_transaction
from apps.jobs.models import BackgroundJob, RecoveryReceipt
from apps.jobs.queue import enqueue_job
from apps.jobs.worker import drain_queue
from apps.jobs.receipts import verify_recovery_receipt
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def completed_receipt():
    organization = Organization.objects.create(name="Attack target")
    from conftest import grant_queue_owner
    grant_queue_owner(organization)
    job = enqueue_job(organization_id=organization.id,
        job_type=BackgroundJob.Type.REPORT_GENERATION, payload={"report_id":str(uuid4())})
    class Handler:
        def prepare(self, job): return None
        def execute_external(self, prepared, heartbeat): return None
        def persist(self, job, result): return None
    drain_queue("attack-test-worker", lambda kind: Handler(), using="worker_runtime", max_jobs=1)
    return RecoveryReceipt.objects.get(job=job)


def test_application_cannot_forge_a_recovery_receipt(completed_receipt):
    receipt = completed_receipt
    with tenant_transaction(receipt.organization_id, using="app_runtime"):
        with pytest.raises(DatabaseError), transaction.atomic(using="app_runtime"):
            RecoveryReceipt.objects.using("app_runtime").create(organization_id=receipt.organization_id,
                job_id=receipt.job_id, attempt=receipt.attempt, outcome="completed",
                payload=receipt.payload, sha256=receipt.sha256)


def test_self_consistent_hash_cannot_hide_forged_input(completed_receipt):
    import hashlib
    import rfc8785
    forged = copy.copy(completed_receipt)
    forged.payload = {**forged.payload, "input_sha256":"0"*64}
    forged.sha256 = hashlib.sha256(rfc8785.dumps(forged.payload)).hexdigest()
    assert not verify_recovery_receipt(forged)
    forged.payload = {**completed_receipt.payload, "attempt":True}
    forged.sha256 = hashlib.sha256(rfc8785.dumps(forged.payload)).hexdigest()
    assert not verify_recovery_receipt(forged)


def test_temporary_table_cannot_bypass_cross_tenant_job_binding(completed_receipt):
    receipt = completed_receipt
    other = Organization.objects.create(name="Shadow attacker")
    with tenant_transaction(other.id, using="worker_runtime"):
        with connections["worker_runtime"].cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE background_jobs (id uuid, organization_id uuid, attempts integer, status text, job_type text) ON COMMIT DROP")
            cursor.execute("INSERT INTO pg_temp.background_jobs VALUES (%s,%s,%s,'completed',%s)",
                [receipt.job_id, other.id, receipt.attempt, receipt.job.job_type])
        with pytest.raises(DatabaseError), transaction.atomic(using="worker_runtime"):
            RecoveryReceipt.objects.using("worker_runtime").create(organization=other,
                job_id=receipt.job_id, attempt=receipt.attempt, outcome="completed",
                payload={**receipt.payload, "organization_id":str(other.id)}, sha256="0"*64)


def test_worker_completion_receipt_is_bound_immutable_and_tenant_private():
    organization = Organization.objects.create(name="Receipt firm")
    from conftest import grant_queue_owner
    grant_queue_owner(organization)
    other = Organization.objects.create(name="Other receipt firm")
    job = enqueue_job(organization_id=organization.id,
        job_type=BackgroundJob.Type.REPORT_GENERATION, payload={"report_id":str(uuid4())})
    class Handler:
        def prepare(self, job): return None
        def execute_external(self, prepared, heartbeat): return None
        def persist(self, job, result): return None
    drain_queue("receipt-worker", lambda kind: Handler(), using="worker_runtime", max_jobs=1)
    receipt = RecoveryReceipt.objects.get(job=job)
    assert verify_recovery_receipt(receipt)
    assert receipt.outcome == "completed"
    with tenant_transaction(other.id, using="app_runtime"):
        assert not RecoveryReceipt.objects.using("app_runtime").filter(id=receipt.id).exists()
    with tenant_transaction(organization.id, using="app_runtime"):
        assert RecoveryReceipt.objects.using("app_runtime").filter(id=receipt.id).exists()
    with pytest.raises(DatabaseError), transaction.atomic():
        RecoveryReceipt.objects.filter(id=receipt.id).update(payload={})
    with pytest.raises(DatabaseError), transaction.atomic():
        RecoveryReceipt.objects.filter(id=receipt.id).delete()
    changed = copy.copy(receipt)
    changed.organization_id = other.id
    assert not verify_recovery_receipt(changed)
