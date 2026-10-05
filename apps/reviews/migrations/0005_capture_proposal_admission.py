"""Receipt-bound server proposal recomputation; no worker issuance authority."""

import uuid

import django.db.models.deletion
import rfc8785
from django.conf import settings
from django.db import migrations, models

from apps.assessments.capture_v1 import _rules

RULES = rfc8785.dumps(_rules()).decode()

SQL = r"""
DO $extension$
BEGIN
 IF EXISTS(SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
           WHERE e.extname='uuid-ossp' AND n.nspname<>'app_private') THEN
  RAISE EXCEPTION 'Proposal UUIDv5 requires uuid-ossp in app_private; existing extension is not relocated';
 END IF;
END;$extension$;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA app_private;
DO $privileges$
DECLARE member record;
BEGIN
 FOR member IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_depend d ON d.objid=p.oid
  JOIN pg_extension e ON e.oid=d.refobjid WHERE d.classid='pg_proc'::regclass AND d.deptype='e' AND e.extname='uuid-ossp' LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission',member.signature);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO agentledger_owner',member.signature);
 END LOOP;
END;$privileges$;

ALTER TABLE review_core_proposal_gate OWNER TO agentledger_owner;
ALTER TABLE review_capture_proposal_receipts OWNER TO agentledger_owner;
REVOKE ALL ON review_core_proposal_gate,review_capture_proposal_receipts FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE review_core_proposal_gate ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_core_proposal_gate FORCE ROW LEVEL SECURITY;
ALTER TABLE review_capture_proposal_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_capture_proposal_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY proposal_gate_owner ON review_core_proposal_gate TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY proposal_receipt_owner ON review_capture_proposal_receipts TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY proposal_receipt_owner_read ON review_capture_proposal_receipts FOR SELECT TO agentledger_app
 USING(organization_id=app_private.current_organization_id() AND EXISTS(SELECT 1 FROM public.organizations_organizationmember
 WHERE organization_id=review_capture_proposal_receipts.organization_id AND user_id=app_private.current_user_id() AND role='owner'));
GRANT SELECT ON review_capture_proposal_receipts TO agentledger_app;
INSERT INTO review_core_proposal_gate(id,enabled) VALUES(1,false);
CREATE TRIGGER immutable_proposal_receipt BEFORE UPDATE OR DELETE ON review_capture_proposal_receipts
 FOR EACH ROW EXECUTE FUNCTION app_private.prevent_paid_coverage_mutation();

CREATE FUNCTION app_private.validate_capture_proposal_record_v1(record jsonb,captured timestamptz) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE fields text[]:=ARRAY['display_name','vendor_name','business_owner','department','user_count','business_purpose',
 'monthly_cost_cents','seat_count','connected_systems','data_categories','permissions','capabilities','autonomy_level','human_approval','status'];
 field text; value jsonb; basis text; entry jsonb;
BEGIN
 IF jsonb_typeof(record) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(record))<>22
  OR NOT record ?& (fields||ARRAY['id','product_id','source_type','declaration_contract','declaration_as_of','provenance','archived_at'])
  OR jsonb_typeof(record->'id') IS DISTINCT FROM 'string' OR record->>'id' IS DISTINCT FROM ((record->>'id')::uuid)::text
  OR record->'archived_at' IS DISTINCT FROM 'null'::jsonb OR record->'product_id' IS DISTINCT FROM 'null'::jsonb
  OR record->>'source_type' IS DISTINCT FROM 'manual' OR record->>'declaration_contract' IS DISTINCT FROM 'core.inventory.declarations.v1'
  OR jsonb_typeof(record->'declaration_as_of') IS DISTINCT FROM 'string' OR record->>'declaration_as_of' !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
  OR (record->>'declaration_as_of')::date>(captured AT TIME ZONE 'UTC')::date
  OR jsonb_typeof(record->'provenance') IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(record->'provenance'))<>17
  OR NOT (record->'provenance') ?& (fields||ARRAY['product_id','source_type'])
  OR record->'provenance'->>'product_id' IS DISTINCT FROM 'Unknown' OR record->'provenance'->>'source_type' IS DISTINCT FROM 'Declared' THEN
  RAISE EXCEPTION 'Exact permanent capture record required'; END IF;
 FOREACH field IN ARRAY fields LOOP
  value:=record->field; basis:=record->'provenance'->>field;
  IF basis='Unknown' THEN
   IF value IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Unknown capture values must be null'; END IF;
  ELSIF basis='Declared' THEN
   IF field=ANY(ARRAY['connected_systems','data_categories','permissions','capabilities']) THEN
    IF jsonb_typeof(value) IS DISTINCT FROM 'array' OR jsonb_array_length(value)<>(SELECT count(DISTINCT v) FROM jsonb_array_elements(value) v) THEN
     RAISE EXCEPTION 'Declared capture lists invalid'; END IF;
    FOR entry IN SELECT v FROM jsonb_array_elements(value) v LOOP
     IF jsonb_typeof(entry) IS DISTINCT FROM 'string' OR length(entry#>>'{}') NOT BETWEEN 1 AND 200 THEN
      RAISE EXCEPTION 'Declared capture list member invalid'; END IF;
    END LOOP;
   ELSIF field=ANY(ARRAY['user_count','seat_count','monthly_cost_cents','autonomy_level']) THEN
    IF jsonb_typeof(value) IS DISTINCT FROM 'number' OR value::text !~ '^[0-9]+$'
     OR (value::text)::numeric>(CASE WHEN field='autonomy_level' THEN 4 ELSE 2147483647 END) THEN
     RAISE EXCEPTION 'Declared capture integer invalid'; END IF;
   ELSIF field='human_approval' THEN
    IF jsonb_typeof(value) IS DISTINCT FROM 'boolean' THEN RAISE EXCEPTION 'Declared capture boolean invalid'; END IF;
   ELSIF jsonb_typeof(value) IS DISTINCT FROM 'string' OR length(value#>>'{}')>(CASE WHEN field='business_purpose' THEN 4096 ELSE 255 END) THEN
    RAISE EXCEPTION 'Declared capture text invalid'; END IF;
  ELSE RAISE EXCEPTION 'Unknown capture provenance vocabulary';
  END IF;
 END LOOP;
 RETURN true;
END;$fn$;
ALTER FUNCTION app_private.validate_capture_proposal_record_v1(jsonb,timestamptz) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.validate_capture_proposal_record_v1(jsonb,timestamptz) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.capture_policy_results_v1(record jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE rules jsonb:=$rules$__RULES__$rules$::jsonb; rule jsonb; condition jsonb; missing jsonb;
 field text; actual jsonb; matched boolean; tested boolean; result jsonb; outputs jsonb:='[]'::jsonb;
BEGIN
 FOR rule IN SELECT value FROM jsonb_array_elements(rules) LOOP
  SELECT coalesce(jsonb_agg(to_jsonb(fields.field) ORDER BY fields.field COLLATE "C"),'[]'::jsonb) INTO missing FROM
   (SELECT DISTINCT value->>'field' AS field FROM jsonb_array_elements(rule->'conditions') WHERE
    record->'provenance'->>(value->>'field') IS DISTINCT FROM 'Declared'
    OR record->(value->>'field') IS NULL OR record->(value->>'field')='null'::jsonb) fields;
  IF missing<>'[]'::jsonb THEN
   result:=jsonb_build_object('rule_id',rule->'rule_id','rule_version',rule->'version','result','UNKNOWN',
    'severity',NULL,'explanation','Required declarations are not established.','recommended_remediation',NULL,'effects','[]'::jsonb,'missing_fields',missing);
  ELSE
   matched:=true;
   FOR condition IN SELECT value FROM jsonb_array_elements(rule->'conditions') LOOP
    field:=condition->>'field'; actual:=record->field;
    CASE condition->>'operator'
     WHEN 'contains' THEN
      IF jsonb_typeof(actual)<>'array' THEN RAISE EXCEPTION 'Permanent policy premise type invalid'; END IF;
      tested:=actual @> jsonb_build_array(condition->'value');
     WHEN 'is_false' THEN
      IF jsonb_typeof(actual)<>'boolean' THEN RAISE EXCEPTION 'Permanent policy boolean premise invalid'; END IF;
      tested:=actual='false'::jsonb;
     WHEN 'greater_than_or_equal' THEN
      IF jsonb_typeof(actual)<>'number' OR actual::text !~ '^[0-9]+$' THEN RAISE EXCEPTION 'Permanent policy integer premise invalid'; END IF;
      tested:=(actual::text)::integer >= (condition->>'value')::integer;
     WHEN 'equals' THEN tested:=actual=condition->'value';
     WHEN 'not_equals' THEN tested:=actual<>condition->'value';
     ELSE RAISE EXCEPTION 'Unsupported permanent policy operator';
    END CASE;
    matched:=matched AND tested;
   END LOOP;
   result:=jsonb_build_object('rule_id',rule->'rule_id','rule_version',rule->'version',
    'result',CASE WHEN matched THEN rule->>'result_on_match' ELSE 'NOT_APPLICABLE' END,
    'severity',CASE WHEN NOT matched THEN 'NONE' WHEN rule->>'severity'='1' THEN 'LOW'
      WHEN rule->>'severity'='2' THEN 'MODERATE' WHEN rule->>'severity'='3' THEN 'HIGH'
      WHEN rule->>'severity'='4' THEN 'CRITICAL' ELSE 'NONE' END,
    'explanation',rule->'explanation','recommended_remediation',rule->'remediation',
    'effects',CASE WHEN matched THEN rule->'effects' ELSE '[]'::jsonb END,'missing_fields','[]'::jsonb);
  END IF;
  outputs:=outputs||jsonb_build_array(result);
 END LOOP;
 RETURN outputs;
END;$fn$;
ALTER FUNCTION app_private.capture_policy_results_v1(jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_policy_results_v1(jsonb) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.capture_proposal_v1(inputs jsonb,sid uuid,input_hash text,result_hash text,record jsonb,source jsonb,action text,description text,severity jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE identity uuid; payload jsonb; contract text:='stewardence.core_review_proposal.v1';
BEGIN
 identity:=app_private.uuid_generate_v5('0b59c53e-e126-56e6-b67c-c0d5041355c2'::uuid,
  app_private.queue_canonical(jsonb_build_object('snapshot_id',sid::text,'contract',contract,
   'inventory_item_id',record->'id','source_class',source->'class','source_identity',source->'identity','source_digest',source->'digest')));
 payload:=jsonb_build_object('schema',contract,'proposal_id',identity::text,'organization_id',inputs->'organization_id',
  'snapshot_id',sid::text,'snapshot_input_sha256',input_hash,'snapshot_result_sha256',result_hash,
  'inventory_item_id',record->'id','record_sha256',encode(sha256(convert_to(app_private.queue_canonical(record),'UTF8')),'hex'),
  'source',source,'action_kind',action,'proposal_text',description,'authority','proposal_only','verification','not_established',
  'original_outcome',source->'outcome','source_state_immutable',true,'resolution_effect','none','owner_statement_only',true,'resolution_verified',false);
 IF severity IS NOT NULL THEN payload:=payload||jsonb_build_object('severity',severity); END IF;
 RETURN payload||jsonb_build_object('sha256',encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
END;$fn$;
ALTER FUNCTION app_private.capture_proposal_v1(jsonb,uuid,text,text,jsonb,jsonb,text,text,jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_proposal_v1(jsonb,uuid,text,text,jsonb,jsonb,text,text,jsonb) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.recompute_capture_proposals_v1(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; inputs jsonb; record jsonb; rule jsonb; result jsonb; policy jsonb;
 rules jsonb:=$rules$__RULES__$rules$::jsonb; expected_ruleset jsonb; qualification jsonb; qualification_hash text;
 question jsonb; questions jsonb; source jsonb; definition jsonb; fields jsonb; field text; description text; action text;
 proposals jsonb:='[]'::jsonb; accounting boolean;
BEGIN
 PERFORM app_private.review_capture_binding(sid,org);
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 IF jsonb_typeof(s.input_payload) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(s.input_payload))<>14
  OR NOT s.input_payload ?& ARRAY['snapshot_schema_version','capture_contract','assessment','organization_id','created_by_id','captured_at',
   'industry_applicability','workflow_profile','inventory','evidence_references','benefit_model','rulesets','risk_configuration','engine_versions']
  OR jsonb_typeof(s.result_payload) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(s.result_payload))<>6
  OR NOT s.result_payload ?& ARRAY['snapshot_schema_version','capture_contract','assessment','industry_applicability','benefit_model','inventory_results']
  OR s.input_payload->'evidence_references' IS DISTINCT FROM '[]'::jsonb
  OR s.input_payload->'risk_configuration' IS DISTINCT FROM '{"state":"not_assessed"}'::jsonb
  OR jsonb_typeof(s.input_payload->'inventory') IS DISTINCT FROM 'array' OR jsonb_array_length(s.input_payload->'inventory') NOT BETWEEN 1 AND 100
  OR jsonb_typeof(s.result_payload->'inventory_results') IS DISTINCT FROM 'array'
  OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(s.input_payload->'inventory'))<>jsonb_array_length(s.input_payload->'inventory')
  OR (SELECT jsonb_agg(value->'id' ORDER BY ord) FROM jsonb_array_elements(s.input_payload->'inventory') WITH ORDINALITY t(value,ord))
   IS DISTINCT FROM (SELECT jsonb_agg(value->'inventory_item_id' ORDER BY ord) FROM jsonb_array_elements(s.result_payload->'inventory_results') WITH ORDINALITY t(value,ord)) THEN
  RAISE EXCEPTION 'Exact capture proposal payload and membership required'; END IF;
 FOR result IN SELECT value FROM jsonb_array_elements(s.result_payload->'inventory_results') LOOP
  IF jsonb_typeof(result) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(result))<>3
   OR NOT result ?& ARRAY['inventory_item_id','policy_results','risk']
   OR result->'risk' IS DISTINCT FROM '{"state":"not_assessed","score":null,"band":null}'::jsonb THEN
   RAISE EXCEPTION 'Capture proposal cannot admit new risk claims'; END IF;
 END LOOP;
 inputs:=s.input_payload; accounting:=inputs->'industry_applicability'->>'industry'='accounting_bookkeeping';
 IF inputs->'industry_applicability' IS DISTINCT FROM jsonb_build_object('industry',inputs->'industry_applicability'->'industry',
  'policy_state',CASE WHEN accounting THEN 'applicable' ELSE 'not_assessed' END,
  'reason',CASE WHEN accounting THEN 'accounting_pack_selected' ELSE 'no_qualified_industry_pack' END,'generic_exposure','core.exposure.declarations.v1') THEN
  RAISE EXCEPTION 'Frozen proposal applicability invalid'; END IF;
 expected_ruleset:=jsonb_build_object('name','accounting_and_bookkeeping','version','1.1.0','definitions',rules,
  'definitions_sha256',encode(sha256(convert_to(app_private.queue_canonical(rules),'UTF8')),'hex'));
 IF inputs->'rulesets' IS DISTINCT FROM jsonb_build_object('industry',CASE WHEN accounting THEN expected_ruleset ELSE 'null'::jsonb END,'organization','[]'::jsonb)
  OR inputs->'engine_versions' IS DISTINCT FROM (CASE WHEN accounting THEN
   '{"capture":"core.capture.declarations.v1","exposure":"core.exposure.declarations.v1","policy":"AL-POLICY-1","policy_admission":"core.capture.known_policy.v1"}'::jsonb
   ELSE '{"capture":"core.capture.declarations.v1","exposure":"core.exposure.declarations.v1"}'::jsonb END) THEN
  RAISE EXCEPTION 'Permanent proposal rule or engine pins invalid'; END IF;
 qualification:=jsonb_build_object('schema','stewardence.core_review_proposal_applicability.v1',
  'industry_applicability',inputs->'industry_applicability','ruleset',inputs->'rulesets'->'industry','engine_versions',inputs->'engine_versions');
 qualification_hash:=encode(sha256(convert_to(app_private.queue_canonical(qualification),'UTF8')),'hex');
 FOR record IN SELECT value FROM jsonb_array_elements(inputs->'inventory') LOOP
  PERFORM app_private.validate_capture_proposal_record_v1(record,s.captured_at);
  SELECT value->'policy_results' INTO policy FROM jsonb_array_elements(s.result_payload->'inventory_results') WHERE value->>'inventory_item_id'=record->>'id';
  IF policy IS DISTINCT FROM (CASE WHEN accounting THEN app_private.capture_policy_results_v1(record) ELSE '[]'::jsonb END) THEN
   RAISE EXCEPTION 'Frozen policy result differs from independent permanent recomputation'; END IF;
  questions:='[]'::jsonb;
  FOREACH field IN ARRAY ARRAY['business_owner','business_purpose'] LOOP
   IF record->'provenance'->>field IS DISTINCT FROM 'Declared' THEN
    questions:=questions||jsonb_build_array(jsonb_build_object('question_id',field,'outcome','UNKNOWN',
     'explanation',CASE WHEN field='business_owner' THEN 'Responsible person has not been declared.' ELSE 'Business purpose has not been declared.' END,
     'source_fields',jsonb_build_array(field),'basis','unknown','verification','not_established'));
   ELSIF jsonb_typeof(record->field) IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'Exposure declaration text type invalid'; END IF;
  END LOOP;
  questions:=questions||jsonb_build_array(jsonb_build_object('question_id','account_identity','outcome','UNKNOWN',
   'explanation','This captured inventory schema does not identify the executing account or principal.',
   'source_fields','[]'::jsonb,'basis','unknown','verification','not_established'))||
   jsonb_build_array(jsonb_build_object('question_id','access_removal','outcome','UNKNOWN',
   'explanation','This captured inventory schema does not record an access-removal procedure.',
   'source_fields','[]'::jsonb,'basis','unknown','verification','not_established'));
  IF record->'provenance'->>'human_approval'='Declared' AND record->'provenance'->>'autonomy_level'='Declared'
   AND record->'provenance'->>'capabilities'='Declared' AND record->'provenance'->>'permissions'='Declared' THEN
   IF jsonb_typeof(record->'human_approval') IS DISTINCT FROM 'boolean' OR jsonb_typeof(record->'autonomy_level') IS DISTINCT FROM 'number'
    OR (record->>'autonomy_level') !~ '^[0-4]$' OR jsonb_typeof(record->'capabilities') IS DISTINCT FROM 'array'
    OR jsonb_typeof(record->'permissions') IS DISTINCT FROM 'array' THEN RAISE EXCEPTION 'Exposure approval premise invalid'; END IF;
   IF record->'human_approval'='false'::jsonb AND (record->'capabilities'<>'[]'::jsonb OR record->'permissions'<>'[]'::jsonb OR record->>'autonomy_level'<>'0') THEN
    questions:=questions||jsonb_build_array(jsonb_build_object('question_id','approval','outcome','CONCERN',
     'explanation','Actions or permissions are declared without a human approval requirement; review the intended boundary.',
     'source_fields','["human_approval","autonomy_level","capabilities","permissions"]'::jsonb,'basis','customer_declaration','verification','not_established'));
   END IF;
  END IF;
  FOR question IN SELECT value FROM jsonb_array_elements(questions) LOOP
   CASE question->>'question_id'
    WHEN 'business_owner' THEN action:='request_declaration'; description:='Record the responsible person as an owner declaration.';
    WHEN 'business_purpose' THEN action:='request_declaration'; description:='Record the business purpose as an owner declaration.';
    WHEN 'account_identity' THEN action:='request_evidence'; description:='Provide executing account or principal evidence for owner review.';
    WHEN 'access_removal' THEN action:='request_evidence'; description:='Provide access-removal or offboarding evidence for owner review.';
    WHEN 'approval' THEN action:='review_declared_boundary'; description:='Review the declared action and human approval boundary.';
    ELSE RAISE EXCEPTION 'Unsupported permanent proposal template';
   END CASE;
   definition:=jsonb_build_object('exposure_contract','core.exposure.declarations.v1','question_id',question->'question_id',
    'outcome',question->'outcome','action_kind',action,'proposal_text',description);
   source:=jsonb_build_object('class',CASE WHEN question->>'outcome'='UNKNOWN' THEN 'exposure_unknown' ELSE 'exposure_concern' END,
    'contract','core.exposure.declarations.v1','contract_version',1,'identity',question->'question_id',
    'digest',encode(sha256(convert_to(app_private.queue_canonical(question),'UTF8')),'hex'),
    'definition_sha256',encode(sha256(convert_to(app_private.queue_canonical(definition),'UTF8')),'hex'),
    'outcome',question->'outcome','source_fields',question->'source_fields');
   proposals:=proposals||jsonb_build_array(app_private.capture_proposal_v1(inputs,sid,s.input_sha256,s.result_sha256,record,source,action,description,NULL));
  END LOOP;
  IF accounting THEN
   FOR result IN SELECT value FROM jsonb_array_elements(policy) WHERE value->>'result'='FAIL' LOOP
    SELECT value INTO rule FROM jsonb_array_elements(rules) WHERE value->>'rule_id'=result->>'rule_id';
    SELECT jsonb_agg(to_jsonb(f.field) ORDER BY f.field COLLATE "C") INTO fields FROM (SELECT DISTINCT value->>'field' field FROM jsonb_array_elements(rule->'conditions')) f;
    source:=jsonb_build_object('class','accounting_fail','contract','accounting_and_bookkeeping','contract_version','1.1.0',
     'identity',result->'rule_id','rule_version',result->'rule_version',
     'digest',encode(sha256(convert_to(app_private.queue_canonical(result),'UTF8')),'hex'),
     'definition_sha256',encode(sha256(convert_to(app_private.queue_canonical(rule),'UTF8')),'hex'),
     'definitions_sha256',expected_ruleset->'definitions_sha256','outcome','FAIL','source_fields',fields,
     'applicability_contract','stewardence.core_review_proposal_applicability.v1',
     'applicability_sha256',encode(sha256(convert_to(app_private.queue_canonical(inputs->'industry_applicability'),'UTF8')),'hex'),
     'qualification_sha256',qualification_hash,'policy_engine',inputs->'engine_versions'->'policy','policy_admission',inputs->'engine_versions'->'policy_admission');
    proposals:=proposals||jsonb_build_array(app_private.capture_proposal_v1(inputs,sid,s.input_sha256,s.result_sha256,record,source,
     'address_qualified_failure',result->>'recommended_remediation',result->'severity'));
   END LOOP;
  END IF;
 END LOOP;
 RETURN (SELECT coalesce(jsonb_agg(value ORDER BY value->>'inventory_item_id' COLLATE "C",value->'source'->>'class' COLLATE "C",value->'source'->>'identity' COLLATE "C",value->>'proposal_id' COLLATE "C"),'[]'::jsonb) FROM jsonb_array_elements(proposals));
END;$fn$;
ALTER FUNCTION app_private.recompute_capture_proposals_v1(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.recompute_capture_proposals_v1(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.issue_core_exposure_proposals(rid uuid,org uuid,actor uuid,sid uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; capture public.assessment_capture_receipts%ROWTYPE;
 previous public.review_capture_proposal_receipts%ROWTYPE; revision public.core_action_card_revisions%ROWTYPE;
 cards jsonb; card_hash text; qualification_hash text; issued timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR rid IS NULL OR org IS NULL OR actor IS NULL OR sid IS NULL THEN
  RAISE EXCEPTION 'Proposal admission requires explicit identities and read committed'; END IF;
 IF org IS DISTINCT FROM app_private.current_organization_id() OR actor IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Proposal identity context invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':proposal:'||sid::text,0));
 PERFORM 1 FROM public.review_core_proposal_gate WHERE id=1 FOR SHARE;
 IF NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org) THEN
  RAISE EXCEPTION 'Proposal admission unavailable'; END IF;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org FOR KEY SHARE;
 SELECT * INTO capture FROM public.assessment_capture_receipts WHERE snapshot_id=sid AND organization_id=org FOR KEY SHARE;
 SELECT * INTO revision FROM public.core_action_card_revisions WHERE snapshot_id=sid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.organization_workflow_profiles WHERE organization_id=org FOR SHARE;
 cards:=app_private.recompute_capture_proposals_v1(sid,org);
 card_hash:=encode(sha256(convert_to(app_private.queue_canonical(cards),'UTF8')),'hex');
 qualification_hash:=encode(sha256(convert_to(app_private.queue_canonical(jsonb_build_object('schema','stewardence.core_review_proposal_applicability.v1',
  'industry_applicability',s.input_payload->'industry_applicability','ruleset',s.input_payload->'rulesets'->'industry','engine_versions',s.input_payload->'engine_versions')),'UTF8')),'hex');
 issued:=clock_timestamp();
 IF NOT EXISTS(SELECT 1 FROM public.review_core_proposal_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org)
  OR NOT EXISTS(SELECT 1 FROM public.organization_workflow_profiles WHERE organization_id=org)
  OR s.created_by_id IS DISTINCT FROM actor OR capture.created_by_id IS DISTINCT FROM actor OR s.captured_at>issued THEN
  RAISE EXCEPTION 'Proposal authority unavailable after waits'; END IF;
 SELECT * INTO previous FROM public.review_capture_proposal_receipts WHERE snapshot_id=sid AND organization_id=org;
 IF FOUND THEN
  IF revision.id IS DISTINCT FROM previous.revision_id OR revision.created_by_id IS DISTINCT FROM actor
   OR previous.created_by_id IS DISTINCT FROM actor OR previous.capture_receipt_id IS DISTINCT FROM capture.id
   OR previous.contract IS DISTINCT FROM 'stewardence.core_review_proposal.v1'
   OR previous.input_sha256 IS DISTINCT FROM s.input_sha256 OR previous.result_sha256 IS DISTINCT FROM s.result_sha256
   OR previous.revision_sha256 IS DISTINCT FROM card_hash OR previous.qualification_sha256 IS DISTINCT FROM qualification_hash
   OR revision.cards IS DISTINCT FROM cards OR revision.sha256 IS DISTINCT FROM card_hash OR revision.input_sha256 IS DISTINCT FROM s.result_sha256 THEN
   RAISE EXCEPTION 'Issued proposal replay pins invalid'; END IF;
  RETURN revision.id;
 END IF;
 IF revision.id IS NOT NULL THEN RAISE EXCEPTION 'Unissued legacy revision conflicts with proposal contract'; END IF;
 INSERT INTO public.core_action_card_revisions(id,organization_id,created_by_id,created_at,snapshot_id,input_sha256,cards,sha256)
 VALUES(rid,org,actor,issued,sid,s.result_sha256,cards,card_hash);
 INSERT INTO public.review_capture_proposal_receipts(id,organization_id,created_by_id,created_at,snapshot_id,revision_id,capture_receipt_id,
 contract,input_sha256,result_sha256,revision_sha256,qualification_sha256)
 VALUES(gen_random_uuid(),org,actor,issued,sid,rid,capture.id,'stewardence.core_review_proposal.v1',s.input_sha256,s.result_sha256,card_hash,qualification_hash);
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.issue_core_exposure_proposals(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_core_exposure_proposals(uuid,uuid,uuid,uuid) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_core_exposure_proposals(uuid,uuid,uuid,uuid) TO agentledger_app;
""".replace("__RULES__", RULES)


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0004_capture_pack_projection"),
        ("jobs", "0015_legacy_action_card_schema_fence"),
    ]
    operations = [
        migrations.CreateModel(
            name="CoreProposalAdmissionGate",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        primary_key=True, default=1, editable=False, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "review_core_proposal_gate",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1), name="review_proposal_gate_singleton"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CaptureProposalAdmissionReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True,
                        default=uuid.uuid4,
                        editable=False,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(editable=False)),
                ("contract", models.CharField(max_length=80, editable=False)),
                ("input_sha256", models.CharField(max_length=64, editable=False)),
                ("result_sha256", models.CharField(max_length=64, editable=False)),
                ("revision_sha256", models.CharField(max_length=64, editable=False)),
                (
                    "qualification_sha256",
                    models.CharField(max_length=64, editable=False),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        to="organizations.organization",
                        on_delete=django.db.models.deletion.PROTECT,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        to=settings.AUTH_USER_MODEL,
                        on_delete=django.db.models.deletion.PROTECT,
                    ),
                ),
                (
                    "snapshot",
                    models.OneToOneField(
                        to="assessments.assessmentsnapshot",
                        on_delete=django.db.models.deletion.PROTECT,
                    ),
                ),
                (
                    "revision",
                    models.OneToOneField(
                        to="jobs.actioncardrevision",
                        on_delete=django.db.models.deletion.PROTECT,
                    ),
                ),
                (
                    "capture_receipt",
                    models.ForeignKey(
                        to="assessments.snapshotcapturereceipt",
                        on_delete=django.db.models.deletion.PROTECT,
                    ),
                ),
            ],
            options={"db_table": "review_capture_proposal_receipts"},
        ),
        migrations.RunSQL(SQL),
    ]
