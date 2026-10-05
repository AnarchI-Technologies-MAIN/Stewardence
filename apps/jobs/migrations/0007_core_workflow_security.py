from django.db import migrations

SQL = r"""
CREATE FUNCTION app_private.protect_core_record() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
DECLARE parent_org uuid; data jsonb;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Core records are append-only'; END IF;
 IF current_user='agentledger_app' AND NEW.created_by_id IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Core actor binding is invalid';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM public.organizations_organizationmember WHERE organization_id=NEW.organization_id
   AND user_id=NEW.created_by_id AND role='owner') THEN RAISE EXCEPTION 'Core owner binding is invalid'; END IF;
 data:=to_jsonb(NEW);
 IF TG_TABLE_NAME='core_workflow_schedules' THEN
  IF NEW.interval_hours NOT IN (24,168,720) THEN RAISE EXCEPTION 'Core schedule interval is invalid'; END IF;
 END IF;
 IF TG_TABLE_NAME='core_health_controls' THEN
  IF NEW.mode NOT IN ('normal','paused') OR length(trim(NEW.reason))=0 THEN RAISE EXCEPTION 'Core health control is invalid'; END IF;
 END IF;
 IF TG_TABLE_NAME='core_known_entities' THEN
 IF (
  NEW.category NOT IN ('services','branches','ai_accounts','agents','employees')
  OR NEW.provenance<>'declared' OR NEW.branch_profile NOT IN ('business.v1','development.v1')
  OR length(trim(NEW.label))=0 OR NEW.as_of>clock_timestamp()
  OR NEW.sha256 !~ '^[0-9a-f]{64}$') THEN
  RAISE EXCEPTION 'Core entity declaration is invalid';
 END IF;
 END IF;
 IF data->>'supersedes_id' IS NOT NULL THEN
  EXECUTE format('SELECT organization_id FROM public.%I WHERE id=$1',TG_TABLE_NAME)
   INTO parent_org USING (data->>'supersedes_id')::uuid;
  IF parent_org IS DISTINCT FROM NEW.organization_id THEN RAISE EXCEPTION 'Core successor binding is invalid'; END IF;
 END IF;
 IF TG_TABLE_NAME IN ('core_workflow_schedules','core_action_card_revisions') THEN
  IF NOT EXISTS (SELECT 1 FROM public.assessment_snapshots WHERE id=(data->>'snapshot_id')::uuid
   AND organization_id=NEW.organization_id AND result_sha256=COALESCE(data->>'snapshot_sha256',data->>'input_sha256')) THEN
   RAISE EXCEPTION 'Core snapshot binding is invalid';
  END IF;
 END IF;
 IF TG_TABLE_NAME='core_workflow_runs' AND data->>'schedule_id' IS NOT NULL THEN
  IF NOT EXISTS(SELECT 1 FROM public.core_workflow_schedules WHERE id=(data->>'schedule_id')::uuid AND organization_id=NEW.organization_id) THEN
   RAISE EXCEPTION 'Core schedule binding is invalid';
  END IF;
 END IF;
 RETURN NEW;
END;
$fn$;
ALTER FUNCTION app_private.protect_core_record() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_core_record() FROM PUBLIC;
DO $fn$
DECLARE t text;
BEGIN
 FOREACH t IN ARRAY ARRAY['core_known_entities','core_workflow_schedules','core_health_controls','core_workflow_runs','core_action_card_revisions'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO agentledger_owner',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',t);
  EXECUTE format('GRANT SELECT,INSERT ON public.%I TO agentledger_app',t);
  EXECUTE format('GRANT SELECT ON public.%I TO agentledger_worker',t);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY core_owner ON public.%I FOR ALL TO agentledger_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('CREATE POLICY core_tenant ON public.%I FOR ALL TO agentledger_app,agentledger_worker USING(organization_id=app_private.current_organization_id()) WITH CHECK(organization_id=app_private.current_organization_id())',t);
  EXECUTE format('CREATE TRIGGER core_record_guard BEFORE INSERT OR UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION app_private.protect_core_record()',t);
 END LOOP;
END;
$fn$;
CREATE FUNCTION app_private.core_work_allowed(org uuid) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
 SELECT NOT EXISTS(SELECT 1 FROM public.core_health_controls
   WHERE organization_id=org AND mode='paused' AND NOT EXISTS
    (SELECT 1 FROM public.core_health_controls successor WHERE successor.supersedes_id=core_health_controls.id))
 AND NOT EXISTS(SELECT 1 FROM (SELECT payload,sha256 FROM public.job_recovery_receipts
    WHERE organization_id=org ORDER BY created_at DESC,id DESC LIMIT 50) recent
   WHERE recent.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.recovery_canonical(recent.payload),'UTF8')),'hex'))
$fn$;
ALTER FUNCTION app_private.core_work_allowed(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.core_work_allowed(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.core_work_allowed(uuid) TO agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies=[('jobs','0006_corecontrol_workflowschedule_actioncardrevision_and_more')]
    operations=[migrations.RunSQL(SQL)]
