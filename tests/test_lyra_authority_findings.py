"""Actual restricted-role probes for expanded Lyra findings."""
import hashlib,json,time
from datetime import timedelta
from uuid import uuid4
import pytest,rfc8785
from django.db import DatabaseError,connections,transaction
from django.utils import timezone
from django.urls import reverse
from agentledger.tenancy.context import identity_transaction,tenant_transaction
from apps.jobs.models import BackgroundJob,RecoveryReceipt
from apps.jobs.core_models import WorkflowRun,CoreControl,WorkflowSchedule
from apps.jobs.core_workflows import dispatch,configure_control,configure_schedule
from apps.jobs.contracts import WorkflowRequest,Operation,BranchProfile
from apps.jobs.queue import claim_next_job,recover_expired_jobs,complete_job_with_fence,heartbeat_job_with_fence,LostJobLease
from apps.jobs.receipts import verify_recovery_receipt
from apps.billing.models import Subscription

pytestmark=pytest.mark.django_db(transaction=True,databases='__all__')

@pytest.fixture
def configured(report_context):
    from apps.organizations.models import WorkflowProfile
    user,org,*_=report_context
    WorkflowProfile.objects.create(organization=org,created_by=user,profile='business.v1',settings={'name':'Main'})
    return report_context

def test_application_cannot_insert_counterfeit_workflow_receipt(configured):
    user,org,_,_,snapshot=configured
    req=WorkflowRequest(org.id,Operation.REPORT,(snapshot.id,),timezone.now(),BranchProfile.BUSINESS)
    p={'schema':'stewardence.workflow_receipt.v1','request':req.envelope(),'authority':'proposal_only',
       'report_id':str(uuid4()),'job_id':str(uuid4()),'state':'queued'}
    with pytest.raises(DatabaseError),identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
        WorkflowRun.objects.using('app_runtime').create(organization=org,created_by=user,operation=req.operation.value,
            input_sha256=req.input_sha256,effective_at=req.effective_at,payload=p,sha256=hashlib.sha256(rfc8785.dumps(p)).hexdigest())
    run=dispatch(req,actor_id=user.id,using='app_runtime')
    assert run.payload['report_id']!=p['report_id']

def test_narrow_issuer_rejects_fabricated_effects(configured):
    user,org,_,_,snapshot=configured
    req=WorkflowRequest(org.id,Operation.REPORT,(snapshot.id,),timezone.now(),BranchProfile.BUSINESS)
    p={'schema':'stewardence.workflow_receipt.v1','request':req.envelope(),'authority':'proposal_only',
       'report_id':str(uuid4()),'job_id':str(uuid4()),'state':'queued'}
    with pytest.raises(DatabaseError),identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
        with connections['app_runtime'].cursor() as c:
            c.execute('SELECT app_private.issue_workflow_run(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)',
                [uuid4(),org.id,user.id,req.operation.value,req.input_sha256,req.effective_at,json.dumps(p),
                 rfc8785.dumps(p).decode(),hashlib.sha256(rfc8785.dumps(p)).hexdigest(),None])
    assert not WorkflowRun.objects.exists()

@pytest.mark.parametrize('job_type',['risk_reassessment','catalog_refresh','audit_batch_seal'])
def test_unknown_outcome_nonreport_expiry_is_review_not_replay(configured,job_type):
    user,org,*_=configured
    job=BackgroundJob.objects.create(organization=org,job_type=job_type,payload={},available_at=timezone.now(),priority=-100)
    claimed=claim_next_job('expiry-probe',using='worker_runtime')
    assert claimed.id==job.id
    BackgroundJob.objects.filter(pk=job.id).update(lock_expires_at=timezone.now()-timedelta(seconds=1))
    assert recover_expired_jobs(using='worker_runtime')==1
    job.refresh_from_db()
    assert job.status=='failed' and job.attempts==1
    receipt=RecoveryReceipt.objects.get(job=job)
    assert receipt.outcome=='review' and verify_recovery_receipt(receipt)
    second=claim_next_job('second-worker',using='worker_runtime')
    assert second is None or second.id!=job.id

def test_worker_raw_completion_and_expired_heartbeat_are_denied(configured):
    user,org,*_=configured
    job=BackgroundJob.objects.create(organization=org,job_type='report_generation',payload={},available_at=timezone.now(),priority=-100)
    claimed=claim_next_job('authority-probe',using='worker_runtime')
    assert claimed.id==job.id
    configure_control(organization_id=org.id,actor_id=user.id,mode='paused',reason='Pause before completion')
    with pytest.raises(DatabaseError),transaction.atomic(using='worker_runtime'):
        BackgroundJob.objects.using('worker_runtime').filter(pk=job.id).update(status='completed',completed_at=timezone.now(),
            locked_at=None,lock_expires_at=None,locked_by=None,claim_token=None)
    with pytest.raises(LostJobLease):
        complete_job_with_fence(job_id=job.id,worker_id='authority-probe',claim_token=claimed.claim_token,using='worker_runtime')
    BackgroundJob.objects.filter(pk=job.id).update(lock_expires_at=timezone.now()-timedelta(seconds=1))
    with pytest.raises(DatabaseError),transaction.atomic(using='worker_runtime'):
        BackgroundJob.objects.using('worker_runtime').filter(pk=job.id).update(lock_expires_at=timezone.now()+timedelta(minutes=10))
    with pytest.raises(LostJobLease):
        heartbeat_job_with_fence(job_id=job.id,worker_id='authority-probe',claim_token=claimed.claim_token,using='worker_runtime')
    assert not RecoveryReceipt.objects.filter(job=job).exists()

def test_owner_can_stop_after_entitlement_lapses_and_cannot_resume(client,configured):
    user,org,*_=configured
    Subscription.objects.filter(organization=org).update(status='canceled')
    response=client.post(reverse('core-pause'))
    assert response.status_code==200 and response['Cache-Control']=='private, no-store'
    assert CoreControl.objects.get().mode=='paused'
    from django.core.exceptions import PermissionDenied
    with pytest.raises(PermissionDenied): configure_control(organization_id=org.id,actor_id=user.id,mode='normal',reason='Not paid')

def test_direct_schedule_insert_rejects_lapsed_owner(configured):
    user,org,_,_,snapshot=configured
    Subscription.objects.filter(organization=org).update(status='canceled')
    with pytest.raises(DatabaseError),identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
        WorkflowSchedule.objects.using('app_runtime').create(organization=org,created_by=user,snapshot=snapshot,
            snapshot_sha256=snapshot.result_sha256,interval_hours=24,starts_at=timezone.now())

@pytest.mark.parametrize('role',['app_runtime','worker_runtime'])
def test_runtime_insert_rejects_payload_digest_mismatch(configured,role):
    user,org,*_=configured
    with pytest.raises(DatabaseError),identity_transaction(user.id,using=role),tenant_transaction(org.id,using=role):
        with connections[role].cursor() as c:
            c.execute("INSERT INTO background_jobs(id,organization_id,job_type,payload,input_sha256,status,priority,attempts,available_at,created_at) VALUES(%s,%s,'audit_batch_seal','{}','0000000000000000000000000000000000000000000000000000000000000000','queued',100,0,clock_timestamp(),clock_timestamp())",[uuid4(),org.id])

@pytest.mark.parametrize('p',[{}, {'x':'Δ😀\n\t"\\','n':9007199254740991,'z':[True,None,-42]}, {'a':{'b':0},'z':'unknown'}])
def test_closed_queue_canonical_domain_matches_rfc8785(p):
    with connections['default'].cursor() as c:
        c.execute('SELECT app_private.queue_canonical(%s::jsonb)',[json.dumps(p)])
        assert c.fetchone()[0].encode()==rfc8785.dumps(p)

@pytest.mark.parametrize('p',[{'n':1.25},{'n':9007199254740992},{'Δ':'non-ASCII key'}])
def test_queue_unsupported_number_or_key_requires_new_contract(p):
    with pytest.raises(DatabaseError),transaction.atomic(),connections['default'].cursor() as c:
        c.execute('SELECT app_private.queue_canonical(%s::jsonb)',[json.dumps(p)])


def wait_for_database_lock(application_name):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        with connections['default'].cursor() as c:
            c.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event_type='Lock')",[application_name])
            if c.fetchone()[0]: return
        time.sleep(.02)
    pytest.fail('Probe did not reach the deterministic database lock barrier')


def test_raw_owner_pause_insert_serializes_with_inflight_persistence(configured):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from apps.jobs.queue import lock_job_for_persistence
    user,org,*_=configured
    job=BackgroundJob.objects.create(organization=org,job_type='report_generation',payload={},available_at=timezone.now(),priority=-100)
    claimed=claim_next_job('ordered-worker',using='worker_runtime')
    assert claimed.id==job.id
    def raw_pause():
        close_old_connections()
        try:
            with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
                with connections['app_runtime'].cursor() as c: c.execute("SET LOCAL application_name='core-raw-pause-probe'")
                CoreControl.objects.using('app_runtime').create(organization=org,created_by=user,mode='paused',reason='Raw owner stop')
            return True
        finally: connections['app_runtime'].close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic(using='worker_runtime'):
            lock_job_for_persistence(job_id=job.id,worker_id='ordered-worker',claim_token=claimed.claim_token,using='worker_runtime')
            future=pool.submit(raw_pause)
            wait_for_database_lock('core-raw-pause-probe')
            assert not future.done()
            complete_job_with_fence(job_id=job.id,worker_id='ordered-worker',claim_token=claimed.claim_token,using='worker_runtime')
        assert future.result(timeout=10)
    job.refresh_from_db()
    assert job.status=='completed' and CoreControl.objects.get().mode=='paused'


def test_persistence_waiting_for_pause_does_not_use_old_snapshot(configured):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections
    from apps.jobs.queue import lock_job_for_persistence
    user,org,*_=configured
    job=BackgroundJob.objects.create(organization=org,job_type='report_generation',payload={},available_at=timezone.now(),priority=-100)
    claimed=claim_next_job('waiting-worker',using='worker_runtime')
    assert claimed.id==job.id
    def persist_after_wait():
        close_old_connections()
        try:
            with transaction.atomic(using='worker_runtime'):
                with connections['worker_runtime'].cursor() as c:c.execute("SET LOCAL application_name='core-persistence-wait-probe'")
                lock_job_for_persistence(job_id=job.id,worker_id='waiting-worker',claim_token=claimed.claim_token,using='worker_runtime')
            return 'admitted'
        except LostJobLease: return 'blocked'
        finally: connections['worker_runtime'].close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
            CoreControl.objects.using('app_runtime').create(organization=org,created_by=user,mode='paused',reason='Commit pause before persistence')
            future=pool.submit(persist_after_wait)
            wait_for_database_lock('core-persistence-wait-probe')
            assert not future.done()
        assert future.result(timeout=10)=='blocked'
    assert not RecoveryReceipt.objects.filter(job=job).exists()


def test_report_persistence_refuses_repeatable_read_before_any_effect(configured):
    from apps.jobs.queue import lock_job_for_persistence
    user,org,*_=configured
    job=BackgroundJob.objects.create(organization=org,job_type='report_generation',payload={},available_at=timezone.now(),priority=-100)
    claimed=claim_next_job('isolation-probe',using='worker_runtime')
    assert claimed.id==job.id
    with pytest.raises(DatabaseError),tenant_transaction(org.id,using='worker_runtime',isolation='repeatable_read'):
        lock_job_for_persistence(job_id=job.id,worker_id='isolation-probe',claim_token=claimed.claim_token,using='worker_runtime')
