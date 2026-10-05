import copy
import hashlib
from datetime import timedelta
import pytest
import rfc8785
from django.db import connections, DatabaseError, transaction
from django.utils import timezone
from agentledger.tenancy.context import tenant_transaction
from apps.jobs.models import BackgroundJob, RecoveryReceipt
from apps.jobs.queue import enqueue_job, claim_next_job, fail_job_with_fence, recover_expired_jobs, complete_job_with_fence
from apps.jobs.receipts import verify_recovery_receipt
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(transaction=True, databases='__all__')


def make_job():
    org = Organization.objects.create(name='Atomic receipt fixture')
    from conftest import grant_queue_owner
    grant_queue_owner(org)
    return enqueue_job(organization_id=org.id,job_type='report_generation',payload={'declared':125,'name':'Δ'})


def test_lease_expiry_receipt_is_atomic_and_not_duplicated():
    job = make_job()
    claim = claim_next_job('crashed-worker')
    BackgroundJob.objects.filter(pk=job.id).update(lock_expires_at=timezone.now()-timedelta(seconds=1))
    assert recover_expired_jobs() == 1
    receipt = RecoveryReceipt.objects.get(job=job)
    assert receipt.attempt == claim.attempts
    assert receipt.outcome == 'retry'
    assert receipt.payload['reason_code'] == 'lease_expired'
    assert verify_recovery_receipt(receipt)
    assert recover_expired_jobs() == 0
    assert RecoveryReceipt.objects.filter(job=job).count() == 1


def test_worker_cannot_insert_even_a_valid_receipt_or_change_job_inputs(request):
    job = make_job()
    claim = claim_next_job('worker')
    if claim is None:
        import json
        from tests.queue_claim_diagnostics import claim_none_facts
        request.node.add_report_section('call', 'claim None diagnostics',
            json.dumps(claim_none_facts(job.id), default=str, sort_keys=True))
    fail_job_with_fence(job_id=job.id,worker_id='worker',claim_token=claim.claim_token,
        error_code='job_requires_review',safe_summary='Review required',fingerprint='0'*64)
    receipt = RecoveryReceipt.objects.get(job=job)
    with tenant_transaction(job.organization_id,using='worker_runtime'):
        with pytest.raises(DatabaseError), transaction.atomic(using='worker_runtime'):
            RecoveryReceipt.objects.using('worker_runtime').create(organization_id=job.organization_id,
                job_id=job.id,attempt=receipt.attempt,outcome=receipt.outcome,payload=receipt.payload,sha256=receipt.sha256)
        with pytest.raises(DatabaseError), transaction.atomic(using='worker_runtime'):
            BackgroundJob.objects.using('worker_runtime').filter(pk=job.id).update(payload={'forged':True})


@pytest.mark.parametrize('mutation', ['digest','input','string_attempt','extra','missing','completed_reason'])
def test_database_admission_rejects_malformed_receipts(mutation):
    job = make_job()
    # Administrator fixture creates a terminal job without its automatic issuer,
    # solely to test the INSERT guard independently of uniqueness constraints.
    claim=claim_next_job('admission-fixture')
    with transaction.atomic(), connections['default'].cursor() as c:
        c.execute('ALTER TABLE background_jobs DISABLE TRIGGER job_transition_receipt')
        try:
            complete_job_with_fence(job_id=job.id,worker_id='admission-fixture',claim_token=claim.claim_token)
        finally:
            c.execute('ALTER TABLE background_jobs ENABLE TRIGGER job_transition_receipt')
    p = {'schema':'stewardence.recovery.v1','job_id':str(job.id),'organization_id':str(job.organization_id),
        'operation':job.job_type,'attempt':1,'outcome':'completed','input_sha256':job.input_sha256,
        'reason_code':'','failure_fingerprint':''}
    if mutation=='input': p['input_sha256']='0'*64
    if mutation=='string_attempt': p['attempt']='1'
    if mutation=='extra': p['extra']='unadmitted'
    if mutation=='missing': p.pop('reason_code')
    if mutation=='completed_reason': p['reason_code']='job_requires_review'
    digest = hashlib.sha256(rfc8785.dumps(p)).hexdigest()
    if mutation=='digest': digest='0'*64
    with pytest.raises(DatabaseError), transaction.atomic():
        RecoveryReceipt.objects.create(organization_id=job.organization_id,job_id=job.id,
            attempt=1,outcome='completed',payload=p,sha256=digest)


def test_retry_exhaustion_state_receipt_and_message_agree():
    job = make_job()
    for attempt in range(1,6):
        BackgroundJob.objects.filter(pk=job.id).update(available_at=timezone.now()-timedelta(seconds=1))
        claim = claim_next_job('worker')
        fail_job_with_fence(job_id=job.id,worker_id='worker',claim_token=claim.claim_token,
            error_code='job_execution_failed',safe_summary='Temporary failure; retry admitted',fingerprint='1'*64,retryable=True)
        job.refresh_from_db()
        receipt = RecoveryReceipt.objects.get(job=job,attempt=attempt)
        assert verify_recovery_receipt(receipt)
        if attempt < 5:
            assert job.status=='queued' and receipt.outcome=='retry'
        if attempt == 5:
            assert job.status=='failed' and receipt.outcome=='review'
            assert job.safe_error_summary=='Retry limit reached; review required.'
            assert receipt.payload['reason_code']=='retry_limit_reached'
    assert claim_next_job('worker') is None


def test_irreversible_migration_refuses_schema_reversal_without_breaking_writes():
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.exceptions import IrreversibleError
    executor=MigrationExecutor(connections['default'])
    with pytest.raises(IrreversibleError):
        executor.migrate([('jobs','0004_receipt_admission')])
    job=make_job()
    claim=claim_next_job('still-valid')
    complete_job_with_fence(job_id=job.id,worker_id='still-valid',claim_token=claim.claim_token)
    assert verify_recovery_receipt(RecoveryReceipt.objects.get(job=job))


@pytest.mark.parametrize('attempt',[1,2,5,32767])
@pytest.mark.parametrize('outcome',['completed','retry','review'])
def test_sql_receipt_encoding_matches_rfc8785_on_closed_domain(attempt,outcome):
    p={'schema':'stewardence.recovery.v1','job_id':str(__import__('uuid').uuid4()),
        'organization_id':str(__import__('uuid').uuid4()),'operation':'report_generation',
        'attempt':attempt,'outcome':outcome,'input_sha256':'a'*64,
        'reason_code':'' if outcome=='completed' else 'lease_expired',
        'failure_fingerprint':'' if outcome=='completed' else 'f'*64}
    import json
    with connections['default'].cursor() as c:
        c.execute('SELECT app_private.recovery_canonical(%s::jsonb)',[json.dumps(p)])
        encoded=c.fetchone()[0].encode()
    assert encoded==rfc8785.dumps(p)


@pytest.mark.parametrize('changes',[{'status':'completed','completed_at':timezone.now()},
    {'attempts':4},{'status':'running','attempts':4}])
def test_direct_worker_state_shortcuts_are_rejected(changes):
    job=make_job()
    with tenant_transaction(job.organization_id,using='worker_runtime'):
        with pytest.raises(DatabaseError),transaction.atomic(using='worker_runtime'):
            BackgroundJob.objects.using('worker_runtime').filter(pk=job.id).update(**changes)
    assert not RecoveryReceipt.objects.filter(job=job).exists()
