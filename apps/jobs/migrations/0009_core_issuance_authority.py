"""Database participation in controls and qualified workflow issuance."""
from django.db import migrations

SQL=r"""
CREATE OR REPLACE FUNCTION app_private.core_work_allowed(org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_subscription s
  JOIN public.billing_billingcustomer c ON c.id=s.billing_customer_id
  JOIN public.organizations_organizationmember m ON m.organization_id=s.organization_id AND m.user_id=c.user_id AND m.role='owner'
  WHERE s.organization_id=org AND s.status IN ('active','canceling'))
 AND NOT EXISTS(SELECT 1 FROM public.core_health_controls h WHERE organization_id=org AND mode='paused'
  AND NOT EXISTS(SELECT 1 FROM public.core_health_controls successor WHERE successor.supersedes_id=h.id))
 AND NOT EXISTS(SELECT 1 FROM (SELECT payload,sha256 FROM public.job_recovery_receipts
  WHERE organization_id=org ORDER BY created_at DESC,id DESC LIMIT 50) recent
  WHERE recent.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.recovery_canonical(recent.payload),'UTF8')),'hex'))
$fn$;
CREATE FUNCTION app_private.core_owner_entitled(org uuid,actor uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.organizations_organizationmember m
  JOIN public.billing_subscription s ON s.organization_id=m.organization_id
  JOIN public.billing_billingcustomer c ON c.id=s.billing_customer_id AND c.user_id=m.user_id
  JOIN public.organization_workflow_profiles p ON p.organization_id=m.organization_id
  WHERE m.organization_id=org AND m.user_id=actor AND m.role='owner'
   AND s.status IN ('active','canceling') AND p.profile IN ('business.v1','development.v1'))
$fn$;
ALTER FUNCTION app_private.core_owner_entitled(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.core_owner_entitled(uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.core_owner_entitled(uuid,uuid) TO agentledger_app;

CREATE FUNCTION app_private.admit_core_authority() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public AS $fn$
DECLARE previous uuid;
BEGIN
 IF TG_TABLE_NAME='core_health_controls' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('core:'||NEW.organization_id::text||':control',0));
  SELECT id INTO previous FROM public.core_health_controls c WHERE c.organization_id=NEW.organization_id
   AND NOT EXISTS(SELECT 1 FROM public.core_health_controls next WHERE next.supersedes_id=c.id)
   ORDER BY created_at DESC,id DESC LIMIT 1;
  IF NEW.supersedes_id IS DISTINCT FROM previous THEN RAISE EXCEPTION 'Control must extend current authority history'; END IF;
  IF NEW.mode='paused' THEN RETURN NEW; END IF;
 END IF;
 IF NOT app_private.core_owner_entitled(NEW.organization_id,NEW.created_by_id) THEN
  RAISE EXCEPTION 'Active entitled owner and selected profile required';
 END IF;
 IF TG_TABLE_NAME='core_known_entities' THEN
  IF NEW.branch_profile IS DISTINCT FROM (SELECT profile FROM public.organization_workflow_profiles WHERE organization_id=NEW.organization_id) THEN
   RAISE EXCEPTION 'Entity meaning differs from selected profile';
  END IF;
 END IF;
 IF TG_TABLE_NAME='core_workflow_schedules' THEN
  PERFORM pg_advisory_xact_lock(hashtextextended('core:'||NEW.organization_id::text||':schedules',0));
  IF NEW.starts_at<clock_timestamp()-interval '5 minutes' OR NEW.starts_at>clock_timestamp()+interval '366 days'
   OR (SELECT count(*) FROM public.core_workflow_schedules s WHERE s.organization_id=NEW.organization_id
    AND NOT EXISTS(SELECT 1 FROM public.core_workflow_schedules successor WHERE successor.supersedes_id=s.id))>=10 THEN
   RAISE EXCEPTION 'Schedule configuration exceeds admission bounds';
  END IF;
 END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.admit_core_authority() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.admit_core_authority() FROM PUBLIC;
DO $fn$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['core_known_entities','core_workflow_schedules','core_health_controls','core_workflow_runs','core_action_card_revisions'] LOOP
  EXECUTE format('CREATE TRIGGER core_authority_admission BEFORE INSERT ON public.%I FOR EACH ROW EXECUTE FUNCTION app_private.admit_core_authority()',t);
 END LOOP;
END;$fn$;

CREATE FUNCTION app_private.issue_workflow_run(rid uuid,org uuid,actor uuid,op text,input_digest text,
 effective timestamptz,p jsonb,canonical_payload text,digest text,schedule uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE req jsonb; receipt uuid; profile text; r public.reports%ROWTYPE; j public.background_jobs%ROWTYPE;
 canonical_request text; selected_schedule public.core_workflow_schedules%ROWTYPE;
BEGIN
 IF org IS DISTINCT FROM app_private.current_organization_id() AND session_user='agentledger_app' THEN
  RAISE EXCEPTION 'Workflow tenant binding required';
 END IF;
 IF actor IS DISTINCT FROM app_private.current_user_id() AND session_user='agentledger_app' THEN
  RAISE EXCEPTION 'Workflow actor binding required';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 IF NOT app_private.core_owner_entitled(org,actor) OR (op<>'core.health_check' AND NOT app_private.core_work_allowed(org)) THEN
  RAISE EXCEPTION 'Workflow admission unavailable';
 END IF;
 IF canonical_payload::jsonb IS DISTINCT FROM p OR digest IS DISTINCT FROM encode(sha256(convert_to(canonical_payload,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Workflow payload binding invalid';
 END IF;
 req:=p->'request';
 SELECT w.profile INTO profile FROM public.organization_workflow_profiles w WHERE w.organization_id=org;
 IF jsonb_typeof(req) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(req))<>6
  OR req->>'schema' IS DISTINCT FROM 'stewardence.workflow.v1'
  OR req->>'organization_id' IS DISTINCT FROM org::text OR req->>'branch_profile' IS DISTINCT FROM profile
  OR req->>'operation' IS DISTINCT FROM op OR (req->>'effective_at')::timestamptz IS DISTINCT FROM effective
  OR effective>clock_timestamp() OR req->>'effective_at' !~ '[+]00:00$'
  OR jsonb_typeof(req->'receipt_ids') IS DISTINCT FROM 'array'
  OR p->>'schema' IS DISTINCT FROM 'stewardence.workflow_receipt.v1' OR p->>'authority' IS DISTINCT FROM 'proposal_only' THEN
  RAISE EXCEPTION 'Workflow request identity invalid';
 END IF;
 canonical_request:='{"branch_profile":'||to_json(req->>'branch_profile')::text||',"effective_at":'||to_json(req->>'effective_at')::text||
  ',"operation":'||to_json(op)::text||',"organization_id":'||to_json(org::text)::text||',"receipt_ids":['||
  coalesce((SELECT string_agg(to_json(v)::text,',' ORDER BY v) FROM jsonb_array_elements_text(req->'receipt_ids') v),'')||
  '],"schema":"stewardence.workflow.v1"}';
 IF input_digest IS DISTINCT FROM encode(sha256(convert_to(canonical_request,'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Workflow input digest invalid';
 END IF;
 IF op<>'core.health_check' THEN
  IF jsonb_array_length(req->'receipt_ids')<>1 THEN RAISE EXCEPTION 'One assessment receipt required'; END IF;
  receipt:=(req->'receipt_ids'->>0)::uuid;
  IF NOT EXISTS(SELECT 1 FROM public.assessment_snapshots WHERE id=receipt AND organization_id=org) THEN
   RAISE EXCEPTION 'Workflow assessment binding invalid';
  END IF;
 END IF;
 IF schedule IS NOT NULL THEN
  SELECT * INTO selected_schedule FROM public.core_workflow_schedules WHERE id=schedule AND organization_id=org FOR UPDATE;
  IF NOT FOUND OR selected_schedule.created_by_id<>actor OR op<>'report.generate_from_receipts'
   OR selected_schedule.snapshot_id<>receipt OR effective<selected_schedule.starts_at
   OR mod(extract(epoch FROM effective-selected_schedule.starts_at),selected_schedule.interval_hours*3600)<>0
   OR EXISTS(SELECT 1 FROM public.core_workflow_schedules WHERE supersedes_id=schedule)
   OR EXISTS(SELECT 1 FROM public.core_workflow_runs WHERE schedule_id=schedule AND effective_at>effective) THEN
   RAISE EXCEPTION 'Workflow schedule attribution invalid or stale';
  END IF;
 END IF;
 IF op='report.generate_from_receipts' THEN
  SELECT * INTO r FROM public.reports WHERE id=(p->>'report_id')::uuid AND organization_id=org AND assessment_snapshot_id=receipt;
  IF NOT FOUND THEN RAISE EXCEPTION 'Issued report effect is unresolved'; END IF;
  IF p->>'job_id' IS NOT NULL THEN
   SELECT * INTO j FROM public.background_jobs WHERE id=(p->>'job_id')::uuid AND organization_id=org
    AND job_type='report_generation' AND payload=jsonb_build_object('report_id',r.id::text);
   IF NOT FOUND OR p->>'state' IS DISTINCT FROM j.status THEN RAISE EXCEPTION 'Issued report job binding invalid'; END IF;
  ELSIF NOT EXISTS(SELECT 1 FROM public.report_artifacts WHERE report_id=r.id AND organization_id=org)
   OR p->>'state' IS DISTINCT FROM 'artifact_metadata_present' THEN RAISE EXCEPTION 'Issued artifact effect is unresolved'; END IF;
 ELSIF op='action_cards.reassess_from_signals' THEN
  IF NOT EXISTS(SELECT 1 FROM public.core_action_card_revisions WHERE id=(p->>'revision_id')::uuid
   AND organization_id=org AND snapshot_id=receipt AND jsonb_array_length(cards)=(p->>'proposal_count')::integer)
   OR p->>'state' IS DISTINCT FROM 'reassessed' THEN RAISE EXCEPTION 'Issued revision effect is unresolved'; END IF;
 ELSIF op<>'core.health_check' THEN RAISE EXCEPTION 'Unsupported workflow operation'; END IF;
 INSERT INTO public.core_workflow_runs(id,organization_id,created_by_id,created_at,operation,input_sha256,effective_at,payload,sha256,schedule_id)
  VALUES(rid,org,actor,clock_timestamp(),op,input_digest,effective,p,digest,schedule);
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.issue_workflow_run(uuid,uuid,uuid,text,text,timestamptz,jsonb,text,text,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_workflow_run(uuid,uuid,uuid,text,text,timestamptz,jsonb,text,text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.issue_workflow_run(uuid,uuid,uuid,text,text,timestamptz,jsonb,text,text,uuid) TO agentledger_app;
REVOKE INSERT ON public.core_workflow_runs FROM agentledger_app;
"""

class Migration(migrations.Migration):
    dependencies=[('jobs','0008_worker_transition_authority'),('reports','0004_reportartifact_security'),('billing','0005_billing_security')]
    operations=[migrations.RunSQL(SQL)]
