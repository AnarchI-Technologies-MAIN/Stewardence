"""Closed candidate, actual local storage/roles; no Spaces or rendering claim."""
from uuid import uuid4
from uuid import UUID
import pytest
from django.core.exceptions import ValidationError
from django.db import connections, DatabaseError, transaction
from django.utils import timezone
from datetime import timedelta
from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import claim_next_job
from apps.jobs.worker import execute_claimed_job, JobExecution
from apps.jobs.core_workflows import configure_control
from apps.billing.models import PaidCoverageAuthority
from apps.assessments.snapshots import create_assessment_snapshot
from tests.conftest import _roi_inputs
from apps.organizations.models import WorkflowProfile
from apps.reports.jobs import ReportGenerationHandler
from apps.reports.models import ReportArtifact
from apps.reports.storage import LocalPrivateReportStorage, ReportStorageError
from apps.reviews.jobs import ReviewReportGenerationHandler
from apps.reviews.models import (ReviewCycle,ArtifactRequest,PackCompletion,BaselineHead,
                                ReviewLifecycleGate,ReservationEvent)
from apps.reviews.services import open_cycle,freeze_cycle,request_pack_artifact

pytestmark=pytest.mark.django_db(transaction=True,databases='__all__')


class Renderer:
    def render(self,context):
        return b'%PDF-1.7\nclosed local qualification\n%%EOF\n'


@pytest.fixture
def pack_context(report_context):
    user,org,_,_,snapshot=report_context
    WorkflowProfile.objects.create(organization=org,created_by=user,profile='business.v1',settings={'name':'Main'})
    cycle=open_cycle(organization_id=org.id,actor_id=user.id,input_snapshot_id=snapshot.id,using='app_runtime')
    pack=freeze_cycle(cycle_id=cycle.id,organization_id=org.id,actor_id=user.id,expected_revision=1,using='app_runtime')
    return user,org,snapshot,pack


def request(context,**kwargs):
    user,org,_,pack=context
    return request_pack_artifact(pack_id=pack.id,organization_id=org.id,actor_id=user.id,using='app_runtime',**kwargs)


@pytest.fixture
def enabled(settings):
    settings.REVIEW_PACK_LIFECYCLE_ENABLED=True
    ReviewLifecycleGate.objects.update_or_create(id=1,defaults={'enabled':True})


def claimed(context):
    _,org,_,_=context
    job=ArtifactRequest.objects.get(organization=org).job
    # Administrative fixture ordering; no production queue mutation authority.
    BackgroundJob.objects.filter(id=job.id).update(priority=-100)
    with transaction.atomic(using='worker_runtime'):
        result=claim_next_job('review-qualification',using='worker_runtime')
    assert result is not None and result.id==job.id
    return result


def handler(tmp_path,storage=None):
    delegate=ReportGenerationHandler(renderer=Renderer(),storage=storage or LocalPrivateReportStorage(tmp_path),using='worker_runtime')
    return ReviewReportGenerationHandler(delegate=delegate,worker_id='review-qualification')


def test_application_and_database_gates_are_independent(pack_context,settings):
    with pytest.raises(ValidationError,match='gate closed'):
        request(pack_context)
    settings.REVIEW_PACK_LIFECYCLE_ENABLED=True
    with pytest.raises(DatabaseError,match='gate closed'):
        request(pack_context)
    assert not ArtifactRequest.objects.exists()
    assert ReviewCycle.objects.get(id=pack_context[3].cycle_id).state=='FROZEN'


def test_request_replay_is_bound_to_explicit_promotion_choice(pack_context,enabled):
    first=request(pack_context,promote_baseline=True)
    assert request(pack_context,promote_baseline=True).id==first.id
    with pytest.raises(DatabaseError,match='replay changed'):
        request(pack_context,promote_baseline=False)
    assert ArtifactRequest.objects.count()==1
    assert ReviewCycle.objects.get(id=pack_context[3].cycle_id).state=='ARTIFACT_PENDING'


@pytest.mark.parametrize('promotion',[False,True])
def test_actual_local_readback_completes_same_frozen_identity(pack_context,enabled,tmp_path,promotion):
    staged=request(pack_context,promote_baseline=promotion)
    pack=pack_context[3]
    job=claimed(pack_context)
    execute_claimed_job(JobExecution(job=job,worker_id='review-qualification'),handler(tmp_path),using='worker_runtime')
    completion=PackCompletion.objects.get(request=staged)
    assert completion.artifact.report_id==staged.report_id
    assert completion.payload['manifest_sha256']==pack.sha256
    assert completion.payload['verification']=='trusted_handler_storage_readback'
    assert completion.payload['baseline_outcome']==('promoted' if promotion else 'not_requested')
    assert BaselineHead.objects.exists()==promotion
    assert ReviewCycle.objects.get(id=pack.cycle_id).state=='COMPLETED'
    assert list(ReservationEvent.objects.order_by('revision').values_list('state',flat=True))==['reserved','consumed']
    pack.refresh_from_db(using='default')
    assert pack.manifest['artifact_state']=='not_created'
    assert pack.manifest['baseline_promotion']=='blocked'
    assert BackgroundJob.objects.get(id=job.id).status=='completed'


def test_corrupt_local_readback_rolls_back_metadata_and_completion_but_keeps_request(pack_context,enabled,tmp_path):
    class CorruptStorage(LocalPrivateReportStorage):
        def get(self,*,key):
            return b'%PDF-1.7\ncorrupted\n%%EOF\n'
    staged=request(pack_context,promote_baseline=True)
    job=claimed(pack_context)
    with pytest.raises(ReportStorageError,match='verification failed'):
        execute_claimed_job(JobExecution(job=job,worker_id='review-qualification'),handler(tmp_path,CorruptStorage(tmp_path)),using='worker_runtime')
    assert not PackCompletion.objects.exists() and not ReportArtifact.objects.exists()
    assert not BaselineHead.objects.exists()
    assert ArtifactRequest.objects.get(id=staged.id).manifest_sha256==pack_context[3].sha256
    assert ReviewCycle.objects.get(id=pack_context[3].cycle_id).state=='ARTIFACT_PENDING'
    assert BackgroundJob.objects.get(id=job.id).status=='running'
    assert ReservationEvent.objects.count()==1
    # A retained matching external object is adopted by an honest retry of
    # exactly this claim/request. No new pack or quota reservation is issued.
    execute_claimed_job(JobExecution(job=job,worker_id='review-qualification'),handler(tmp_path),using='worker_runtime')
    assert PackCompletion.objects.get(request=staged).payload['manifest_sha256']==pack_context[3].sha256
    assert ArtifactRequest.objects.count()==1 and ReservationEvent.objects.count()==2


@pytest.mark.parametrize('revocation',['paid','pause','lease','gate'])
def test_completion_rechecks_current_authority_after_render(pack_context,enabled,tmp_path,revocation):
    user,org,_,pack=pack_context
    request(pack_context,promote_baseline=True)
    job=claimed(pack_context)
    wrapped=handler(tmp_path)
    with tenant_transaction(org.id,using='worker_runtime'):
        prepared=wrapped.prepare(job)
    result=wrapped.execute_external(prepared,lambda:None)
    if revocation=='paid':
        PaidCoverageAuthority.objects.all().delete()
    if revocation=='pause':
        configure_control(organization_id=org.id,actor_id=user.id,mode='paused',reason='local qualification pause',using='app_runtime')
    if revocation=='lease':
        BackgroundJob.objects.filter(id=job.id).update(lock_expires_at=timezone.now()-timedelta(seconds=1))
    if revocation=='gate':
        ReviewLifecycleGate.objects.filter(id=1).update(enabled=False)
    with pytest.raises(DatabaseError):
        with tenant_transaction(org.id,using='worker_runtime'):
            wrapped.persist(job,result)
    assert not PackCompletion.objects.exists() and not ReportArtifact.objects.exists()
    assert not BaselineHead.objects.exists()
    assert ReviewCycle.objects.get(id=pack.cycle_id).state=='ARTIFACT_PENDING'


def test_stale_claim_token_cannot_discover_or_complete_review_request(pack_context,enabled):
    _,org,_,_=pack_context
    request(pack_context)
    job=claimed(pack_context)
    with pytest.raises(DatabaseError,match='lease authority'):
        with tenant_transaction(org.id,using='worker_runtime'):
            with connections['worker_runtime'].cursor() as cursor:
                cursor.execute('SELECT app_private.review_job_target(%s,%s)',[job.id,uuid4()])


def test_completion_replay_does_not_promote_baseline_twice(pack_context,enabled,tmp_path):
    _,org,_,_=pack_context
    staged=request(pack_context,promote_baseline=True)
    job=claimed(pack_context)
    wrapped=handler(tmp_path)
    with tenant_transaction(org.id,using='worker_runtime'):
        prepared=wrapped.prepare(job)
    result=wrapped.execute_external(prepared,lambda:None)
    with tenant_transaction(org.id,using='worker_runtime'):
        first=wrapped.persist(job,result)
        again=wrapped.persist(job,result)
        assert first.id==again.id
    assert PackCompletion.objects.filter(request=staged).count()==1
    assert BaselineHead.objects.get(organization=org).revision==1
    assert ReservationEvent.objects.count()==2


@pytest.mark.parametrize('offset,expected',[(-1,'older_snapshot'),(0,'promoted'),(1,'promoted')])
def test_baseline_advancement_preserves_snapshot_order(pack_context,report_context,enabled,tmp_path,offset,expected):
    user,org,snapshot,firstpack=pack_context
    request(pack_context,promote_baseline=True)
    firstjob=claimed(pack_context)
    execute_claimed_job(JobExecution(job=firstjob,worker_id='review-qualification'),handler(tmp_path),using='worker_runtime')
    next_snapshot=create_assessment_snapshot(organization_id=org.id,created_by_id=user.id,
        assessed_item_id=report_context[3].id,roi_inputs=_roi_inputs(),
        captured_at=snapshot.captured_at+timedelta(days=offset),previous_snapshot=snapshot)
    cycle=open_cycle(organization_id=org.id,actor_id=user.id,input_snapshot_id=next_snapshot.id,using='app_runtime')
    next_pack=freeze_cycle(cycle_id=cycle.id,organization_id=org.id,actor_id=user.id,expected_revision=1,using='app_runtime')
    next_context=(user,org,next_snapshot,next_pack)
    staged=request(next_context,promote_baseline=True)
    BackgroundJob.objects.filter(id=staged.job_id).update(priority=-200)
    next_job=claim_next_job('review-qualification',using='worker_runtime')
    assert next_job.id==staged.job_id
    execute_claimed_job(JobExecution(job=next_job,worker_id='review-qualification'),handler(tmp_path),using='worker_runtime')
    assert PackCompletion.objects.get(request=staged).payload['baseline_outcome']==expected
    head=BaselineHead.objects.get(organization=org)
    assert head.pack_id==(firstpack.id if expected=='older_snapshot' else next_pack.id)
    assert head.revision==(1 if expected=='older_snapshot' else 2)


def test_head_lock_wait_cannot_reuse_pre_expiry_lease(pack_context,report_context,enabled,tmp_path):
    import threading
    import time
    user,org,snapshot,firstpack=pack_context
    request(pack_context,promote_baseline=True)
    firstjob=claimed(pack_context)
    execute_claimed_job(JobExecution(job=firstjob,worker_id='review-qualification'),handler(tmp_path),using='worker_runtime')
    next_snapshot=create_assessment_snapshot(organization_id=org.id,created_by_id=user.id,
        assessed_item_id=report_context[3].id,roi_inputs=_roi_inputs(),
        captured_at=snapshot.captured_at+timedelta(days=1),previous_snapshot=snapshot)
    cycle=open_cycle(organization_id=org.id,actor_id=user.id,input_snapshot_id=next_snapshot.id,using='app_runtime')
    pack=freeze_cycle(cycle_id=cycle.id,organization_id=org.id,actor_id=user.id,expected_revision=1,using='app_runtime')
    staged=request((user,org,next_snapshot,pack),promote_baseline=True)
    BackgroundJob.objects.filter(id=staged.job_id).update(priority=-200)
    job=claim_next_job('review-qualification',using='worker_runtime')
    assert job.id==staged.job_id
    wrapped=handler(tmp_path)
    with tenant_transaction(org.id,using='worker_runtime'):
        prepared=wrapped.prepare(job)
    result=wrapped.execute_external(prepared,lambda:None)
    with connections['default'].cursor() as cursor:
        cursor.execute("UPDATE background_jobs SET lock_expires_at=clock_timestamp()+interval '3 seconds' WHERE id=%s",[job.id])
    outcome=[]
    def attempt():
        try:
            with tenant_transaction(org.id,using='worker_runtime'):
                wrapped.persist(job,result)
            outcome.append('admitted')
        except DatabaseError as error:
            outcome.append('denied' if 'completion authority unavailable' in str(error) else type(error).__name__)
        finally:
            connections['worker_runtime'].close()
    thread=threading.Thread(target=attempt)
    try:
        with transaction.atomic():
            with connections['default'].cursor() as cursor:
                cursor.execute('SELECT revision FROM review_baseline_heads WHERE organization_id=%s FOR UPDATE',[org.id])
                assert cursor.fetchone()[0]==1
            thread.start()
            deadline=time.monotonic()+8
            observed=False
            expired=False
            while time.monotonic()<deadline:
                with connections['default'].cursor() as cursor:
                    # The observer holds a row-lock transaction. Refresh its
                    # statistics snapshot instead of replaying its first view
                    # of pg_stat_activity throughout the barrier wait.
                    cursor.execute('SELECT pg_stat_clear_snapshot()')
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.usename='agentledger_worker' AND position('app_private.complete_review_pack' in a.query)>0 AND l.locktype='transactionid' AND NOT l.granted)")
                    observed=observed or cursor.fetchone()[0]
                    cursor.execute('SELECT clock_timestamp()>lock_expires_at FROM background_jobs WHERE id=%s',[job.id])
                    expired=cursor.fetchone()[0]
                if observed and expired:
                    break
                threading.Event().wait(.02)
            assert observed,f'Actual worker did not reach the head row-lock barrier: {outcome}'
            assert expired,'Database lease did not expire at the observed barrier'
    finally:
        thread.join(timeout=15)
    assert not thread.is_alive() and outcome==['denied']
    assert not PackCompletion.objects.filter(request=staged).exists()
    assert not ReportArtifact.objects.filter(report_id=staged.report_id).exists()
    assert BaselineHead.objects.get(organization=org).pack_id==firstpack.id
    assert ReviewCycle.objects.get(id=pack.cycle_id).state=='ARTIFACT_PENDING'
    assert ReservationEvent.objects.filter(reservation__cycle_id=pack.cycle_id).count()==1


@pytest.mark.parametrize('table',['review_artifact_requests','review_pack_completions','review_baseline_heads'])
def test_lifecycle_worker_has_no_direct_table_access(table):
    with pytest.raises(DatabaseError,match='permission denied'),transaction.atomic(using='worker_runtime'):
        with connections['worker_runtime'].cursor() as cursor:
            cursor.execute(f'SELECT * FROM {table}')


@pytest.mark.parametrize('table',['review_artifact_requests','review_pack_completions','review_baseline_heads'])
def test_lifecycle_app_has_no_raw_write_admission(pack_context,table):
    user,org,_,_=pack_context
    with pytest.raises(DatabaseError,match='permission denied'):
        with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
            with connections['app_runtime'].cursor() as cursor:
                cursor.execute(f'DELETE FROM {table}')


def test_app_cannot_issue_completion(pack_context,enabled):
    user,org,_,_=pack_context
    with pytest.raises(DatabaseError,match='permission denied'):
        with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
            with connections['app_runtime'].cursor() as cursor:
                cursor.execute('SELECT app_private.complete_review_pack(%s,%s,%s,%s,%s)',[uuid4(),uuid4(),uuid4(),'fake',uuid4()])


@pytest.mark.parametrize('bad',[True,False,3.0,'3',None])
def test_request_revision_type_is_exact(pack_context,enabled,bad):
    with pytest.raises(ValidationError):
        request(pack_context,expected_revision=bad)


@pytest.mark.parametrize('bad',[0,1,'true',[],None])
def test_request_promotion_type_is_exact(pack_context,enabled,bad):
    with pytest.raises(ValidationError):
        request(pack_context,promote_baseline=bad)
