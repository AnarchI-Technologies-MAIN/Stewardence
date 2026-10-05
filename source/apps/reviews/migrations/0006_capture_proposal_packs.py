"""Capture pack v4: freeze issued proposals and separate owner statement kinds."""

from django.db import migrations

SQL = r"""
ALTER FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) RENAME TO freeze_review_cycle_pre_v4;
REVOKE ALL ON FUNCTION app_private.freeze_review_cycle_pre_v4(uuid,uuid,uuid,integer) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) RENAME TO request_review_artifact_pre_v4;
REVOKE ALL ON FUNCTION app_private.request_review_artifact_pre_v4(uuid,uuid,uuid,integer,uuid,uuid,boolean) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.review_pack_projection(uuid,uuid) RENAME TO review_pack_projection_pre_v4;
REVOKE ALL ON FUNCTION app_private.review_pack_projection_pre_v4(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) RENAME TO complete_review_pack_pre_v4;
REVOKE ALL ON FUNCTION app_private.complete_review_pack_pre_v4(uuid,uuid,uuid,text,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.require_capture_proposal_freeze_authority(org uuid,actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org) THEN
  RAISE EXCEPTION 'Capture proposal freeze authority unavailable after waits'; END IF;
END;$fn$;
ALTER FUNCTION app_private.require_capture_proposal_freeze_authority(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.require_capture_proposal_freeze_authority(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.require_capture_pack_creator(sid uuid,org uuid,actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.assessment_snapshots s
  JOIN public.assessment_capture_receipts c ON c.snapshot_id=s.id AND c.organization_id=s.organization_id
  JOIN public.review_capture_proposal_receipts p ON p.snapshot_id=s.id AND p.organization_id=s.organization_id
  JOIN public.core_action_card_revisions r ON r.id=p.revision_id AND r.snapshot_id=s.id AND r.organization_id=s.organization_id
  WHERE s.id=sid AND s.organization_id=org AND s.created_by_id=actor
   AND c.created_by_id=actor AND p.created_by_id=actor AND r.created_by_id=actor) THEN
  RAISE EXCEPTION 'Capture proposal pack requires original admitted creator'; END IF;
END;$fn$;
ALTER FUNCTION app_private.require_capture_pack_creator(uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.require_capture_pack_creator(uuid,uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.review_capture_proposal_selection_v1(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; c public.assessment_capture_receipts%ROWTYPE;
 receipt public.review_capture_proposal_receipts%ROWTYPE; r public.core_action_card_revisions%ROWTYPE;
BEGIN
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 SELECT * INTO c FROM public.assessment_capture_receipts WHERE snapshot_id=sid AND organization_id=org;
 SELECT * INTO receipt FROM public.review_capture_proposal_receipts WHERE snapshot_id=sid AND organization_id=org;
 SELECT * INTO r FROM public.core_action_card_revisions WHERE id=receipt.revision_id AND snapshot_id=sid AND organization_id=org;
 IF s.id IS NULL OR c.id IS NULL OR receipt.id IS NULL OR r.id IS NULL
  OR receipt.capture_receipt_id IS DISTINCT FROM c.id OR receipt.created_by_id IS DISTINCT FROM s.created_by_id
  OR r.created_by_id IS DISTINCT FROM s.created_by_id OR receipt.contract IS DISTINCT FROM 'stewardence.core_review_proposal.v1'
  OR receipt.input_sha256 IS DISTINCT FROM s.input_sha256 OR receipt.result_sha256 IS DISTINCT FROM s.result_sha256
  OR receipt.revision_sha256 IS DISTINCT FROM r.sha256 OR r.input_sha256 IS DISTINCT FROM s.result_sha256
  OR r.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(r.cards),'UTF8')),'hex')
  OR r.cards IS DISTINCT FROM app_private.recompute_capture_proposals_v1(sid,org)
  OR receipt.qualification_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(jsonb_build_object(
   'schema','stewardence.core_review_proposal_applicability.v1','industry_applicability',s.input_payload->'industry_applicability',
   'ruleset',s.input_payload->'rulesets'->'industry','engine_versions',s.input_payload->'engine_versions')),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Frozen proposal issuance pins invalid'; END IF;
 RETURN (SELECT coalesce(jsonb_agg(jsonb_build_object('proposal_receipt_id',receipt.id::text,'revision_id',r.id::text,
  'revision_sha256',r.sha256,'card_index',ord-1,'card_sha256',encode(sha256(convert_to(app_private.queue_canonical(value),'UTF8')),'hex'),
  'qualification_sha256',receipt.qualification_sha256,'proposal',value) ORDER BY ord),'[]'::jsonb)
  FROM jsonb_array_elements(r.cards) WITH ORDINALITY t(value,ord));
END;$fn$;
ALTER FUNCTION app_private.review_capture_proposal_selection_v1(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_capture_proposal_selection_v1(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.validate_capture_decision_selection_v2(selected jsonb,proposals jsonb,sid uuid,org uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE entry jsonb; proposal jsonb; p jsonb; d public.core_decision_events%ROWTYPE;
BEGIN
 IF jsonb_typeof(selected) IS DISTINCT FROM 'array' OR jsonb_array_length(selected)>2*jsonb_array_length(proposals)
  OR (SELECT count(DISTINCT value->>'event_id') FROM jsonb_array_elements(selected))<>jsonb_array_length(selected)
  OR (SELECT count(DISTINCT (value->'payload'->>'card_index',value->'payload'->>'event_kind')) FROM jsonb_array_elements(selected))<>jsonb_array_length(selected) THEN
  RAISE EXCEPTION 'Frozen capture statement membership invalid'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(selected) LOOP
  IF jsonb_typeof(entry) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(entry))<>3
   OR NOT entry ?& ARRAY['event_id','event_sha256','payload'] THEN RAISE EXCEPTION 'Frozen capture statement shape invalid'; END IF;
  p:=entry->'payload';
  SELECT * INTO d FROM public.core_decision_events WHERE id=(entry->>'event_id')::uuid AND snapshot_id=sid AND organization_id=org;
  SELECT value INTO proposal FROM jsonb_array_elements(proposals) WHERE value->>'card_index'=p->>'card_index';
  IF d.id IS NULL OR proposal IS NULL OR p IS DISTINCT FROM d.payload OR entry->>'event_sha256' IS DISTINCT FROM d.sha256
   OR d.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(p),'UTF8')),'hex')
   OR p->>'schema' IS DISTINCT FROM 'stewardence.core_decision_event.v2'
   OR (SELECT count(*) FROM jsonb_object_keys(p))<>31
   OR p->>'id' IS DISTINCT FROM d.id::text OR p->>'organization_id' IS DISTINCT FROM org::text
   OR p->>'created_by_id' IS DISTINCT FROM d.created_by_id::text OR (p->>'created_at')::timestamptz IS DISTINCT FROM d.created_at
   OR p->>'revision_id' IS DISTINCT FROM proposal->>'revision_id' OR d.revision_id::text IS DISTINCT FROM proposal->>'revision_id'
   OR p->>'revision_sha256' IS DISTINCT FROM proposal->>'revision_sha256' OR d.revision_sha256 IS DISTINCT FROM proposal->>'revision_sha256'
   OR p->>'snapshot_id' IS DISTINCT FROM sid::text OR p->>'snapshot_result_sha256' IS DISTINCT FROM proposal->'proposal'->>'snapshot_result_sha256'
   OR d.snapshot_result_sha256 IS DISTINCT FROM p->>'snapshot_result_sha256'
   OR p->'card_index' IS DISTINCT FROM to_jsonb(d.card_index) OR p->>'card_sha256' IS DISTINCT FROM proposal->>'card_sha256'
   OR d.card_sha256 IS DISTINCT FROM proposal->>'card_sha256' OR p->'sequence' IS DISTINCT FROM to_jsonb(d.sequence) OR d.sequence<1
   OR p->'previous_event_id' IS DISTINCT FROM coalesce(to_jsonb(d.previous_event_id),'null'::jsonb)
   OR p->>'event_kind' IS DISTINCT FROM d.event_kind OR p->>'state' IS DISTINCT FROM d.state
   OR p->>'responsible_label' IS DISTINCT FROM d.responsible_label OR p->'due_date' IS DISTINCT FROM coalesce(to_jsonb(d.due_date),'null'::jsonb)
   OR p->>'notes' IS DISTINCT FROM d.notes OR p->'links' IS DISTINCT FROM d.links
   OR p->>'proposal_id' IS DISTINCT FROM proposal->'proposal'->>'proposal_id'
   OR p->>'proposal_sha256' IS DISTINCT FROM proposal->'proposal'->>'sha256'
   OR p->>'proposal_contract' IS DISTINCT FROM proposal->'proposal'->>'schema'
   OR p->>'proposal_receipt_id' IS DISTINCT FROM proposal->>'proposal_receipt_id'
   OR p->>'source_class' IS DISTINCT FROM proposal->'proposal'->'source'->>'class'
   OR p->>'source_identity' IS DISTINCT FROM proposal->'proposal'->'source'->>'identity'
   OR p->>'source_digest' IS DISTINCT FROM proposal->'proposal'->'source'->>'digest'
   OR p->>'original_outcome' IS DISTINCT FROM proposal->'proposal'->>'original_outcome'
   OR p->>'resolution_effect' IS DISTINCT FROM 'none' OR p->'source_state_immutable' IS DISTINCT FROM 'true'::jsonb
   OR p->'owner_statement_only' IS DISTINCT FROM 'true'::jsonb OR p->'resolution_verified' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'Frozen capture statement issuance pins invalid'; END IF;
 END LOOP;
 RETURN true;
END;$fn$;
ALTER FUNCTION app_private.validate_capture_decision_selection_v2(jsonb,jsonb,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.validate_capture_decision_selection_v2(jsonb,jsonb,uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.review_capture_decision_selection_v2(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE receipt public.review_capture_proposal_receipts%ROWTYPE; selected jsonb; proposals jsonb;
BEGIN
 proposals:=app_private.review_capture_proposal_selection_v1(sid,org);
 SELECT * INTO receipt FROM public.review_capture_proposal_receipts WHERE snapshot_id=sid AND organization_id=org;
 SELECT coalesce(jsonb_agg(jsonb_build_object('event_id',d.id::text,'event_sha256',d.sha256,'payload',d.payload)
  ORDER BY d.card_index,d.event_kind COLLATE "C",d.sequence),'[]'::jsonb) INTO selected FROM public.core_decision_events d
 WHERE d.revision_id=receipt.revision_id AND d.snapshot_id=sid AND d.organization_id=org
  AND NOT EXISTS(SELECT 1 FROM public.core_decision_events newer WHERE newer.revision_id=d.revision_id
   AND newer.card_index=d.card_index AND newer.event_kind=d.event_kind AND newer.sequence>d.sequence);
 PERFORM app_private.validate_capture_decision_selection_v2(selected,proposals,sid,org);
 RETURN selected;
END;$fn$;
ALTER FUNCTION app_private.review_capture_decision_selection_v2(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_capture_decision_selection_v2(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.validate_capture_proposal_pack(pid uuid,org uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE p public.review_pack_identities%ROWTYPE; c public.review_cycles%ROWTYPE;
BEGIN
 SELECT * INTO p FROM public.review_pack_identities WHERE id=pid AND organization_id=org;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=org;
 IF p.id IS NULL OR c.id IS NULL OR p.created_by_id IS DISTINCT FROM c.created_by_id
  OR p.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(p.manifest),'UTF8')),'hex')
  OR (SELECT count(*) FROM jsonb_object_keys(p.manifest))<>12
  OR NOT p.manifest ?& ARRAY['schema','cycle_id','organization_id','baseline_pack_id','snapshot','capture','selected_proposals','selected_decisions','proposal_contract_version','selection_scope','artifact_state','baseline_promotion']
  OR p.manifest->>'proposal_contract_version' IS DISTINCT FROM 'stewardence.core_review_proposal.v1'
  OR p.manifest->>'schema' IS DISTINCT FROM 'stewardence.review_pack.v4' OR p.manifest->>'cycle_id' IS DISTINCT FROM c.id::text
  OR p.manifest->>'organization_id' IS DISTINCT FROM org::text
  OR p.manifest->'snapshot' IS DISTINCT FROM app_private.review_snapshot_manifest_capture(c.input_snapshot_id,org)
  OR p.manifest->'capture' IS DISTINCT FROM app_private.review_capture_binding(c.input_snapshot_id,org)
  OR p.manifest->'selected_proposals' IS DISTINCT FROM app_private.review_capture_proposal_selection_v1(c.input_snapshot_id,org)
  OR p.manifest->>'selection_scope' IS DISTINCT FROM 'issued_capture_proposals' OR p.manifest->>'artifact_state' IS DISTINCT FROM 'not_created'
  OR p.manifest->'baseline_pack_id' IS DISTINCT FROM 'null'::jsonb OR p.manifest->>'baseline_promotion' IS DISTINCT FROM 'blocked' THEN
  RAISE EXCEPTION 'Capture proposal pack frozen binding invalid'; END IF;
 PERFORM app_private.validate_capture_decision_selection_v2(p.manifest->'selected_decisions',p.manifest->'selected_proposals',c.input_snapshot_id,org);
 RETURN true;
END;$fn$;
ALTER FUNCTION app_private.validate_capture_proposal_pack(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.validate_capture_proposal_pack(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE OR REPLACE FUNCTION app_private.freeze_capture_proposal_review_cycle(cid uuid,org uuid,actor uuid,expected integer) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE c public.review_cycles%ROWTYPE; event public.review_cycle_events%ROWTYPE;
 pack public.review_pack_identities%ROWTYPE; coverage public.billing_paid_coverage%ROWTYPE;
 snapshot jsonb; manifest jsonb; payload jsonb; rid uuid; pid uuid; retained bigint; reserved bigint;
 decision_idx integer; decision_revision uuid;
BEGIN
 PERFORM app_private.require_review_owner(org,actor);
 IF expected IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'Review revision compare and swap failed'; END IF;
 SELECT * INTO c FROM public.review_cycles WHERE id=cid AND organization_id=org FOR UPDATE;
 IF NOT FOUND OR c.created_by_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'Review cycle owner binding invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':proposal:'||c.input_snapshot_id::text,0));
 PERFORM 1 FROM public.review_core_proposal_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 PERFORM 1 FROM public.assessment_snapshots WHERE id=c.input_snapshot_id AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.assessment_capture_receipts WHERE snapshot_id=c.input_snapshot_id AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.review_capture_proposal_receipts WHERE snapshot_id=c.input_snapshot_id AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.core_action_card_revisions WHERE snapshot_id=c.input_snapshot_id AND organization_id=org FOR KEY SHARE;
 SELECT id INTO decision_revision FROM public.core_action_card_revisions WHERE snapshot_id=c.input_snapshot_id AND organization_id=org;
 FOR decision_idx IN SELECT generate_series(0,jsonb_array_length(cards)-1) FROM public.core_action_card_revisions WHERE id=decision_revision LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':decision:'||decision_revision::text||':'||decision_idx::text,0));
 END LOOP;
 PERFORM 1 FROM public.core_decision_events WHERE revision_id=decision_revision AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.organization_workflow_profiles WHERE organization_id=org FOR SHARE;
 PERFORM app_private.require_capture_pack_creator(c.input_snapshot_id,org,actor);


 SELECT * INTO pack FROM public.review_pack_identities WHERE cycle_id=cid;
 IF FOUND THEN
  IF pack.admitted_revision IS DISTINCT FROM expected
   OR pack.organization_id IS DISTINCT FROM org OR pack.created_by_id IS DISTINCT FROM actor
   OR pack.manifest->>'cycle_id' IS DISTINCT FROM cid::text
   OR pack.manifest->>'organization_id' IS DISTINCT FROM org::text
   OR pack.manifest->'snapshot'->>'snapshot_id' IS DISTINCT FROM c.input_snapshot_id::text
   OR pack.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(pack.manifest),'UTF8')),'hex') THEN
   RAISE EXCEPTION 'Frozen review identity replay changed'; END IF;
  PERFORM app_private.validate_capture_proposal_pack(pack.id,org);
  PERFORM app_private.require_capture_proposal_freeze_authority(org,actor);
  RETURN pack.id;
 END IF;
 snapshot:=app_private.review_snapshot_manifest_capture(c.input_snapshot_id,org);

 manifest:=jsonb_build_object('schema','stewardence.review_pack.v4',
  'proposal_contract_version','stewardence.core_review_proposal.v1','cycle_id',c.id::text,
  'organization_id',org::text,'baseline_pack_id',NULL,'snapshot',snapshot,
  'capture',app_private.review_capture_binding(c.input_snapshot_id,org),
  'selected_proposals',app_private.review_capture_proposal_selection_v1(c.input_snapshot_id,org),
  'selected_decisions',app_private.review_capture_decision_selection_v2(c.input_snapshot_id,org),
  'selection_scope','issued_capture_proposals','artifact_state','not_created','baseline_promotion','blocked');

 SELECT * INTO event FROM public.review_cycle_events WHERE cycle_id=cid ORDER BY revision DESC LIMIT 1;
 IF NOT FOUND OR event.revision<>expected OR event.state<>'OPEN'
  OR event.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(event.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Review state compare and swap failed'; END IF;
 IF EXISTS(SELECT 1 FROM public.review_cycles pending WHERE pending.organization_id=org AND pending.id<>cid
  AND (SELECT state FROM public.review_cycle_events e WHERE e.cycle_id=pending.id ORDER BY revision DESC LIMIT 1) IN ('FINALIZATION_REQUESTED','FROZEN','ARTIFACT_PENDING')) THEN
  RAISE EXCEPTION 'Review frozen pending capacity exhausted'; END IF;
 SELECT p.* INTO coverage FROM public.billing_paid_coverage p
  JOIN public.billing_subscription s ON s.id=p.subscription_id
  JOIN public.billing_billingcustomer b ON b.id=s.billing_customer_id
  JOIN public.billing_paid_coverage_authority a ON a.id=1 AND a.stripe_account_id=p.stripe_account_id AND a.livemode=p.livemode
  WHERE s.organization_id=org AND b.user_id=actor AND s.portfolio='core'
   AND app_private.paid_subscription_access(s.id) AND p.stripe_subscription_id=s.stripe_subscription_id
   AND p.stripe_customer_id=b.stripe_customer_id AND p.service_start<=clock_timestamp() AND p.service_end>clock_timestamp()
  ORDER BY p.service_start DESC,p.service_end DESC,p.id LIMIT 1 FOR KEY SHARE OF p;
 IF NOT FOUND THEN RAISE EXCEPTION 'Admitted billing interval required for review reservation'; END IF;
 IF (SELECT count(*) FROM public.review_capacity_reservations r
  JOIN public.billing_paid_coverage p ON p.id=r.paid_coverage_id
  WHERE r.organization_id=org AND r.state IN ('reserved','reconciliation','consumed')
   AND p.subscription_id=coverage.subscription_id AND p.stripe_subscription_id=coverage.stripe_subscription_id
   AND p.service_start=coverage.service_start AND p.service_end=coverage.service_end)>=12 THEN
  RAISE EXCEPTION 'Review billing interval capacity exhausted'; END IF;
 SELECT coalesce(sum(size_bytes),0) INTO retained FROM public.report_artifacts WHERE organization_id=org;
 SELECT coalesce(sum(reserved_bytes),0) INTO reserved FROM public.review_capacity_reservations
  WHERE organization_id=org AND coalesce((SELECT e.state FROM public.review_reservation_events e WHERE e.reservation_id=review_capacity_reservations.id ORDER BY revision DESC LIMIT 1),state) IN ('reserved','reconciliation');
 IF retained+reserved+16777216>3221225472 THEN RAISE EXCEPTION 'Review storage reservation capacity exhausted'; END IF;
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Review paid owner admission unavailable'; END IF;
 PERFORM app_private.require_capture_proposal_freeze_authority(org,actor);
 rid:=gen_random_uuid(); pid:=gen_random_uuid();
 INSERT INTO public.review_capacity_reservations(id,organization_id,created_by_id,created_at,cycle_id,paid_coverage_id,reserved_bytes,state)
 VALUES(rid,org,actor,clock_timestamp(),cid,coverage.id,16777216,'reserved');
 payload:=jsonb_build_object('schema','stewardence.review_reservation_event.v2','reservation_id',rid::text,
  'cycle_id',cid::text,'revision',1,'state','reserved','paid_coverage_id',coverage.id::text,'reserved_bytes',16777216);
 INSERT INTO public.review_reservation_events(id,organization_id,created_by_id,created_at,reservation_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),org,actor,clock_timestamp(),rid,1,'reserved',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 payload:=jsonb_build_object('schema','stewardence.review_cycle_event.v2','cycle_id',cid::text,
  'revision',2,'state','FINALIZATION_REQUESTED','reservation_id',rid::text);
 INSERT INTO public.review_cycle_events(id,organization_id,created_by_id,created_at,cycle_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),org,actor,clock_timestamp(),cid,2,'FINALIZATION_REQUESTED',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 INSERT INTO public.review_pack_identities(id,organization_id,created_by_id,created_at,cycle_id,admitted_revision,manifest,sha256)
 VALUES(pid,org,actor,clock_timestamp(),cid,expected,manifest,
  encode(sha256(convert_to(app_private.queue_canonical(manifest),'UTF8')),'hex'));
 payload:=jsonb_build_object('schema','stewardence.review_cycle_event.v2','cycle_id',cid::text,
  'revision',3,'state','FROZEN','pack_id',pid::text,'manifest_sha256',
  encode(sha256(convert_to(app_private.queue_canonical(manifest),'UTF8')),'hex'));
 INSERT INTO public.review_cycle_events(id,organization_id,created_by_id,created_at,cycle_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),org,actor,clock_timestamp(),cid,3,'FROZEN',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 PERFORM app_private.require_capture_proposal_freeze_authority(org,actor);
 RETURN pid;
END;$fn$;
ALTER FUNCTION app_private.freeze_capture_proposal_review_cycle(uuid,uuid,uuid,integer) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.freeze_capture_proposal_review_cycle(uuid,uuid,uuid,integer) FROM PUBLIC,agentledger_worker;
REVOKE ALL ON FUNCTION app_private.freeze_capture_proposal_review_cycle(uuid,uuid,uuid,integer) FROM agentledger_app,agentledger_worker,agentledger_billing_admission;


CREATE FUNCTION app_private.capture_exposure_review_v1(record jsonb,captured timestamptz) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE questions jsonb:='[]'::jsonb; field text; label text; outcome text; explanation text; fields jsonb;
 body jsonb; whitespace text:=chr(9)||chr(10)||chr(11)||chr(12)||chr(13)||chr(28)||chr(29)||chr(30)||chr(31)||chr(32)||chr(133)||chr(160)||chr(5760)||chr(8192)||chr(8193)||chr(8194)||chr(8195)||chr(8196)||chr(8197)||chr(8198)||chr(8199)||chr(8200)||chr(8201)||chr(8202)||chr(8232)||chr(8233)||chr(8239)||chr(8287)||chr(12288);
BEGIN
 PERFORM app_private.validate_capture_proposal_record_v1(record,captured);
 FOREACH field IN ARRAY ARRAY['business_owner','business_purpose','data_categories','permissions','capabilities','approval','account_identity','access_removal'] LOOP
  fields:=jsonb_build_array(field);
  CASE field WHEN 'business_owner' THEN label:='Responsible person'; WHEN 'business_purpose' THEN label:='Business purpose';
   WHEN 'data_categories' THEN label:='Information categories'; WHEN 'permissions' THEN label:='Permissions'; WHEN 'capabilities' THEN label:='Actions'; ELSE label:=NULL; END CASE;
  IF field=ANY(ARRAY['business_owner','business_purpose']) THEN
   IF record->'provenance'->>field IS DISTINCT FROM 'Declared' THEN outcome:='UNKNOWN'; explanation:=label||' has not been declared.';
   ELSIF btrim(record->>field,whitespace)='' THEN outcome:='CONCERN'; explanation:=label||' is blank in the declaration.';
   ELSE outcome:='PASS'; explanation:=label||' is recorded as a declaration.'; END IF;
  ELSIF field=ANY(ARRAY['data_categories','permissions','capabilities']) THEN
   IF record->'provenance'->>field IS DISTINCT FROM 'Declared' THEN outcome:='UNKNOWN'; explanation:=label||' have not been declared.';
   ELSE outcome:='PASS'; explanation:=label||' are recorded as declarations, including any stated empty list.'; END IF;
  ELSIF field='approval' THEN
   fields:='["human_approval","autonomy_level","capabilities","permissions"]'::jsonb;
   IF record->'provenance'->>'human_approval' IS DISTINCT FROM 'Declared' OR record->'provenance'->>'autonomy_level' IS DISTINCT FROM 'Declared'
    OR record->'provenance'->>'capabilities' IS DISTINCT FROM 'Declared' OR record->'provenance'->>'permissions' IS DISTINCT FROM 'Declared' THEN
    outcome:='UNKNOWN'; explanation:='The declared action and approval boundary is incomplete.';
   ELSIF record->'capabilities'='[]'::jsonb AND record->'permissions'='[]'::jsonb AND record->>'autonomy_level'='0' THEN
    outcome:='NOT_APPLICABLE'; explanation:='No actions or permissions are declared; approval applicability follows that declaration only.';
   ELSIF record->'human_approval'='true'::jsonb THEN outcome:='PASS'; explanation:='A human approval requirement is declared; enforcement has not been checked.';
   ELSE outcome:='CONCERN'; explanation:='Actions or permissions are declared without a human approval requirement; review the intended boundary.'; END IF;
  ELSIF field='account_identity' THEN outcome:='UNKNOWN'; fields:='[]'::jsonb; explanation:='This captured inventory schema does not identify the executing account or principal.';
  ELSE outcome:='UNKNOWN'; fields:='[]'::jsonb; explanation:='This captured inventory schema does not record an access-removal procedure.';
  END IF;
  questions:=questions||jsonb_build_array(jsonb_build_object('question_id',field,'outcome',outcome,'explanation',explanation,
   'source_fields',fields,'basis',CASE WHEN outcome='UNKNOWN' THEN 'unknown' ELSE 'customer_declaration' END,'verification','not_established'));
 END LOOP;
 body:=jsonb_build_object('schema','core.exposure.declarations.v1','inventory_item_id',record->'id',
  'record_sha256',encode(sha256(convert_to(app_private.queue_canonical(record),'UTF8')),'hex'),'questions',questions,'authority','proposal_only','verification','not_established');
 RETURN body||jsonb_build_object('sha256',encode(sha256(convert_to(app_private.queue_canonical(body),'UTF8')),'hex'));
END;$fn$;
ALTER FUNCTION app_private.capture_exposure_review_v1(jsonb,timestamptz) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_exposure_review_v1(jsonb,timestamptz) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.capture_proposal_request_projection(request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE q public.review_artifact_requests%ROWTYPE; p public.review_pack_identities%ROWTYPE; c public.review_cycles%ROWTYPE;
 s public.assessment_snapshots%ROWTYPE; r public.reports%ROWTYPE; j public.background_jobs%ROWTYPE;
BEGIN
 SELECT * INTO q FROM public.review_artifact_requests WHERE id=request_id;
 SELECT * INTO p FROM public.review_pack_identities WHERE id=q.pack_id AND organization_id=q.organization_id;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=q.organization_id;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=c.input_snapshot_id AND organization_id=q.organization_id;
 SELECT * INTO r FROM public.reports WHERE id=q.report_id AND organization_id=q.organization_id;
 SELECT * INTO j FROM public.background_jobs WHERE id=q.job_id AND organization_id=q.organization_id;
 PERFORM app_private.validate_capture_proposal_pack(p.id,q.organization_id);
 IF q.id IS NULL OR r.id IS NULL OR j.id IS NULL OR q.promote_baseline IS DISTINCT FROM false
  OR p.created_by_id IS DISTINCT FROM q.created_by_id OR c.created_by_id IS DISTINCT FROM q.created_by_id
  OR r.created_by_id IS DISTINCT FROM q.created_by_id OR s.created_by_id IS DISTINCT FROM q.created_by_id
  OR q.manifest_sha256 IS DISTINCT FROM p.sha256 OR r.assessment_snapshot_id IS DISTINCT FROM s.id
  OR j.job_type IS DISTINCT FROM 'report_generation' OR j.payload IS DISTINCT FROM jsonb_build_object('report_id',r.id::text)
  OR j.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(j.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Capture proposal projection effect pins invalid'; END IF;
 RETURN jsonb_build_object('schema','stewardence.review_worker_projection.v3','request_id',q.id::text,'job_id',j.id::text,
  'report_id',r.id::text,'organization_id',q.organization_id::text,'pack_id',p.id::text,
  'manifest',p.manifest,'manifest_sha256',p.sha256,'snapshot_input',s.input_payload,'snapshot_result',s.result_payload,
  'selected_proposals',p.manifest->'selected_proposals','selected_decisions',p.manifest->'selected_decisions');
END;$fn$;
ALTER FUNCTION app_private.capture_proposal_request_projection(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_proposal_request_projection(uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.capture_proposal_preflight_context(request_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE projection jsonb; metadata jsonb; exposure jsonb; r public.reports%ROWTYPE; captured timestamptz;
BEGIN
 projection:=app_private.capture_proposal_request_projection(request_id);
 SELECT * INTO r FROM public.reports WHERE id=(projection->>'report_id')::uuid AND organization_id=(projection->>'organization_id')::uuid;
 captured:=(projection->'manifest'->'snapshot'->>'captured_at')::timestamptz;
 metadata:=jsonb_build_object('report_identifier',r.report_identifier,'organization_display_name',r.organization_display_name,
  'assessment_date',projection->'manifest'->'snapshot'->'captured_at','assessment_id',projection->'manifest'->'snapshot'->'assessment_id',
  'assessment_version',projection->'manifest'->'snapshot'->'assessment_version','assessment_snapshot_id',projection->'manifest'->'snapshot'->'snapshot_id',
  'input_sha256',projection->'manifest'->'snapshot'->'input_sha256','result_sha256',projection->'manifest'->'snapshot'->'result_sha256');
 SELECT jsonb_agg(app_private.capture_exposure_review_v1(value,captured) ORDER BY ord)
  INTO exposure FROM jsonb_array_elements(projection->'snapshot_input'->'inventory') WITH ORDINALITY t(value,ord);
 RETURN jsonb_build_object('context_version','AL-REVIEW-PACK-CONTEXT-3','title','Frozen Tool Exposure Evidence Pack',
  'metadata',metadata,'projection',projection,'exposure_reviews',exposure);
END;$fn$;
ALTER FUNCTION app_private.capture_proposal_preflight_context(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_proposal_preflight_context(uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.freeze_review_cycle(cid uuid,org uuid,actor uuid,expected integer) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE c public.review_cycles%ROWTYPE; schema text;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Review freeze context invalid'; END IF;
 PERFORM app_private.require_review_owner(org,actor);
 SELECT * INTO c FROM public.review_cycles WHERE id=cid AND organization_id=org;
 SELECT manifest->>'schema' INTO schema FROM public.review_pack_identities WHERE cycle_id=cid AND organization_id=org;
 IF schema IN ('stewardence.review_pack.v2','stewardence.review_pack.v3') THEN
  RETURN app_private.freeze_review_cycle_pre_v4(cid,org,actor,expected); END IF;
 IF schema='stewardence.review_pack.v4' OR (schema IS NULL AND EXISTS(SELECT 1 FROM public.review_capture_proposal_receipts WHERE snapshot_id=c.input_snapshot_id AND organization_id=org)) THEN
  RETURN app_private.freeze_capture_proposal_review_cycle(cid,org,actor,expected); END IF;
 IF schema IS NOT NULL THEN RAISE EXCEPTION 'Unsupported frozen review version'; END IF;
 RETURN app_private.freeze_review_cycle_pre_v4(cid,org,actor,expected);
END;$fn$;
ALTER FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) TO agentledger_app;

CREATE FUNCTION app_private.request_review_artifact(pid uuid,org uuid,actor uuid,expected integer,rid uuid,jid uuid,promote boolean) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE schema text; target uuid; sid uuid; context jsonb; payload_bytes integer;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Review request context invalid'; END IF;
 SELECT manifest->>'schema' INTO schema FROM public.review_pack_identities WHERE id=pid AND organization_id=org;
 IF schema IN ('stewardence.review_pack.v2','stewardence.review_pack.v3') THEN
  RETURN app_private.request_review_artifact_pre_v4(pid,org,actor,expected,rid,jid,promote); END IF;
 IF schema IS DISTINCT FROM 'stewardence.review_pack.v4' OR promote IS DISTINCT FROM false THEN RAISE EXCEPTION 'Capture proposal request meaning unavailable'; END IF;
 PERFORM app_private.require_review_owner(org,actor);
 PERFORM 1 FROM public.review_lifecycle_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.review_core_proposal_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 SELECT c.input_snapshot_id INTO sid FROM public.review_cycles c JOIN public.review_pack_identities p ON p.cycle_id=c.id WHERE p.id=pid AND p.organization_id=org;
 PERFORM 1 FROM public.assessment_snapshots WHERE id=sid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.review_pack_identities WHERE id=pid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.review_capture_proposal_receipts WHERE snapshot_id=sid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.reports WHERE id=rid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.background_jobs WHERE id=jid AND organization_id=org FOR KEY SHARE;
 PERFORM app_private.require_capture_pack_creator(sid,org,actor);
 PERFORM app_private.validate_capture_proposal_pack(pid,org);
 target:=app_private.request_review_artifact_v2(pid,org,actor,expected,rid,jid,false);
 context:=app_private.capture_proposal_preflight_context(target);
 payload_bytes:=octet_length(convert_to(app_private.queue_canonical(context),'UTF8'));
 IF payload_bytes>1048576 THEN RAISE EXCEPTION 'Frozen capture context is % bytes; maximum is 1048576; request not admitted',payload_bytes; END IF;
 PERFORM app_private.require_capture_proposal_freeze_authority(org,actor);
 IF NOT EXISTS(SELECT 1 FROM public.review_lifecycle_gate WHERE id=1 AND enabled) THEN RAISE EXCEPTION 'Capture proposal request lifecycle disabled after waits'; END IF;
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) TO agentledger_app;

CREATE FUNCTION app_private.capture_proposal_pack_projection(jid uuid,token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE target uuid; projection jsonb;
BEGIN
 target:=app_private.review_job_target(jid,token);
 IF target IS NULL THEN RAISE EXCEPTION 'Capture proposal job request required'; END IF;
 projection:=app_private.capture_proposal_request_projection(target);
 IF app_private.review_job_target(jid,token) IS DISTINCT FROM target
  OR NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled) THEN
  RAISE EXCEPTION 'Capture proposal projection authority unavailable'; END IF;
 RETURN projection;
END;$fn$;
ALTER FUNCTION app_private.capture_proposal_pack_projection(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_proposal_pack_projection(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.review_pack_projection(jid uuid,token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE target uuid; schema text;
BEGIN
 target:=app_private.review_job_target(jid,token);
 IF target IS NULL THEN RETURN app_private.review_pack_projection_pre_v4(jid,token); END IF;
 SELECT p.manifest->>'schema' INTO schema FROM public.review_pack_identities p JOIN public.review_artifact_requests q ON q.pack_id=p.id WHERE q.id=target;
 IF schema IN ('stewardence.review_pack.v2','stewardence.review_pack.v3') THEN RETURN app_private.review_pack_projection_pre_v4(jid,token); END IF;
 IF schema='stewardence.review_pack.v4' THEN RETURN app_private.capture_proposal_pack_projection(jid,token); END IF;
 RAISE EXCEPTION 'Unsupported review projection version';
END;$fn$;
ALTER FUNCTION app_private.review_pack_projection(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_pack_projection(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.review_pack_projection(uuid,uuid) TO agentledger_worker;

CREATE FUNCTION app_private.complete_review_pack(request_id uuid,artifact_id uuid,jid uuid,worker_id text,token uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE q public.review_artifact_requests%ROWTYPE; schema text; target uuid;
BEGIN
 SELECT * INTO q FROM public.review_artifact_requests WHERE id=request_id AND organization_id=app_private.current_organization_id();
 SELECT manifest->>'schema' INTO schema FROM public.review_pack_identities WHERE id=q.pack_id AND organization_id=q.organization_id;
 IF schema IN ('stewardence.review_pack.v2','stewardence.review_pack.v3') THEN RETURN app_private.complete_review_pack_pre_v4(request_id,artifact_id,jid,worker_id,token); END IF;
 IF schema IS DISTINCT FROM 'stewardence.review_pack.v4' OR q.promote_baseline IS DISTINCT FROM false THEN RAISE EXCEPTION 'Capture proposal completion meaning unavailable'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||q.organization_id::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('review:'||q.organization_id::text||':capacity',0));
 PERFORM 1 FROM public.review_lifecycle_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.review_core_proposal_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.accounts_user WHERE id=q.created_by_id FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=q.organization_id FOR KEY SHARE;
 PERFORM 1 FROM public.review_artifact_requests WHERE id=q.id FOR KEY SHARE;
 PERFORM 1 FROM public.review_pack_identities WHERE id=q.pack_id FOR KEY SHARE;
 PERFORM 1 FROM public.reports WHERE id=q.report_id AND organization_id=q.organization_id FOR KEY SHARE;
 PERFORM 1 FROM public.report_artifacts WHERE id=artifact_id AND report_id=q.report_id AND organization_id=q.organization_id FOR KEY SHARE;
 PERFORM 1 FROM public.review_capacity_reservations r JOIN public.review_pack_identities p ON p.cycle_id=r.cycle_id WHERE p.id=q.pack_id FOR KEY SHARE OF r;
 PERFORM app_private.validate_capture_proposal_pack(q.pack_id,q.organization_id);
 target:=app_private.complete_review_pack_v2(request_id,artifact_id,jid,worker_id,token);
 IF app_private.review_job_target(jid,token) IS DISTINCT FROM q.id THEN RAISE EXCEPTION 'Capture proposal completion lease unavailable after waits'; END IF;
 PERFORM app_private.require_capture_proposal_freeze_authority(q.organization_id,q.created_by_id);
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) FROM PUBLIC,agentledger_app,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) TO agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0005_capture_proposal_admission"),
        ("jobs", "0016_capture_decisions"),
    ]
    operations = [migrations.RunSQL(SQL)]
