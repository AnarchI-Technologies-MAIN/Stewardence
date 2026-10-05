from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError, ObjectDoesNotExist
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from apps.organizations.models import OrganizationMember,WorkflowProfile
from apps.assessments.models import AssessmentSnapshot
from apps.inventory.models import InventoryItem
from .core_models import KnownEntity,WorkflowSchedule,CoreControl,WorkflowRun,ActionCardRevision
from .core_workflows import admit_entity,configure_schedule,configure_control,tick,normalized_entities,recorded_health


class EntityForm(forms.Form):
    category=forms.ChoiceField(choices=KnownEntity._meta.get_field('category').choices)
    label=forms.CharField(max_length=200,label='Recorded name')
    as_of=forms.DateTimeField(label='Evidence as of (UTC)',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))


class ScheduleForm(forms.Form):
    snapshot=forms.ModelChoiceField(queryset=AssessmentSnapshot.objects.none(),label='Assessment receipt')
    interval_hours=forms.TypedChoiceField(coerce=int,choices=WorkflowSchedule._meta.get_field('interval_hours').choices)
    starts_at=forms.DateTimeField(label='First scheduled slot (UTC)',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))


class ControlForm(forms.Form):
    mode=forms.ChoiceField(choices=CoreControl._meta.get_field('mode').choices)
    reason=forms.CharField(max_length=200,label='Reason for this control decision')


@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def core_workspace(request):
    org=getattr(request,'organization_id',None)
    if org is None: raise Http404('Choose a firm first')
    member=get_object_or_404(OrganizationMember,organization_id=org,user_id=request.user.id)
    owner=member.role==OrganizationMember.Role.OWNER
    if request.method=='POST' and not owner: raise PermissionDenied('Workspace owner required')
    profile=WorkflowProfile.objects.filter(organization_id=org).first()
    if profile is None: return redirect('organizations:workflow-profile')
    action=request.POST.get('action','')
    entity_form=EntityForm(request.POST if action=='entity' else None,initial={'as_of':timezone.now()})
    schedule_form=ScheduleForm(request.POST if action=='schedule' else None)
    schedule_form.fields['snapshot'].queryset=AssessmentSnapshot.objects.filter(organization_id=org).order_by('-captured_at','-id')
    control_form=ControlForm(request.POST if action=='control' else None)
    error=None
    if request.method=='POST':
        try:
            if action=='entity' and entity_form.is_valid():
                admit_entity(organization_id=org,actor_id=request.user.id,**entity_form.cleaned_data)
                return redirect('core-workspace')
            if action=='schedule' and schedule_form.is_valid():
                data=schedule_form.cleaned_data
                configure_schedule(organization_id=org,actor_id=request.user.id,snapshot_id=data['snapshot'].id,
                    interval_hours=data['interval_hours'],starts_at=data['starts_at'])
                return redirect('core-workspace')
            if action=='control' and control_form.is_valid():
                configure_control(organization_id=org,actor_id=request.user.id,**control_form.cleaned_data)
                return redirect('core-workspace')
            if action=='tick':
                tick(organization_id=org,actor_id=request.user.id)
                return redirect('core-workspace')
            if action not in {'entity','schedule','control','tick'}: raise ValidationError('Unsupported workflow action')
        except (ValidationError,ObjectDoesNotExist):
            error='The request could not be admitted. Verify its recorded time, selected receipt and configuration.'
    try:
        entities=normalized_entities(org)
        health=recorded_health(org)
        if not health['receipt_integrity']: raise ValidationError('Recovery receipt integrity failed')
        revisions=list(ActionCardRevision.objects.filter(organization_id=org).select_related('snapshot').order_by('-created_at','-id')[:1])
        from apps.assessments.snapshots import canonical_sha256,verify_snapshot
        if any(canonical_sha256(r.cards)!=r.sha256 or r.input_sha256!=r.snapshot.result_sha256 or not verify_snapshot(r.snapshot) for r in revisions):
            raise ValidationError('Action card integrity failed')
        runs=list(WorkflowRun.objects.filter(organization_id=org).order_by('-created_at','-id')[:25])
        if any(canonical_sha256(r.payload)!=r.sha256 or canonical_sha256(r.payload.get('request'))!=r.input_sha256
            or r.payload.get('request',{}).get('organization_id')!=str(org) for r in runs):
            raise ValidationError('Workflow receipt integrity failed')
    except ValidationError:
        response=render(request,'jobs/core_workspace.html',{'integrity_failed':True},status=503)
        response['Cache-Control']='private, no-store'
        return response
    response=render(request,'jobs/core_workspace.html',{'owner':owner,'profile':profile,'entities':entities,
        'inventory_records':InventoryItem.objects.filter(organization_id=org,archived_at__isnull=True).count(),
        'entity_counts':{category:sum(row['category']==category for row in entities) for category in ('services','branches','ai_accounts','agents','employees')},
        'health':health,'revisions':revisions,'runs':runs,'schedules':WorkflowSchedule.objects.filter(organization_id=org,successor__isnull=True).order_by('starts_at','id')[:10],
        'entity_form':entity_form,'schedule_form':schedule_form,'control_form':control_form,'error':error,'as_of':timezone.now()})
    response['Cache-Control']='private, no-store'
    return response


@login_required
@require_http_methods(['POST'])
def pause_core(request):
    org=getattr(request,'organization_id',None)
    if org is None: raise Http404('Choose a firm first')
    configure_control(organization_id=org,actor_id=request.user.id,mode='paused',reason='Owner requested stop')
    from django.http import HttpResponse
    response=HttpResponse('Configured Core work is paused. Billing status does not remove owner stop authority.',content_type='text/plain')
    response['Cache-Control']='private, no-store'
    return response
