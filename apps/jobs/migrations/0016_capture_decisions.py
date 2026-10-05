"""Separate exact issued-capture decision v2; historical issuer body unchanged."""

from django.db import migrations

SQL = r"""
ALTER FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb) RENAME TO issue_core_decision_schema1;
REVOKE ALL ON FUNCTION app_private.issue_core_decision_schema1(uuid,uuid,jsonb)
 FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
CREATE FUNCTION app_private.issue_core_decision(org uuid,actor uuid,e jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE r public.core_action_card_revisions%ROWTYPE; s public.assessment_snapshots%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR org IS NULL OR actor IS NULL
  OR org IS DISTINCT FROM app_private.current_organization_id() OR actor IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Legacy decision context invalid'; END IF;
 SELECT * INTO r FROM public.core_action_card_revisions WHERE id=(e->>'revision_id')::uuid AND organization_id=org;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=r.snapshot_id AND organization_id=org;
 IF r.id IS NULL OR s.id IS NULL OR s.input_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR s.result_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR EXISTS(SELECT 1 FROM public.review_capture_proposal_receipts WHERE revision_id=r.id) THEN
  RAISE EXCEPTION 'Legacy decision requires snapshot schema one'; END IF;
 RETURN app_private.issue_core_decision_schema1(org,actor,e);
END;$fn$;
ALTER FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb)
 FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_core_decision(uuid,uuid,jsonb) TO agentledger_app;
CREATE FUNCTION app_private.issue_core_capture_decision(org uuid,actor uuid,e jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE r public.core_action_card_revisions%ROWTYPE; s public.assessment_snapshots%ROWTYPE;
 prior public.core_decision_events%ROWTYPE; previous uuid; rid uuid; idx integer; seq integer;
 receipt public.review_capture_proposal_receipts%ROWTYPE; capture public.assessment_capture_receipts%ROWTYPE; proposal jsonb;
 event_id uuid:=gen_random_uuid(); issued timestamptz; card_hash text; due date; body jsonb;
 required text[]:=ARRAY['schema','revision_id','card_index','expected_previous_event','event_kind','state',
 'responsible_label','due_date','notes','links','proposal_id','proposal_sha256']; key text; link jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Decision admission requires read committed'; END IF;
 IF org IS NULL OR actor IS NULL OR jsonb_typeof(e) IS DISTINCT FROM 'object' OR octet_length(e::text)>65536
  OR NOT e ?& required OR EXISTS(SELECT 1 FROM jsonb_object_keys(e) k WHERE NOT k=ANY(required)) THEN
  RAISE EXCEPTION 'Invalid decision envelope'; END IF;
 IF (org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id()) THEN RAISE EXCEPTION 'Decision identity mismatch'; END IF;
 FOREACH key IN ARRAY ARRAY['schema','revision_id','event_kind','state','responsible_label','notes','proposal_id','proposal_sha256'] LOOP
  IF jsonb_typeof(e->key) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'Decision fields must be strings'; END IF;
 END LOOP;
 IF e->>'schema'<>'stewardence.core_decision.v2' OR e->>'proposal_sha256' !~ '^[0-9a-f]{64}$' OR jsonb_typeof(e->'card_index')<>'number'
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
 PERFORM 1 FROM public.core_decision_desk_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.review_core_proposal_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 SELECT * INTO r FROM public.core_action_card_revisions WHERE id=rid AND organization_id=org FOR KEY SHARE;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=r.snapshot_id AND organization_id=org FOR KEY SHARE;
 SELECT * INTO capture FROM public.assessment_capture_receipts WHERE snapshot_id=s.id AND organization_id=org FOR KEY SHARE;
 SELECT * INTO receipt FROM public.review_capture_proposal_receipts WHERE revision_id=rid AND snapshot_id=s.id AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.organization_workflow_profiles WHERE organization_id=org FOR SHARE;
 IF r.id IS NULL OR s.id IS NULL OR capture.id IS NULL OR receipt.id IS NULL
  OR jsonb_typeof(r.cards) IS DISTINCT FROM 'array' OR idx>=jsonb_array_length(r.cards)
  OR receipt.contract IS DISTINCT FROM 'stewardence.core_review_proposal.v1'
  OR receipt.capture_receipt_id IS DISTINCT FROM capture.id
  OR receipt.input_sha256 IS DISTINCT FROM s.input_sha256 OR receipt.result_sha256 IS DISTINCT FROM s.result_sha256
  OR receipt.revision_sha256 IS DISTINCT FROM r.sha256 OR r.input_sha256 IS DISTINCT FROM s.result_sha256
  OR r.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(r.cards),'UTF8')),'hex')
  OR r.cards IS DISTINCT FROM app_private.recompute_capture_proposals_v1(s.id,org)
  OR receipt.qualification_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(jsonb_build_object(
   'schema','stewardence.core_review_proposal_applicability.v1','industry_applicability',s.input_payload->'industry_applicability',
   'ruleset',s.input_payload->'rulesets'->'industry','engine_versions',s.input_payload->'engine_versions')),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Capture proposal issuance unresolved'; END IF;
 proposal:=r.cards->idx;
 IF proposal->>'proposal_id' IS DISTINCT FROM (e->>'proposal_id')::uuid::text
  OR proposal->>'sha256' IS DISTINCT FROM e->>'proposal_sha256'
  OR proposal->>'sha256' IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(proposal-'sha256'),'UTF8')),'hex')
  OR proposal->>'snapshot_id' IS DISTINCT FROM s.id::text OR proposal->>'snapshot_result_sha256' IS DISTINCT FROM s.result_sha256
  OR proposal->>'resolution_effect' IS DISTINCT FROM 'none' OR proposal->'source_state_immutable' IS DISTINCT FROM 'true'::jsonb
  OR proposal->'resolution_verified' IS DISTINCT FROM 'false'::jsonb THEN
  RAISE EXCEPTION 'Exact proposal identity mismatch'; END IF;
 card_hash:=encode(sha256(convert_to(app_private.queue_canonical(r.cards->idx),'UTF8')),'hex');
 SELECT * INTO prior FROM public.core_decision_events WHERE revision_id=rid AND card_index=idx
  ORDER BY sequence DESC LIMIT 1 FOR KEY SHARE;
 IF (FOUND AND previous IS DISTINCT FROM prior.id) OR (NOT FOUND AND previous IS NOT NULL) THEN
  RAISE EXCEPTION 'Stale decision history'; END IF;
 seq:=coalesce(prior.sequence,0)+1; issued:=clock_timestamp();
 IF NOT EXISTS(SELECT 1 FROM public.core_decision_desk_gate WHERE id=1 AND enabled)
  OR NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org)
  OR s.captured_at>issued OR org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Capture decision authority unavailable after waits'; END IF;
 body:=jsonb_build_object('schema','stewardence.core_decision_event.v2','id',event_id,'organization_id',org,
  'created_by_id',actor,'created_at',issued,'revision_id',rid,'revision_sha256',r.sha256,
  'snapshot_id',s.id,'snapshot_result_sha256',s.result_sha256,'card_index',idx,'card_sha256',card_hash,
  'previous_event_id',previous,'sequence',seq,'event_kind',e->>'event_kind','state',e->>'state',
  'responsible_label',btrim(e->>'responsible_label'),'due_date',due,'notes',e->>'notes','links',e->'links',
  'owner_statement_only',true,'resolution_verified',false,'proposal_id',proposal->'proposal_id',
  'proposal_sha256',proposal->'sha256','proposal_contract',proposal->'schema',
  'proposal_receipt_id',receipt.id,'source_class',proposal->'source'->'class',
  'source_identity',proposal->'source'->'identity','source_digest',proposal->'source'->'digest',
  'original_outcome',proposal->'original_outcome','resolution_effect','none','source_state_immutable',true);
 INSERT INTO public.core_decision_events(id,organization_id,created_by_id,created_at,revision_id,snapshot_id,
  revision_sha256,snapshot_result_sha256,card_index,card_sha256,previous_event_id,sequence,event_kind,state,
  responsible_label,due_date,notes,links,payload,sha256)
 VALUES(event_id,org,actor,issued,rid,s.id,r.sha256,s.result_sha256,idx,card_hash,previous,seq,e->>'event_kind',
  e->>'state',btrim(e->>'responsible_label'),due,e->>'notes',e->'links',body,
  encode(sha256(convert_to(app_private.queue_canonical(body),'UTF8')),'hex'));
 RETURN event_id;
END;$fn$;
ALTER FUNCTION app_private.issue_core_capture_decision(uuid,uuid,jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_core_capture_decision(uuid,uuid,jsonb)
 FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_core_capture_decision(uuid,uuid,jsonb) TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0015_legacy_action_card_schema_fence"),
        ("reviews", "0005_capture_proposal_admission"),
    ]
    operations = [migrations.RunSQL(SQL)]
