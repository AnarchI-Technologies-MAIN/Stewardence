"""Append-only decision admission on exact issued ActionCardRevision identities."""
import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = r"""
ALTER TABLE core_decision_desk_gate OWNER TO agentledger_owner;
ALTER TABLE core_decision_events OWNER TO agentledger_owner;
REVOKE ALL ON core_decision_desk_gate,core_decision_events FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE core_decision_desk_gate ENABLE ROW LEVEL SECURITY;
ALTER TABLE core_decision_desk_gate FORCE ROW LEVEL SECURITY;
ALTER TABLE core_decision_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE core_decision_events FORCE ROW LEVEL SECURITY;
CREATE POLICY decision_gate_owner ON core_decision_desk_gate TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY decision_owner ON core_decision_events TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY decision_tenant_read ON core_decision_events FOR SELECT TO agentledger_app
 USING(organization_id=app_private.current_organization_id() AND EXISTS(
 SELECT 1 FROM public.organizations_organizationmember m WHERE m.organization_id=core_decision_events.organization_id
 AND m.user_id=app_private.current_user_id() AND m.role='owner'));
GRANT SELECT ON core_decision_events TO agentledger_app;
INSERT INTO core_decision_desk_gate(id,enabled) VALUES(1,false);
CREATE TRIGGER immutable_core_decision BEFORE UPDATE OR DELETE ON core_decision_events
 FOR EACH ROW EXECUTE FUNCTION app_private.prevent_paid_coverage_mutation();

CREATE FUNCTION app_private.issue_core_decision(org uuid,actor uuid,e jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE r public.core_action_card_revisions%ROWTYPE; s public.assessment_snapshots%ROWTYPE;
 prior public.core_decision_events%ROWTYPE; previous uuid; rid uuid; idx integer; seq integer;
 event_id uuid:=gen_random_uuid(); issued timestamptz; card_hash text; due date; body jsonb;
 required text[]:=ARRAY['schema','revision_id','card_index','expected_previous_event','event_kind','state',
 'responsible_label','due_date','notes','links']; key text; link jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Decision admission requires read committed'; END IF;
 IF org IS NULL OR actor IS NULL OR jsonb_typeof(e) IS DISTINCT FROM 'object' OR octet_length(e::text)>65536
  OR NOT e ?& required OR EXISTS(SELECT 1 FROM jsonb_object_keys(e) k WHERE NOT k=ANY(required)) THEN
  RAISE EXCEPTION 'Invalid decision envelope'; END IF;
 IF session_user='agentledger_app' AND (org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id()) THEN RAISE EXCEPTION 'Decision identity mismatch'; END IF;
 FOREACH key IN ARRAY ARRAY['schema','revision_id','event_kind','state','responsible_label','notes'] LOOP
  IF jsonb_typeof(e->key) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'Decision fields must be strings'; END IF;
 END LOOP;
 IF e->>'schema'<>'stewardence.core_decision.v1' OR jsonb_typeof(e->'card_index')<>'number'
  OR e->>'card_index' !~ '^[0-9]{1,9}$' OR length(btrim(e->>'responsible_label')) NOT BETWEEN 1 AND 200
  OR e->>'responsible_label' ~ '[[:cntrl:]]' OR length(e->>'notes')>4096
  OR jsonb_typeof(e->'links') IS DISTINCT FROM 'array' OR jsonb_array_length(e->'links')>10 THEN
  RAISE EXCEPTION 'Invalid decision bounds'; END IF;
 IF NOT ((e->>'event_kind'='disposition' AND e->>'state' IN ('act','defer','decline','accept_risk'))
  OR (e->>'event_kind'='execution' AND e->>'state' IN ('completion_recorded','evidence_reviewed'))) THEN
  RAISE EXCEPTION 'Unsupported decision state'; END IF;
 FOREACH key IN ARRAY ARRAY['expected_previous_event','due_date'] LOOP
  IF jsonb_typeof(e->key) NOT IN ('null','string') THEN RAISE EXCEPTION 'Invalid optional decision field'; END IF;
 END LOOP;
 IF e->>'due_date' IS NOT NULL THEN
  IF e->>'due_date' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' THEN RAISE EXCEPTION 'Invalid due date'; END IF;
  due:=(e->>'due_date')::date;
 END IF;
 FOR link IN SELECT value FROM jsonb_array_elements(e->'links') LOOP
  IF jsonb_typeof(link)<>'string' OR length(link#>>'{}')>2048
   OR link#>>'{}' !~ '^https://[^[:space:]/?#@]+([/?#][^[:space:]]*)?$' THEN RAISE EXCEPTION 'Invalid evidence link'; END IF;
 END LOOP;
 rid:=(e->>'revision_id')::uuid; idx:=(e->>'card_index')::integer;
 previous:=(e->>'expected_previous_event')::uuid;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':decision:'||rid::text||':'||idx::text,0));
 IF NOT EXISTS(SELECT 1 FROM public.core_decision_desk_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Decision admission unavailable'; END IF;
 SELECT * INTO r FROM public.core_action_card_revisions WHERE id=rid AND organization_id=org;
 IF NOT FOUND OR jsonb_typeof(r.cards)<>'array' OR idx>=jsonb_array_length(r.cards)
  OR r.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(r.cards),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Decision revision unresolved'; END IF;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=r.snapshot_id AND organization_id=org;
 IF NOT FOUND OR r.input_sha256 IS DISTINCT FROM s.result_sha256 THEN RAISE EXCEPTION 'Decision snapshot mismatch'; END IF;
 card_hash:=encode(sha256(convert_to(app_private.queue_canonical(r.cards->idx),'UTF8')),'hex');
 SELECT * INTO prior FROM public.core_decision_events WHERE revision_id=rid AND card_index=idx
  ORDER BY sequence DESC LIMIT 1;
 IF (FOUND AND previous IS DISTINCT FROM prior.id) OR (NOT FOUND AND previous IS NOT NULL) THEN
  RAISE EXCEPTION 'Stale decision history'; END IF;
 seq:=coalesce(prior.sequence,0)+1; issued:=clock_timestamp();
 body:=jsonb_build_object('schema','stewardence.core_decision_event.v1','id',event_id,'organization_id',org,
  'created_by_id',actor,'created_at',issued,'revision_id',rid,'revision_sha256',r.sha256,
  'snapshot_id',s.id,'snapshot_result_sha256',s.result_sha256,'card_index',idx,'card_sha256',card_hash,
  'previous_event_id',previous,'sequence',seq,'event_kind',e->>'event_kind','state',e->>'state',
  'responsible_label',btrim(e->>'responsible_label'),'due_date',due,'notes',e->>'notes','links',e->'links',
  'owner_statement_only',true,'resolution_verified',false);
 INSERT INTO public.core_decision_events(id,organization_id,created_by_id,created_at,revision_id,snapshot_id,
  revision_sha256,snapshot_result_sha256,card_index,card_sha256,previous_event_id,sequence,event_kind,state,
  responsible_label,due_date,notes,links,payload,sha256)
 VALUES(event_id,org,actor,issued,rid,s.id,r.sha256,s.result_sha256,idx,card_hash,previous,seq,e->>'event_kind',
  e->>'state',btrim(e->>'responsible_label'),due,e->>'notes',e->'links',body,
  encode(sha256(convert_to(app_private.queue_canonical(body),'UTF8')),'hex'));
 RETURN event_id;
END;$fn$;
ALTER FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb) TO agentledger_app;

CREATE FUNCTION app_private.selected_core_decisions(snapshot uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE selected jsonb;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.core_decision_desk_gate WHERE id=1 AND enabled) THEN RETURN '[]'::jsonb; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('event_id',d.id,'event_sha256',d.sha256,'revision_id',r.id,
  'revision_sha256',r.sha256,'card_index',d.card_index,'card_sha256',d.card_sha256,'snapshot_id',snapshot,
  'snapshot_result_sha256',s.result_sha256,'event_kind',d.event_kind,'state',d.state,
  'owner_statement_only',true,'resolution_verified',false) ORDER BY d.card_index),'[]'::jsonb) INTO selected
 FROM public.core_decision_events d JOIN public.core_action_card_revisions r ON r.id=d.revision_id
 JOIN public.assessment_snapshots s ON s.id=r.snapshot_id
 WHERE s.id=snapshot AND s.organization_id=org AND d.organization_id=org
  AND r.organization_id=org AND r.input_sha256=s.result_sha256
  AND r.sha256=encode(sha256(convert_to(app_private.queue_canonical(r.cards),'UTF8')),'hex')
  AND d.revision_sha256=r.sha256 AND d.snapshot_id=s.id AND d.snapshot_result_sha256=s.result_sha256
  AND d.card_sha256=encode(sha256(convert_to(app_private.queue_canonical(r.cards->d.card_index),'UTF8')),'hex')
  AND d.sha256=encode(sha256(convert_to(app_private.queue_canonical(d.payload),'UTF8')),'hex')
  AND NOT EXISTS(SELECT 1 FROM public.core_decision_events later WHERE later.revision_id=d.revision_id
   AND later.card_index=d.card_index AND later.sequence>d.sequence);
 RETURN selected;
END;$fn$;
ALTER FUNCTION app_private.selected_core_decisions(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.selected_core_decisions(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
"""


class Migration(migrations.Migration):
    dependencies=[('jobs','0013_paid_entitlement'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.CreateModel(name='DecisionDeskGate',fields=[('id',models.PositiveSmallIntegerField(default=1,editable=False,primary_key=True,serialize=False)),('enabled',models.BooleanField(default=False))],
            options={'db_table':'core_decision_desk_gate','constraints':[models.CheckConstraint(condition=models.Q(id=1),name='core_decision_gate_singleton')]}),
        migrations.CreateModel(name='DecisionEvent',fields=[
            ('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),('created_at',models.DateTimeField(auto_now_add=True)),
            ('organization',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='organizations.organization')),
            ('created_by',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
            ('revision',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='jobs.actioncardrevision')),
            ('snapshot',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='assessments.assessmentsnapshot')),
            *[(name,models.CharField(max_length=64)) for name in ('revision_sha256','snapshot_result_sha256','card_sha256','sha256')],
            ('card_index',models.PositiveIntegerField()),('sequence',models.PositiveIntegerField()),
            ('previous_event',models.OneToOneField(null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,related_name='successor',to='jobs.decisionevent')),
            ('event_kind',models.CharField(max_length=16)),('state',models.CharField(max_length=32)),('responsible_label',models.CharField(max_length=200)),
            ('due_date',models.DateField(null=True,blank=True)),('notes',models.TextField(max_length=4096)),('links',models.JSONField(default=list)),('payload',models.JSONField(editable=False)),
        ],options={'db_table':'core_decision_events','constraints':[models.UniqueConstraint(fields=('revision','card_index','sequence'),name='core_decision_sequence_unique')]}),
        migrations.RunSQL(SQL),
    ]
