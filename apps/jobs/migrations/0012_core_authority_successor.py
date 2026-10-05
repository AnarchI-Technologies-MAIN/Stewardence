"""Fail-closed isolation, canonical workflow issuance and database-bound health.

New successor only; no historical migration or deployed source is rewritten.
The workflow/queue canonical domain is closed and separate from financial data.
"""

from django.db import migrations

SQL = r"""

-- Private bounded observation, not a live service/provider probe. Job inputs and
-- their historical admission digests are immutable under runtime grants.
CREATE FUNCTION app_private.recorded_core_health(org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE r record; valid boolean:=true; checked integer:=0; held bigint; mode text;
 expected jsonb; reason text; fingerprint text;
BEGIN
 IF org IS NULL THEN RAISE EXCEPTION 'Health organization required'; END IF;
 FOR r IN SELECT q.*,j.job_type,j.input_sha256,j.organization_id AS job_org
  FROM (SELECT * FROM public.job_recovery_receipts WHERE organization_id=org
   ORDER BY created_at DESC,id DESC LIMIT 50) q
  LEFT JOIN public.background_jobs j ON j.id=q.job_id LOOP
  checked:=checked+1;
  reason:=r.payload->>'reason_code'; fingerprint:=r.payload->>'failure_fingerprint';
  expected:=jsonb_build_object('schema','stewardence.recovery.v1','job_id',r.job_id::text,
   'organization_id',org::text,'operation',r.job_type,'attempt',r.attempt,'outcome',r.outcome,
   'input_sha256',r.input_sha256,'reason_code',reason,'failure_fingerprint',fingerprint);
  IF r.job_org IS DISTINCT FROM org OR r.attempt<1 OR r.payload IS DISTINCT FROM expected
   OR reason IS NULL OR fingerprint IS NULL THEN valid:=false;
  ELSE
   valid:=valid AND r.sha256=encode(sha256(convert_to(app_private.recovery_canonical(r.payload),'UTF8')),'hex')
    AND ((r.outcome='completed' AND reason='' AND fingerprint='')
     OR (r.outcome IN ('retry','review') AND fingerprint ~ '^[0-9a-f]{64}$'
      AND ((r.outcome='retry' AND reason IN ('job_execution_failed','lease_expired'))
       OR (r.outcome='review' AND reason IN ('job_requires_review','retry_limit_reached','lease_expired')))));
  END IF;
 END LOOP;
 SELECT count(*) INTO held FROM public.background_jobs WHERE organization_id=org AND status='failed';
 SELECT c.mode INTO mode FROM public.core_health_controls c WHERE c.organization_id=org
  AND NOT EXISTS(SELECT 1 FROM public.core_health_controls next WHERE next.supersedes_id=c.id)
  ORDER BY c.created_at DESC,c.id DESC LIMIT 1;
 RETURN jsonb_build_object('receipt_integrity',valid,'checked_recent_receipts',checked,
  'review_holds',held,'owner_mode',coalesce(mode,'normal'),'circuit',CASE WHEN valid THEN 'closed' ELSE 'blocked' END,
  'scope','Recorded workflow state; not a live service or provider probe');
END;$fn$;
ALTER FUNCTION app_private.recorded_core_health(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.recorded_core_health(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION app_private.claim_job(w text, lease interval, token uuid)
RETURNS SETOF public.background_jobs LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
 IF w IS NULL OR lease IS NULL OR length(w) NOT BETWEEN 1 AND 255 OR lease<=interval '0 seconds' OR lease>interval '10 minutes' OR token IS NULL THEN
  RAISE EXCEPTION 'Invalid claim parameters';
 END IF;
 RETURN QUERY WITH candidate AS (
  SELECT id FROM public.background_jobs WHERE status='queued' AND available_at<=clock_timestamp()
  AND (job_type<>'report_generation' OR app_private.core_work_allowed(organization_id))
  ORDER BY priority,available_at,id FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE public.background_jobs j SET status='running',locked_by=w,locked_at=clock_timestamp(),
  lock_expires_at=clock_timestamp()+lease,claim_token=token,attempts=j.attempts+1
  FROM candidate c WHERE j.id=c.id RETURNING j.*;
END;$fn$;

CREATE OR REPLACE FUNCTION app_private.finish_job(jid uuid,w text,token uuid,action text,lease interval,
 code text,summary text,fingerprint text,retry boolean) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE j public.background_jobs%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
 IF jid IS NULL OR w IS NULL OR w='' OR token IS NULL THEN RAISE EXCEPTION 'Invalid claim identity'; END IF;
 SELECT * INTO j FROM public.background_jobs WHERE id=jid;
 IF NOT FOUND THEN RETURN false; END IF;
 IF j.job_type='report_generation' AND current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Report persistence requires read committed control admission';
 END IF;
 -- All persistence/control transitions take this lock before any job row lock.
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||j.organization_id::text||':control',0));
 SELECT * INTO j FROM public.background_jobs WHERE id=jid FOR UPDATE;
 IF j.status<>'running' OR j.locked_by IS DISTINCT FROM w OR j.claim_token IS DISTINCT FROM token
  OR j.lock_expires_at IS NULL OR j.lock_expires_at<=clock_timestamp() THEN RETURN false; END IF;
 IF action IS NULL THEN RAISE EXCEPTION 'Transition action required'; END IF;
 IF action IN ('complete','heartbeat') AND j.job_type='report_generation'
  AND NOT app_private.core_work_allowed(j.organization_id) THEN RETURN false; END IF;
 IF action='heartbeat' THEN
  IF lease IS NULL OR lease<=interval '0 seconds' OR lease>interval '10 minutes' THEN RAISE EXCEPTION 'Invalid heartbeat lease'; END IF;
  UPDATE public.background_jobs SET lock_expires_at=clock_timestamp()+lease WHERE id=jid;
 ELSIF action='complete' THEN
  UPDATE public.background_jobs SET status='completed',completed_at=clock_timestamp(),available_at=clock_timestamp(),
   locked_at=NULL,lock_expires_at=NULL,locked_by=NULL,claim_token=NULL WHERE id=jid;
 ELSIF action='fail' THEN
  IF code IS NULL OR code='' OR summary IS NULL OR summary='' OR fingerprint IS NULL OR fingerprint='' THEN
   RAISE EXCEPTION 'Safe failure evidence required';
  END IF;
  retry:=coalesce(retry,false) AND j.job_type='report_generation';
  UPDATE public.background_jobs SET status=CASE WHEN retry AND attempts<5 THEN 'queued' ELSE 'failed' END,
   available_at=clock_timestamp()+CASE attempts WHEN 1 THEN interval '1 minute' WHEN 2 THEN interval '5 minutes'
    WHEN 3 THEN interval '30 minutes' WHEN 4 THEN interval '2 hours' ELSE interval '0 seconds' END,
   completed_at=CASE WHEN retry AND attempts<5 THEN NULL ELSE clock_timestamp() END,
   locked_at=NULL,lock_expires_at=NULL,locked_by=NULL,claim_token=NULL,
   error_code=CASE WHEN retry AND attempts>=5 THEN 'retry_limit_reached' ELSE code END,
   safe_error_summary=CASE WHEN retry AND attempts>=5 THEN 'Retry limit reached; review required.' ELSE summary END,
   error_fingerprint=fingerprint WHERE id=jid;
 ELSE RAISE EXCEPTION 'Unsupported job transition'; END IF;
 RETURN true;
END;$fn$;

CREATE OR REPLACE FUNCTION app_private.lock_job_persistence(jid uuid,w text,token uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE j public.background_jobs%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
 IF jid IS NULL OR w IS NULL OR w='' OR token IS NULL THEN RAISE EXCEPTION 'Invalid claim identity'; END IF;
 SELECT * INTO j FROM public.background_jobs WHERE id=jid;
 IF NOT FOUND THEN RETURN false; END IF;
 IF j.job_type='report_generation' AND current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Report persistence requires read committed control admission';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||j.organization_id::text||':control',0));
 SELECT * INTO j FROM public.background_jobs WHERE id=jid FOR UPDATE;
 RETURN j.status='running' AND j.locked_by=w AND j.claim_token=token AND j.lock_expires_at>clock_timestamp()
  AND (j.job_type<>'report_generation' OR app_private.core_work_allowed(j.organization_id));
END;$fn$;

CREATE OR REPLACE FUNCTION app_private.recover_jobs() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
DECLARE candidate record; j public.background_jobs%ROWTYPE; recovered integer:=0; candidates uuid[]; tenant uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
 -- Freeze the bounded candidate set, then acquire its complete tenant-lock set
 -- in one global UUID order before any job row lock. Stale candidates are
 -- rechecked below; they cannot reorder retained transaction advisory locks.
 SELECT array_agg(id ORDER BY lock_expires_at,id) INTO candidates FROM
  (SELECT id,lock_expires_at FROM public.background_jobs WHERE status='running'
   AND lock_expires_at<clock_timestamp() ORDER BY lock_expires_at,id LIMIT 100) selected;
 IF candidates IS NULL THEN RETURN 0; END IF;
 FOR tenant IN SELECT DISTINCT organization_id FROM public.background_jobs
  WHERE id=ANY(candidates) ORDER BY organization_id LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('core:'||tenant::text||':control',0));
 END LOOP;
 FOR candidate IN SELECT id,organization_id FROM public.background_jobs
  WHERE id=ANY(candidates) ORDER BY lock_expires_at,id LOOP
  SELECT * INTO j FROM public.background_jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
  IF FOUND AND j.status='running' AND j.lock_expires_at<clock_timestamp() THEN
   UPDATE public.background_jobs SET status=CASE WHEN attempts<5 AND job_type='report_generation' THEN 'queued' ELSE 'failed' END,
    available_at=clock_timestamp(),completed_at=CASE WHEN attempts<5 AND job_type='report_generation' THEN NULL ELSE clock_timestamp() END,
    locked_at=NULL,lock_expires_at=NULL,locked_by=NULL,claim_token=NULL,error_code='lease_expired',
    safe_error_summary='The worker lease expired before completion.',error_fingerprint='worker_lease_expired' WHERE id=j.id;
   recovered:=recovered+1;
  END IF;
 END LOOP;
 RETURN recovered;
END;$fn$;
DO $fn$ DECLARE f regprocedure; BEGIN
 FOREACH f IN ARRAY ARRAY['app_private.claim_job(text,interval,uuid)'::regprocedure,
  'app_private.finish_job(uuid,text,uuid,text,interval,text,text,text,boolean)'::regprocedure,
  'app_private.lock_job_persistence(uuid,text,uuid)'::regprocedure,'app_private.recover_jobs()'::regprocedure] LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO agentledger_owner',f);
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO agentledger_worker',f);
 END LOOP;
END;$fn$;
REVOKE UPDATE ON public.background_jobs FROM agentledger_worker;
CREATE OR REPLACE FUNCTION app_private.admit_core_authority() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public AS $fn$
DECLARE previous uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
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
CREATE OR REPLACE FUNCTION app_private.issue_workflow_run(rid uuid,org uuid,actor uuid,op text,input_digest text,
 effective timestamptz,p jsonb,canonical_payload text,digest text,schedule uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE req jsonb; receipt uuid; profile text; r public.reports%ROWTYPE; j public.background_jobs%ROWTYPE;
 canonical_request text; selected_schedule public.core_workflow_schedules%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
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
 IF p IS NULL OR canonical_payload IS DISTINCT FROM app_private.queue_canonical(p)
  OR digest IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(p),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Workflow payload binding invalid';
 END IF;
 IF jsonb_typeof(p) IS DISTINCT FROM 'object'
  OR (SELECT array_agg(key ORDER BY key) FROM jsonb_object_keys(p) key) IS DISTINCT FROM
   (CASE op WHEN 'core.health_check' THEN ARRAY['authority','recorded_health','request','schema']
    WHEN 'report.generate_from_receipts' THEN ARRAY['authority','job_id','report_id','request','schema','state']
    WHEN 'action_cards.reassess_from_signals' THEN ARRAY['authority','proposal_count','request','revision_id','schema','state']
    ELSE ARRAY[]::text[] END) THEN RAISE EXCEPTION 'Closed workflow result required'; END IF;
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
  IF jsonb_typeof(p->'proposal_count') IS DISTINCT FROM 'number' THEN
   RAISE EXCEPTION 'Proposal count requires an admitted integer';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM public.core_action_card_revisions WHERE id=(p->>'revision_id')::uuid
   AND organization_id=org AND snapshot_id=receipt AND jsonb_array_length(cards)::numeric=(p->>'proposal_count')::numeric)
   OR p->>'state' IS DISTINCT FROM 'reassessed' THEN RAISE EXCEPTION 'Issued revision effect is unresolved'; END IF;
 ELSIF op='core.health_check' THEN
  IF jsonb_array_length(req->'receipt_ids')<>0 OR p->'recorded_health' IS DISTINCT FROM app_private.recorded_core_health(org) THEN
   RAISE EXCEPTION 'Health receipt differs from recorded database state';
  END IF;
 ELSE RAISE EXCEPTION 'Unsupported workflow operation'; END IF;
 INSERT INTO public.core_workflow_runs(id,organization_id,created_by_id,created_at,operation,input_sha256,effective_at,payload,sha256,schedule_id)
  VALUES(rid,org,actor,clock_timestamp(),op,input_digest,effective,p,digest,schedule);
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.issue_workflow_run(uuid,uuid,uuid,text,text,timestamptz,jsonb,text,text,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_workflow_run(uuid,uuid,uuid,text,text,timestamptz,jsonb,text,text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.issue_workflow_run(uuid,uuid,uuid,text,text,timestamptz,jsonb,text,text,uuid) TO agentledger_app;
REVOKE INSERT ON public.core_workflow_runs FROM agentledger_app;

CREATE OR REPLACE FUNCTION app_private.issue_action_cards(rid uuid,org uuid,actor uuid,snapshot uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; cards jsonb; existing uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Core authority requires read committed admission';
 END IF;
 IF session_user='agentledger_app' AND (org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id()) THEN RAISE EXCEPTION 'Action-card context binding invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Action-card admission unavailable';
 END IF;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=snapshot AND organization_id=org;
 IF NOT FOUND THEN RAISE EXCEPTION 'Action-card assessment unresolved'; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('inventory_item_id',item->>'inventory_item_id',
  'rule_id',policy->'rule_id','rule_version',policy->'rule_version','severity',policy->'severity',
  'proposal',policy->'recommended_remediation','authority','proposal_only')
  ORDER BY item->>'inventory_item_id' COLLATE "C",policy->>'rule_id' COLLATE "C",policy->>'rule_version' COLLATE "C"),'[]'::jsonb)
  INTO cards FROM jsonb_array_elements(s.result_payload->'inventory_results') item
  CROSS JOIN LATERAL jsonb_array_elements(item->'policy_results') policy WHERE policy->>'result'='FAIL';
 SELECT id INTO existing FROM public.core_action_card_revisions WHERE organization_id=org AND snapshot_id=snapshot;
 IF FOUND THEN RETURN existing; END IF;
 INSERT INTO public.core_action_card_revisions(id,organization_id,created_by_id,created_at,snapshot_id,input_sha256,cards,sha256)
  VALUES(rid,org,actor,clock_timestamp(),snapshot,s.result_sha256,cards,
   encode(sha256(convert_to(app_private.queue_canonical(cards),'UTF8')),'hex'));
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.issue_action_cards(uuid,uuid,uuid,uuid) TO agentledger_app;
REVOKE INSERT ON public.core_action_card_revisions FROM agentledger_app;

"""


class Migration(migrations.Migration):
    dependencies = [("jobs", "0011_action_card_issuance")]
    operations = [migrations.RunSQL(SQL)]
