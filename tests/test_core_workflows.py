from datetime import timedelta,UTC,datetime
from uuid import uuid4
import pytest
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import DatabaseError,transaction
from django.utils import timezone
from django.urls import reverse
from agentledger.tenancy.context import tenant_transaction
from apps.jobs.contracts import WorkflowRequest,Operation,BranchProfile
from apps.jobs.core_models import KnownEntity,WorkflowSchedule,WorkflowRun,ActionCardRevision
from apps.jobs.core_workflows import admit_entity,configure_control,configure_schedule,dispatch,tick,normalized_entities
from apps.jobs.models import BackgroundJob
from apps.organizations.models import WorkflowProfile,Organization,OrganizationMember
from apps.billing.models import Subscription

pytestmark=pytest.mark.django_db(transaction=True,databases='__all__')


@pytest.fixture
def core_context(report_context):
    user,org,member,item,snapshot=report_context
    WorkflowProfile.objects.create(organization=org,created_by=user,profile='business.v1',settings={'name':'Main branch'})
    return report_context


def test_recorded_entity_hash_normalization_and_role_boundaries(core_context):
    user,org,_,_,_=core_context
    entity=admit_entity(organization_id=org.id,actor_id=user.id,category='employees',label='Declared employee account',
        as_of=timezone.now()-timedelta(days=40),using='app_runtime')
    with tenant_transaction(org.id,using='app_runtime'):
        rows=normalized_entities(org.id,using='app_runtime')
    assert rows[0]['freshness']=='stale' and rows[0]['provenance']=='declared'
    assert f'organizations/{org.id}/evidence/employees/{entity.id}'==rows[0]['directory']
    other=Organization.objects.create(name='Other tenant')
    with tenant_transaction(other.id,using='worker_runtime'):
        assert not KnownEntity.objects.using('worker_runtime').filter(pk=entity.id).exists()
    with pytest.raises(DatabaseError),transaction.atomic():
        KnownEntity.objects.filter(pk=entity.id).update(label='Changed history')
    with pytest.raises(ValidationError):
        admit_entity(organization_id=org.id,actor_id=user.id,category='employees',label='future',as_of=timezone.now()+timedelta(days=1))


def test_snapshot_receipt_resolution_and_profile_are_authoritative(core_context):
    user,org,_,_,snapshot=core_context
    with pytest.raises(ValidationError):
        dispatch(WorkflowRequest(org.id,Operation.REPORT,(uuid4(),),timezone.now(),BranchProfile.BUSINESS),actor_id=user.id)
    with pytest.raises(ValidationError):
        dispatch(WorkflowRequest(org.id,Operation.REPORT,(snapshot.id,),timezone.now(),BranchProfile.DEVELOPMENT),actor_id=user.id)
    assert not WorkflowRun.objects.exists()


def test_owner_health_pause_blocks_tick_and_manual_dispatch(core_context):
    user,org,_,_,snapshot=core_context
    configure_control(organization_id=org.id,actor_id=user.id,mode='paused',reason='Owner review')
    assert tick(organization_id=org.id,actor_id=user.id)['state']=='blocked'
    with pytest.raises(PermissionDenied):
        dispatch(WorkflowRequest(org.id,Operation.REPORT,(snapshot.id,),timezone.now(),BranchProfile.BUSINESS),actor_id=user.id)
    assert not WorkflowRun.objects.exists()
    configure_control(organization_id=org.id,actor_id=user.id,mode='normal',reason='Reviewed configuration')
    assert tick(organization_id=org.id,actor_id=user.id)['state']=='processed'
    assert ActionCardRevision.objects.count()==1


def test_client_schedule_tick_is_idempotent_and_does_not_collect_providers(core_context):
    user,org,_,_,snapshot=core_context
    start=timezone.now()-timedelta(seconds=1)
    schedule=configure_schedule(organization_id=org.id,actor_id=user.id,snapshot_id=snapshot.id,interval_hours=24,starts_at=start)
    first=tick(organization_id=org.id,actor_id=user.id)
    second=tick(organization_id=org.id,actor_id=user.id)
    assert first['state']==second['state']=='processed'
    assert WorkflowRun.objects.filter(schedule=schedule).count()==1
    assert BackgroundJob.objects.filter(job_type='report_generation').count()==1
    assert ActionCardRevision.objects.count()==1
    revision=ActionCardRevision.objects.get()
    assert all(c['authority']=='proposal_only' for c in revision.cards)
    assert not BackgroundJob.objects.exclude(job_type__in=['report_generation','audit_batch_seal']).exists()


def test_removed_entitlement_and_nonowner_fail_closed(core_context):
    user,org,member,_,_=core_context
    Subscription.objects.filter(organization=org).update(status='canceled')
    with pytest.raises(PermissionDenied): tick(organization_id=org.id,actor_id=user.id)
    Subscription.objects.filter(organization=org).update(status='active')
    member.role=OrganizationMember.Role.VIEWER
    member.save()
    with pytest.raises(PermissionDenied): tick(organization_id=org.id,actor_id=user.id)
    assert not WorkflowRun.objects.exists()


def test_core_workspace_private_and_forbids_cross_tenant_snapshot(client,core_context):
    user,org,_,_,_=core_context
    response=client.get(reverse('core-workspace'))
    assert response.status_code==200 and response['Cache-Control']=='private, no-store'
    assert b'Coverage unknown' in response.content
    assert b'No live listeners' in response.content
    response=client.post(reverse('core-workspace'),{'action':'schedule','snapshot':str(uuid4()),'interval_hours':'24','starts_at':'2026-10-03T23:00'})
    assert response.status_code==200 and not WorkflowSchedule.objects.exists()


def test_run_core_tick_disabled_by_default(core_context):
    from django.core.management import call_command
    from django.core.management.base import CommandError
    user,org,_,_,_=core_context
    with pytest.raises(CommandError,match='disabled'):
        call_command('run_core_tick',organization_id=org.id,actor_id=user.id)


def test_owner_pause_blocks_queued_claim_and_running_persistence(core_context):
    from apps.jobs.queue import claim_next_job,lock_job_for_persistence,LostJobLease
    user,org,_,_,snapshot=core_context
    dispatch(WorkflowRequest(org.id,Operation.REPORT,(snapshot.id,),timezone.now(),BranchProfile.BUSINESS),actor_id=user.id)
    BackgroundJob.objects.filter(organization=org,job_type='report_generation').update(priority=-100)
    configure_control(organization_id=org.id,actor_id=user.id,mode='paused',reason='Owner pause')
    claimed=claim_next_job('pause-worker',using='worker_runtime')
    assert claimed is None or claimed.job_type=='audit_batch_seal'
    if claimed:
        from apps.jobs.queue import complete_job_with_fence
        complete_job_with_fence(job_id=claimed.id,worker_id='pause-worker',claim_token=claimed.claim_token,using='worker_runtime')
    configure_control(organization_id=org.id,actor_id=user.id,mode='normal',reason='Owner resumes')
    claimed=claim_next_job('pause-worker',using='worker_runtime')
    assert claimed is not None
    assert claimed.job_type=='report_generation'
    configure_control(organization_id=org.id,actor_id=user.id,mode='paused',reason='Pause during processing')
    with pytest.raises(LostJobLease),transaction.atomic(using='worker_runtime'):
        lock_job_for_persistence(job_id=claimed.id,worker_id='pause-worker',claim_token=claimed.claim_token,using='worker_runtime')
    assert not WorkflowRun.objects.filter(operation='core.health_check').exists()


def test_database_rejects_schedule_poisoning(core_context):
    from agentledger.tenancy.context import identity_transaction
    user,org,_,_,snapshot=core_context
    with pytest.raises(DatabaseError),identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
        WorkflowSchedule.objects.using('app_runtime').create(organization=org,created_by=user,snapshot=snapshot,
            snapshot_sha256=snapshot.result_sha256,interval_hours=0,starts_at=timezone.now())
    assert not WorkflowSchedule.objects.exists()
