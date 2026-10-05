"""One deterministic entrypoint; Core does not collect fresh provider data.

Receipt UUIDs in this v1 entrypoint resolve exclusively to verified assessment
snapshots. Future Automation adapters must preserve admission, not bypass it.
"""
from datetime import timedelta, UTC
import unicodedata
from uuid import uuid4
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections
from django.utils import timezone
from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.organizations.models import OrganizationMember, WorkflowProfile
from apps.billing.models import Subscription
from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import canonical_sha256, verify_snapshot
from apps.reports.services import create_report
from apps.reports.jobs import ensure_report_generation_job
from .contracts import WorkflowRequest, Operation, BranchProfile, validate_branch_settings, logical_evidence_directory
from .models import BackgroundJob, RecoveryReceipt
from .core_models import KnownEntity, WorkflowSchedule, CoreControl, WorkflowRun, ActionCardRevision
from .receipts import verify_recovery_receipt


def require_owner(organization_id, actor_id, *, using='default',stop_only=False):
    if not OrganizationMember.objects.using(using).filter(organization_id=organization_id,
        user_id=actor_id,role=OrganizationMember.Role.OWNER).exists():
        raise PermissionDenied('Workspace owner authority required')
    if stop_only:
        return None
    subscription=Subscription.objects.using(using).filter(organization_id=organization_id,
        billing_customer__user_id=actor_id).first()
    if subscription is None or not subscription.grants_access:
        raise PermissionDenied('Active Core entitlement required')
    profile=WorkflowProfile.objects.using(using).get(organization_id=organization_id)
    validate_branch_settings(profile.profile,profile.settings)
    return profile


def lock_scope(organization_id,scope,*,using='default'):
    with connections[using].cursor() as c:
        c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',[f'core:{organization_id}:{scope}'])


def entity_payload(entity):
    return {'schema':'stewardence.known_entity.v1','id':str(entity.id),'organization_id':str(entity.organization_id),
        'category':entity.category,'label':entity.label,'provenance':entity.provenance,
        'branch_profile':entity.branch_profile,'as_of':entity.as_of.isoformat(),
        'supersedes':str(entity.supersedes_id) if entity.supersedes_id else None}


def admit_entity(*,organization_id,actor_id,category,label,as_of,supersedes_id=None,using='default'):
    if category not in {'services','branches','ai_accounts','agents','employees'}:
        raise ValidationError('Unregistered entity category')
    if not isinstance(label,str) or not label.strip() or len(label)>200 or any(unicodedata.category(c) in {'Cc','Cf','Cs'} for c in label):
        raise ValidationError('Invalid recorded entity name')
    if timezone.is_naive(as_of) or as_of>timezone.now(): raise ValidationError('Evidence time must be recorded, with timezone')
    as_of=as_of.astimezone(UTC)
    with identity_transaction(actor_id,using=using),tenant_transaction(organization_id,using=using):
        profile=require_owner(organization_id,actor_id,using=using)
        lock_scope(organization_id,'entities',using=using)
        if supersedes_id is not None:
            KnownEntity.objects.using(using).get(id=supersedes_id,organization_id=organization_id,successor__isnull=True,category=category)
        entity=KnownEntity(id=uuid4(),organization_id=organization_id,created_by_id=actor_id,
            category=category,label=label.strip(),as_of=as_of,branch_profile=profile.profile,supersedes_id=supersedes_id)
        entity.sha256=canonical_sha256(entity_payload(entity))
        entity.save(using=using)
        return entity


def configure_control(*,organization_id,actor_id,mode,reason,using='default'):
    if mode not in {'normal','paused'} or not isinstance(reason,str) or not reason.strip() or len(reason)>200:
        raise ValidationError('A supported health mode and review reason are required')
    with identity_transaction(actor_id,using=using),tenant_transaction(organization_id,using=using):
        require_owner(organization_id,actor_id,using=using,stop_only=mode=='paused')
        lock_scope(organization_id,'control',using=using)
        current=CoreControl.objects.using(using).filter(organization_id=organization_id,successor__isnull=True).order_by('-created_at','-id').first()
        return CoreControl.objects.using(using).create(organization_id=organization_id,created_by_id=actor_id,
            mode=mode,reason=reason.strip(),supersedes=current)


def configure_schedule(*,organization_id,actor_id,snapshot_id,interval_hours,starts_at,using='default'):
    if type(interval_hours) is not int or interval_hours not in {24,168,720} or timezone.is_naive(starts_at):
        raise ValidationError('Choose a supported schedule with timezone')
    if starts_at < timezone.now()-timedelta(minutes=5) or starts_at > timezone.now()+timedelta(days=366):
        raise ValidationError('Schedule start must be within the next year')
    with identity_transaction(actor_id,using=using),tenant_transaction(organization_id,using=using):
        require_owner(organization_id,actor_id,using=using)
        lock_scope(organization_id,'schedules',using=using)
        if WorkflowSchedule.objects.using(using).filter(organization_id=organization_id,successor__isnull=True).count()>=10:
            raise ValidationError('Core schedule limit reached')
        snapshot=AssessmentSnapshot.objects.using(using).get(id=snapshot_id,organization_id=organization_id)
        if not verify_snapshot(snapshot): raise ValidationError('Snapshot integrity failed')
        return WorkflowSchedule.objects.using(using).create(organization_id=organization_id,created_by_id=actor_id,
            snapshot=snapshot,snapshot_sha256=snapshot.result_sha256,interval_hours=interval_hours,starts_at=starts_at)


def recorded_health(organization_id,*,using='default'):
    receipts=list(RecoveryReceipt.objects.using(using).select_related('job').filter(organization_id=organization_id).order_by('-created_at','-id')[:50])
    valid=all(verify_recovery_receipt(r) for r in receipts)
    held=BackgroundJob.objects.using(using).filter(organization_id=organization_id,status='failed').count()
    control=CoreControl.objects.using(using).filter(organization_id=organization_id,successor__isnull=True).order_by('-created_at','-id').first()
    return {'receipt_integrity':valid,'checked_recent_receipts':len(receipts),'review_holds':held,
        'owner_mode':control.mode if control else 'normal','circuit':'closed' if valid else 'blocked',
        'scope':'Recorded workflow state; not a live service or provider probe'}


def dispatch(request:WorkflowRequest,*,actor_id,schedule_id=None,using='default'):
    if not isinstance(request,WorkflowRequest): raise ValidationError('Versioned workflow request required')
    if request.effective_at>timezone.now(): raise ValidationError('Future dispatch is not admitted')
    with identity_transaction(actor_id,using=using),tenant_transaction(request.organization_id,using=using):
        profile=require_owner(request.organization_id,actor_id,using=using)
        lock_scope(request.organization_id,'control',using=using)
        if request.branch_profile.value!=profile.profile: raise ValidationError('Workflow profile mismatch')
        lock_scope(request.organization_id,request.input_sha256,using=using)
        existing=WorkflowRun.objects.using(using).filter(organization_id=request.organization_id,
            operation=request.operation.value,input_sha256=request.input_sha256).first()
        if existing:
            if canonical_sha256(existing.payload)!=existing.sha256 or existing.payload.get('request')!=request.envelope():
                raise ValidationError('Workflow receipt integrity failed')
            if existing.schedule_id!=schedule_id:
                raise ValidationError('Workflow schedule replay attribution changed')
        health=recorded_health(request.organization_id,using=using)
        if not health['receipt_integrity']: raise ValidationError('Recovery receipt integrity failed; configured work blocked')
        if request.operation!=Operation.HEALTH and health['owner_mode']=='paused':
            raise PermissionDenied('Configured Core work is paused by its owner')
        snapshots=list(AssessmentSnapshot.objects.using(using).filter(organization_id=request.organization_id,id__in=request.receipt_ids))
        if len(snapshots)!=len(request.receipt_ids) or any(not verify_snapshot(s) for s in snapshots):
            raise ValidationError('Receipt selection is unresolved or corrupt')
        if request.operation!=Operation.HEALTH and len(snapshots)!=1: raise ValidationError('Core v1 requires one admitted assessment receipt')
        if schedule_id is not None:
            schedule=WorkflowSchedule.objects.using(using).get(id=schedule_id,organization_id=request.organization_id,
                created_by_id=actor_id,successor__isnull=True)
            if request.operation!=Operation.REPORT or len(snapshots)!=1 or schedule.snapshot_id!=snapshots[0].id:
                raise ValidationError('Schedule does not authorize this operation or receipt')
            interval=timedelta(hours=schedule.interval_hours)
            if request.effective_at<schedule.starts_at or (request.effective_at-schedule.starts_at)%interval!=timedelta(0):
                raise ValidationError('Dispatch does not match a configured slot')
            if existing is None and WorkflowRun.objects.using(using).filter(schedule_id=schedule_id,effective_at__gt=request.effective_at).exists():
                raise ValidationError('Historical schedule backfill is not admitted')
        if existing:
            validate_run_effects(existing,request,snapshots,using=using)
            return existing
        result={'schema':'stewardence.workflow_receipt.v1','request':request.envelope(),'authority':'proposal_only'}
        if request.operation==Operation.HEALTH:
            result['recorded_health']=health
        if request.operation==Operation.REPORT:
            report=create_report(organization_id=request.organization_id,assessment_snapshot_id=snapshots[0].id,created_by_id=actor_id,using=using)
            job=ensure_report_generation_job(report=report,using=using)
            result.update(report_id=str(report.id),job_id=str(job.id) if job else None,
                state=job.status if job else 'artifact_metadata_present')
        if request.operation==Operation.REASSESS:
            snapshot=snapshots[0]
            cards=[]
            for item in snapshot.result_payload['inventory_results']:
                for policy in item['policy_results']:
                    if policy['result']=='FAIL':
                        cards.append({'inventory_item_id':item['inventory_item_id'],'rule_id':policy['rule_id'],
                            'rule_version':policy['rule_version'],'severity':policy['severity'],
                            'proposal':policy['recommended_remediation'],'authority':'proposal_only'})
            cards.sort(key=lambda c:(c['inventory_item_id'],c['rule_id'],str(c['rule_version'])))
            with connections[using].cursor() as c:
                c.execute('SELECT app_private.issue_action_cards(%s,%s,%s,%s)',
                    [uuid4(),request.organization_id,actor_id,snapshot.id])
                revision_id=c.fetchone()[0]
            revision=ActionCardRevision.objects.using(using).get(id=revision_id,organization_id=request.organization_id)
            if revision.cards!=cards or revision.sha256!=canonical_sha256(cards): raise ValidationError('Action-card revision integrity failed')
            result.update(revision_id=str(revision.id),proposal_count=len(cards),state='reassessed')
        import json,rfc8785
        run_id=uuid4()
        with connections[using].cursor() as c:
            c.execute('SELECT app_private.issue_workflow_run(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)',
                [run_id,request.organization_id,actor_id,request.operation.value,request.input_sha256,
                 request.effective_at,json.dumps(result),rfc8785.dumps(result).decode(),canonical_sha256(result),schedule_id])
        return WorkflowRun.objects.using(using).get(id=run_id)


def validate_run_effects(run,request,snapshots,*,using):
    from apps.reports.models import Report,ReportArtifact
    if request.operation==Operation.REPORT:
        report=Report.objects.using(using).get(id=run.payload['report_id'],organization_id=request.organization_id,
            assessment_snapshot_id=snapshots[0].id)
        job_id=run.payload.get('job_id')
        if job_id:
            BackgroundJob.objects.using(using).get(id=job_id,organization_id=request.organization_id,
                job_type='report_generation',payload={'report_id':str(report.id)})
        elif not ReportArtifact.objects.using(using).filter(report_id=report.id,organization_id=request.organization_id).exists():
            raise ValidationError('Workflow report artifact is unresolved')
    if request.operation==Operation.REASSESS:
        revision=ActionCardRevision.objects.using(using).get(id=run.payload['revision_id'],
            organization_id=request.organization_id,snapshot_id=snapshots[0].id)
        if canonical_sha256(revision.cards)!=revision.sha256 or len(revision.cards)!=run.payload['proposal_count']:
            raise ValidationError('Workflow revision binding is invalid')


def substantial_signal(previous,current):
    def risks(snapshot):
        return {r['inventory_item_id']:r for r in snapshot.result_payload['inventory_results']}
    old=risks(previous); new=risks(current)
    if set(old)!=set(new): return True
    for item_id,row in new.items():
        prior=old[item_id]
        if abs(row['risk']['score']-prior['risk']['score'])>=10 or row['risk']['band']!=prior['risk']['band']: return True
        high=lambda item:{(p['rule_id'],str(p['rule_version'])) for p in item['policy_results']
            if p['result']=='FAIL' and p['severity'] in {'HIGH','CRITICAL'}}
        if high(row)!=high(prior): return True
    return False


def tick(*,organization_id,actor_id,now=None,using='default'):
    now=now or timezone.now()
    if timezone.is_naive(now) or now>timezone.now()+timedelta(seconds=1): raise ValidationError('Tick time must be recorded, with timezone')
    with identity_transaction(actor_id,using=using),tenant_transaction(organization_id,using=using):
        profile=require_owner(organization_id,actor_id,using=using)
        lock_scope(organization_id,'tick',using=using)
        lock_scope(organization_id,'control',using=using)
        health=recorded_health(organization_id,using=using)
        if not health['receipt_integrity'] or health['owner_mode']=='paused': return {'state':'blocked','health':health,'runs':[]}
        runs=[]
        for schedule in WorkflowSchedule.objects.using(using).filter(organization_id=organization_id,successor__isnull=True,starts_at__lte=now).order_by('starts_at','id')[:10]:
            if schedule.created_by_id!=actor_id: continue
            # Coalesce missed slots; never replay an unbounded backlog.
            delta=timedelta(hours=schedule.interval_hours)
            slot=schedule.starts_at+delta*((now-schedule.starts_at)//delta)
            if schedule.snapshot.result_sha256!=schedule.snapshot_sha256: raise ValidationError('Scheduled receipt binding changed')
            runs.append(dispatch(WorkflowRequest(organization_id,Operation.REPORT,(schedule.snapshot_id,),slot,BranchProfile(profile.profile)),
                actor_id=actor_id,schedule_id=schedule.id,using=using))
        latest=AssessmentSnapshot.objects.using(using).filter(organization_id=organization_id,captured_at__lte=now).order_by('-captured_at','-created_at','-id').first()
        previous=ActionCardRevision.objects.using(using).filter(organization_id=organization_id).select_related('snapshot').order_by('-created_at','-id').first()
        if latest and (previous is None or (previous.snapshot_id!=latest.id and substantial_signal(previous.snapshot,latest))):
            runs.append(dispatch(WorkflowRequest(organization_id,Operation.REASSESS,(latest.id,),latest.captured_at,BranchProfile(profile.profile)),actor_id=actor_id,using=using))
        return {'state':'processed','runs':[str(run.id) for run in runs]}


def normalized_entities(organization_id,*,now=None,using='default'):
    now=now or timezone.now()
    entities=list(KnownEntity.objects.using(using).filter(organization_id=organization_id,successor__isnull=True).order_by('category','label','id')[:500])
    normalized=[]
    for e in entities:
        if canonical_sha256(entity_payload(e))!=e.sha256: raise ValidationError('Recorded entity integrity failed')
        normalized.append({'id':e.id,'label':e.label,'category':e.category,'provenance':e.provenance,'as_of':e.as_of,
            'freshness':'recent' if now-e.as_of<=timedelta(days=30) else 'stale',
            'directory':logical_evidence_directory(e.organization_id,e.category,e.id)})
    return normalized
