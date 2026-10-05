"""Admitted Core knowledge and deliberately configured bounded workflows."""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from apps.organizations.models import Organization
from apps.assessments.models import AssessmentSnapshot


class ImmutableCoreRecord(models.Model):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    organization = models.ForeignKey(Organization,on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self,*args,**kwargs):
        if not self._state.adding: raise ValidationError('Core evidence is immutable')
        super().save(*args,**kwargs)

    def delete(self,*args,**kwargs):
        raise ValidationError('Core evidence is append-only')


class KnownEntity(ImmutableCoreRecord):
    category = models.CharField(max_length=16,choices=[(v,v.replace('_',' ').title()) for v in
        ('services','branches','ai_accounts','agents','employees')])
    label = models.CharField(max_length=200)
    provenance = models.CharField(max_length=16,default='declared',editable=False)
    branch_profile = models.CharField(max_length=32)
    as_of = models.DateTimeField()
    supersedes = models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='successor')
    sha256 = models.CharField(max_length=64)

    class Meta:
        db_table = 'core_known_entities'
        indexes = [models.Index(fields=['organization','category'],name='core_entity_org_category')]


class WorkflowSchedule(ImmutableCoreRecord):
    snapshot = models.ForeignKey(AssessmentSnapshot,on_delete=models.PROTECT)
    snapshot_sha256 = models.CharField(max_length=64)
    interval_hours = models.PositiveSmallIntegerField(choices=[(24,'Daily'),(168,'Weekly'),(720,'Every 30 days')])
    starts_at = models.DateTimeField()
    # Configuration is immutable; changing it creates a successor.
    supersedes = models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='successor')

    class Meta:
        db_table = 'core_workflow_schedules'


class CoreControl(ImmutableCoreRecord):
    mode = models.CharField(max_length=16,choices=[('normal','Allow configured work'),('paused','Pause configured work')])
    reason = models.CharField(max_length=200)
    supersedes = models.OneToOneField('self',null=True,blank=True,on_delete=models.PROTECT,related_name='successor')

    class Meta:
        db_table = 'core_health_controls'


class WorkflowRun(ImmutableCoreRecord):
    operation = models.CharField(max_length=64)
    input_sha256 = models.CharField(max_length=64)
    effective_at = models.DateTimeField()
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)
    schedule = models.ForeignKey(WorkflowSchedule,null=True,blank=True,on_delete=models.PROTECT)

    class Meta:
        db_table = 'core_workflow_runs'
        constraints = [models.UniqueConstraint(fields=['organization','operation','input_sha256'],name='core_run_input_unique')]


class ActionCardRevision(ImmutableCoreRecord):
    snapshot = models.ForeignKey(AssessmentSnapshot,on_delete=models.PROTECT)
    input_sha256 = models.CharField(max_length=64)
    cards = models.JSONField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        db_table = 'core_action_card_revisions'
        constraints = [models.UniqueConstraint(fields=['organization','snapshot'],name='core_card_snapshot_unique')]


class DecisionDeskGate(models.Model):
    """Operator-owned admission switch; no ordinary runtime writes."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = 'core_decision_desk_gate'
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name='core_decision_gate_singleton')]


class DecisionEvent(ImmutableCoreRecord):
    revision = models.ForeignKey(ActionCardRevision, on_delete=models.PROTECT)
    snapshot = models.ForeignKey(AssessmentSnapshot, on_delete=models.PROTECT)
    revision_sha256 = models.CharField(max_length=64)
    snapshot_result_sha256 = models.CharField(max_length=64)
    card_index = models.PositiveIntegerField()
    card_sha256 = models.CharField(max_length=64)
    previous_event = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT, related_name='successor')
    sequence = models.PositiveIntegerField()
    event_kind = models.CharField(max_length=16)
    state = models.CharField(max_length=32)
    responsible_label = models.CharField(max_length=200)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(max_length=4096)
    links = models.JSONField(default=list)
    payload = models.JSONField(editable=False)
    sha256 = models.CharField(max_length=64)

    class Meta:
        db_table = 'core_decision_events'
        constraints = [models.UniqueConstraint(fields=('revision','card_index','sequence'), name='core_decision_sequence_unique')]

    def save(self, *args, **kwargs):
        raise ValidationError('Decision events can only be issued by the decision admission boundary')
