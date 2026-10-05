"""Default-closed schema-2 capture admission; Python computation is trusted."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = r"""
ALTER TABLE assessment_capture_gate OWNER TO agentledger_owner;
REVOKE ALL ON assessment_capture_gate FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE assessment_capture_gate ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_capture_gate FORCE ROW LEVEL SECURITY;
CREATE POLICY capture_gate_owner ON assessment_capture_gate TO agentledger_owner USING(true) WITH CHECK(true);
INSERT INTO assessment_capture_gate VALUES(1,false);
ALTER TABLE assessment_capture_receipts OWNER TO agentledger_owner;
REVOKE ALL ON assessment_capture_receipts FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
GRANT SELECT ON assessment_capture_receipts TO agentledger_app;
ALTER TABLE assessment_capture_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_capture_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY capture_receipt_owner ON assessment_capture_receipts TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY capture_receipt_app ON assessment_capture_receipts FOR SELECT TO agentledger_app
 USING(organization_id=app_private.current_organization_id() AND EXISTS(SELECT 1 FROM organizations_organizationmember m
 WHERE m.organization_id=assessment_capture_receipts.organization_id AND m.user_id=app_private.current_user_id() AND m.role='owner'));
CREATE FUNCTION app_private.capture_receipt_immutable() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN RAISE EXCEPTION 'Capture receipts are immutable'; END;$fn$;
ALTER FUNCTION app_private.capture_receipt_immutable() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_receipt_immutable() FROM PUBLIC;
CREATE TRIGGER capture_receipt_immutable BEFORE UPDATE OR DELETE ON assessment_capture_receipts FOR EACH ROW EXECUTE FUNCTION app_private.capture_receipt_immutable();
CREATE FUNCTION app_private.capture_snapshot_issuance() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN
 IF NEW.input_payload->'snapshot_schema_version'='1'::jsonb AND NEW.result_payload->'snapshot_schema_version'='1'::jsonb THEN RETURN NEW; END IF;
 IF current_user<>'agentledger_owner' OR NEW.input_payload->'snapshot_schema_version' IS DISTINCT FROM '2'::jsonb
  OR NEW.result_payload->'snapshot_schema_version' IS DISTINCT FROM '2'::jsonb THEN RAISE EXCEPTION 'Schema-2 capture requires narrow issuance'; END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.capture_snapshot_issuance() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_snapshot_issuance() FROM PUBLIC;
CREATE TRIGGER capture_snapshot_issuance BEFORE INSERT ON assessment_snapshots FOR EACH ROW EXECUTE FUNCTION app_private.capture_snapshot_issuance();

CREATE FUNCTION app_private.capture_live_records(org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE result jsonb; fields text[]:=ARRAY['display_name','vendor_name','business_owner','department','user_count','business_purpose','monthly_cost_cents','seat_count','connected_systems','data_categories','permissions','capabilities','autonomy_level','human_approval','status'];
 item public.inventory_items%ROWTYPE; values jsonb; provenance jsonb; field text;
BEGIN
 result:='[]'::jsonb;
 FOR item IN SELECT * FROM public.inventory_items WHERE organization_id=org AND archived_at IS NULL
  AND declaration_contract='core.inventory.declarations.v1' ORDER BY id LOOP
  values:='{}'::jsonb; provenance:='{"product_id":"Unknown","source_type":"Declared"}'::jsonb;
  FOREACH field IN ARRAY fields LOOP
   values:=values||jsonb_build_object(field,CASE WHEN item.declared_fields ? field THEN to_jsonb(item)->field ELSE 'null'::jsonb END);
   provenance:=provenance||jsonb_build_object(field,CASE WHEN item.declared_fields ? field THEN 'Declared' ELSE 'Unknown' END);
  END LOOP;
  result:=result||jsonb_build_array(values||jsonb_build_object('id',item.id::text,'product_id',NULL,'source_type',item.source_type,
   'declaration_contract',item.declaration_contract,'declaration_as_of',item.declaration_as_of::text,'provenance',provenance,'archived_at',NULL));
 END LOOP;
 RETURN result;
END;$fn$;
ALTER FUNCTION app_private.capture_live_records(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.capture_live_records(uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.prepare_capture_preview(org uuid,actor uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE organization public.organizations_organization%ROWTYPE; profile public.organization_workflow_profiles%ROWTYPE;
 records jsonb; legacy_count integer; excluded_count integer; reviewed timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR org IS NULL OR actor IS NULL
  OR org IS DISTINCT FROM app_private.current_organization_id() OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Capture preview context invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':inventory',0));
 PERFORM 1 FROM public.assessment_capture_gate WHERE id=1 FOR SHARE;
 -- Prelock actor FK so no authority decision precedes an implicit FK wait.
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 SELECT * INTO organization FROM public.organizations_organization WHERE id=org FOR SHARE;
 SELECT * INTO profile FROM public.organization_workflow_profiles WHERE organization_id=org FOR SHARE;
 PERFORM 1 FROM public.inventory_items WHERE organization_id=org AND archived_at IS NULL AND declaration_contract='core.inventory.declarations.v1' ORDER BY id FOR SHARE;
 IF NOT COALESCE((SELECT enabled FROM public.assessment_capture_gate WHERE id=1),false)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) OR organization.id IS NULL OR profile.id IS NULL THEN RAISE EXCEPTION 'Capture preview unavailable'; END IF;
 records:=app_private.capture_live_records(org);
 IF jsonb_array_length(records) NOT BETWEEN 1 AND 100 THEN RAISE EXCEPTION 'Capture requires one to one hundred explicit records'; END IF;
 SELECT count(*) FILTER(WHERE declaration_contract=''),count(*) FILTER(WHERE declaration_contract<>'core.inventory.declarations.v1') INTO legacy_count,excluded_count FROM public.inventory_items WHERE organization_id=org AND archived_at IS NULL;
 reviewed:=clock_timestamp();
 RETURN jsonb_build_object('schema','core.capture.preview.v1','capture_id',gen_random_uuid()::text,'reviewed_at',to_char(reviewed AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'organization_id',org::text,'actor_id',actor::text,'industry',organization.industry,'workflow_profile',jsonb_build_object('id',profile.id::text,'profile',profile.profile,'settings',profile.settings),
  'inventory_records',records,'excluded_active_count',excluded_count,'legacy_active_count',legacy_count);
END;$fn$;
ALTER FUNCTION app_private.prepare_capture_preview(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.prepare_capture_preview(uuid,uuid) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.prepare_capture_preview(uuid,uuid) TO agentledger_app;

CREATE FUNCTION app_private.issue_deliberate_capture(org uuid,actor uuid,frame jsonb,envelope jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE cid uuid; reviewed timestamptz; admitted timestamptz; request_sha text; previous public.assessment_capture_receipts%ROWTYPE;
 organization public.organizations_organization%ROWTYPE; profile public.organization_workflow_profiles%ROWTYPE;
 records jsonb; legacy_count integer; excluded_count integer; inputs jsonb; results jsonb; row jsonb; expected_applicability jsonb; engines jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR org IS NULL OR actor IS NULL
  OR org IS DISTINCT FROM app_private.current_organization_id() OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Capture admission context invalid'; END IF;
 IF jsonb_typeof(frame) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(frame))<>10
  OR NOT frame ?& ARRAY['schema','capture_id','reviewed_at','organization_id','actor_id','industry','workflow_profile','inventory_records','excluded_active_count','legacy_active_count']
  OR frame->>'schema' IS DISTINCT FROM 'core.capture.preview.v1' OR frame->>'organization_id' IS DISTINCT FROM org::text OR frame->>'actor_id' IS DISTINCT FROM actor::text
  OR jsonb_typeof(frame->'capture_id') IS DISTINCT FROM 'string' OR jsonb_typeof(frame->'reviewed_at') IS DISTINCT FROM 'string'
  OR octet_length(frame::text)>2097152 OR octet_length(envelope::text)>2097152 THEN RAISE EXCEPTION 'Reviewed capture frame invalid'; END IF;
 cid:=(frame->>'capture_id')::uuid; reviewed:=(frame->>'reviewed_at')::timestamptz;
 IF cid IS NULL OR cid::text IS DISTINCT FROM frame->>'capture_id' THEN RAISE EXCEPTION 'Capture identity invalid'; END IF;
 request_sha:=encode(sha256(convert_to(app_private.queue_canonical(frame),'UTF8')),'hex');
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':inventory',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('capture:'||cid::text,0));
 PERFORM 1 FROM public.assessment_capture_gate WHERE id=1 FOR SHARE;
 -- Prelock actor FK so no authority decision precedes an implicit FK wait.
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 SELECT * INTO organization FROM public.organizations_organization WHERE id=org FOR SHARE;
 SELECT * INTO profile FROM public.organization_workflow_profiles WHERE organization_id=org FOR SHARE;
 SELECT * INTO previous FROM public.assessment_capture_receipts WHERE id=cid;
 IF previous.id IS NOT NULL THEN
  IF previous.organization_id IS DISTINCT FROM org OR previous.created_by_id IS DISTINCT FROM actor OR previous.reviewed_frame IS DISTINCT FROM frame OR previous.request_sha256 IS DISTINCT FROM request_sha THEN RAISE EXCEPTION 'Capture replay identity changed'; END IF;
  IF NOT COALESCE((SELECT enabled FROM public.assessment_capture_gate WHERE id=1),false) OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN RAISE EXCEPTION 'Capture replay unavailable'; END IF;
  IF NOT EXISTS(SELECT 1 FROM public.assessment_snapshots s WHERE s.id=previous.snapshot_id AND s.organization_id=org
    AND s.input_payload=envelope->'input_payload' AND s.result_payload=envelope->'result_payload'
    AND s.input_sha256=envelope->>'input_sha256' AND s.result_sha256=envelope->>'result_sha256') THEN RAISE EXCEPTION 'Capture replay computation changed'; END IF;
  RETURN previous.snapshot_id;
 END IF;
 PERFORM 1 FROM public.inventory_items WHERE organization_id=org AND archived_at IS NULL AND declaration_contract='core.inventory.declarations.v1' ORDER BY id FOR SHARE;
 records:=app_private.capture_live_records(org);
 SELECT count(*) FILTER(WHERE declaration_contract=''),count(*) FILTER(WHERE declaration_contract<>'core.inventory.declarations.v1') INTO legacy_count,excluded_count FROM public.inventory_items WHERE organization_id=org AND archived_at IS NULL;
 IF organization.id IS NULL OR profile.id IS NULL OR frame->>'industry' IS DISTINCT FROM organization.industry
  OR frame->'workflow_profile' IS DISTINCT FROM jsonb_build_object('id',profile.id::text,'profile',profile.profile,'settings',profile.settings)
  OR frame->'inventory_records' IS DISTINCT FROM records OR jsonb_array_length(records) NOT BETWEEN 1 AND 100
  OR frame->'legacy_active_count' IS DISTINCT FROM to_jsonb(legacy_count) OR frame->'excluded_active_count' IS DISTINCT FROM to_jsonb(excluded_count) THEN RAISE EXCEPTION 'Reviewed capture source changed'; END IF;
 inputs:=envelope->'input_payload'; results:=envelope->'result_payload';
 expected_applicability:=jsonb_build_object('industry',organization.industry,'policy_state',CASE WHEN organization.industry='accounting_bookkeeping' THEN 'applicable' ELSE 'not_assessed' END,
  'reason',CASE WHEN organization.industry='accounting_bookkeeping' THEN 'accounting_pack_selected' ELSE 'no_qualified_industry_pack' END,'generic_exposure','core.exposure.declarations.v1');
 engines:='{"capture":"core.capture.declarations.v1","exposure":"core.exposure.declarations.v1"}'::jsonb;
 IF organization.industry='accounting_bookkeeping' THEN engines:=engines||'{"policy":"AL-POLICY-1","policy_admission":"core.capture.known_policy.v1"}'::jsonb; END IF;
 IF jsonb_typeof(envelope) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(envelope))<>4
  OR NOT envelope ?& ARRAY['input_payload','result_payload','input_sha256','result_sha256'] OR jsonb_typeof(inputs) IS DISTINCT FROM 'object' OR jsonb_typeof(results) IS DISTINCT FROM 'object'
  OR (SELECT count(*) FROM jsonb_object_keys(inputs))<>14 OR (SELECT count(*) FROM jsonb_object_keys(results))<>6
  OR inputs->'snapshot_schema_version' IS DISTINCT FROM '2'::jsonb OR results->'snapshot_schema_version' IS DISTINCT FROM '2'::jsonb
  OR inputs->>'capture_contract' IS DISTINCT FROM 'core.capture.declarations.v1' OR results->>'capture_contract' IS DISTINCT FROM 'core.capture.declarations.v1'
  OR inputs->'assessment' IS DISTINCT FROM jsonb_build_object('id',cid::text,'version',1) OR results->'assessment' IS DISTINCT FROM inputs->'assessment'
  OR inputs->>'organization_id' IS DISTINCT FROM org::text OR inputs->>'created_by_id' IS DISTINCT FROM actor::text
  OR jsonb_typeof(inputs->'captured_at') IS DISTINCT FROM 'string' OR (inputs->>'captured_at')::timestamptz IS DISTINCT FROM reviewed
  OR inputs->'inventory' IS DISTINCT FROM records OR inputs->'evidence_references' IS DISTINCT FROM '[]'::jsonb
  OR inputs->'benefit_model' IS DISTINCT FROM '{"state":"not_supplied"}'::jsonb OR results->'benefit_model' IS DISTINCT FROM inputs->'benefit_model'
  OR inputs->'industry_applicability' IS DISTINCT FROM expected_applicability OR results->'industry_applicability' IS DISTINCT FROM expected_applicability
  OR inputs->'workflow_profile' IS DISTINCT FROM (frame->'workflow_profile')||jsonb_build_object('settings_sha256',encode(sha256(convert_to(app_private.queue_canonical(profile.settings),'UTF8')),'hex'))
  OR inputs->'engine_versions' IS DISTINCT FROM engines OR inputs->'risk_configuration' IS DISTINCT FROM '{"state":"not_assessed"}'::jsonb
  OR inputs->'rulesets'->'organization' IS DISTINCT FROM '[]'::jsonb OR jsonb_typeof(inputs->'rulesets') IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(inputs->'rulesets'))<>2
  OR jsonb_typeof(results->'inventory_results') IS DISTINCT FROM 'array'
  OR envelope->>'input_sha256' IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(inputs),'UTF8')),'hex')
  OR envelope->>'result_sha256' IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(results),'UTF8')),'hex') THEN RAISE EXCEPTION 'Capture computation identity invalid'; END IF;
 IF organization.industry<>'accounting_bookkeeping' AND inputs->'rulesets'->'industry' IS DISTINCT FROM 'null'::jsonb THEN RAISE EXCEPTION 'Accounting applicability invalid'; END IF;
 IF organization.industry='accounting_bookkeeping' AND (inputs->'rulesets'->'industry'->>'name' IS DISTINCT FROM 'accounting_and_bookkeeping'
  OR inputs->'rulesets'->'industry'->>'version' IS DISTINCT FROM '1.1.0' OR jsonb_typeof(inputs->'rulesets'->'industry'->'definitions') IS DISTINCT FROM 'array'
  OR inputs->'rulesets'->'industry'->>'definitions_sha256' IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(inputs->'rulesets'->'industry'->'definitions'),'UTF8')),'hex')) THEN RAISE EXCEPTION 'Accounting rule identity invalid'; END IF;
 IF (SELECT jsonb_agg(value->'inventory_item_id' ORDER BY ord) FROM jsonb_array_elements(results->'inventory_results') WITH ORDINALITY t(value,ord))
  IS DISTINCT FROM (SELECT jsonb_agg(value->'id' ORDER BY ord) FROM jsonb_array_elements(records) WITH ORDINALITY t(value,ord)) THEN RAISE EXCEPTION 'Capture result membership invalid'; END IF;
 FOR row IN SELECT value FROM jsonb_array_elements(results->'inventory_results') LOOP
  IF jsonb_typeof(row) IS DISTINCT FROM 'object' OR (SELECT count(*) FROM jsonb_object_keys(row))<>3 OR NOT row ?& ARRAY['inventory_item_id','policy_results','risk']
   OR row->'risk' IS DISTINCT FROM '{"state":"not_assessed","score":null,"band":null}'::jsonb OR jsonb_typeof(row->'policy_results') IS DISTINCT FROM 'array'
   OR (organization.industry<>'accounting_bookkeeping' AND row->'policy_results'<>'[]'::jsonb) THEN RAISE EXCEPTION 'Capture result semantics invalid'; END IF;
 END LOOP;
 -- No SQL claim of independently recomputed policy: this result is trusted Python.
 admitted:=clock_timestamp();
 IF reviewed>admitted OR reviewed<admitted-interval '15 minutes' OR NOT COALESCE((SELECT enabled FROM public.assessment_capture_gate WHERE id=1),false)
  OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN RAISE EXCEPTION 'Capture admission unavailable after waits'; END IF;
 INSERT INTO public.assessment_snapshots(id,organization_id,assessment_id,version,created_by_id,captured_at,input_payload,result_payload,input_sha256,result_sha256,created_at)
  VALUES(cid,org,cid,1,actor,reviewed,inputs,results,envelope->>'input_sha256',envelope->>'result_sha256',admitted);
 INSERT INTO public.assessment_capture_receipts(id,organization_id,created_by_id,snapshot_id,reviewed_frame,request_sha256,admitted_at)
  VALUES(cid,org,actor,cid,frame,request_sha,admitted);
 RETURN cid;
END;$fn$;
ALTER FUNCTION app_private.issue_deliberate_capture(uuid,uuid,jsonb,jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_deliberate_capture(uuid,uuid,jsonb,jsonb) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.issue_deliberate_capture(uuid,uuid,jsonb,jsonb) TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("assessments", "0002_snapshot_security"),
        ("inventory", "0008_explicit_declarations"),
        ("jobs", "0013_paid_entitlement"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="CaptureAdmissionGate",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, primary_key=True, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "assessment_capture_gate",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1), name="capture_gate_singleton"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SnapshotCaptureReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(primary_key=True, editable=False, serialize=False),
                ),
                ("reviewed_frame", models.JSONField(editable=False)),
                ("request_sha256", models.CharField(max_length=64, editable=False)),
                ("admitted_at", models.DateTimeField(editable=False)),
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
            ],
            options={"db_table": "assessment_capture_receipts"},
        ),
        migrations.RunSQL(SQL),
    ]
