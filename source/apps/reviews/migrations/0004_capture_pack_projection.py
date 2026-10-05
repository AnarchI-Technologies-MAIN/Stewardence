"""Additive issued capture packs; historical function bodies remain unchanged."""

import importlib

from django.db import migrations

lifecycle = importlib.import_module("apps.reviews.migrations.0002_pack_lifecycle")
projection = importlib.import_module(
    "apps.reviews.migrations.0003_worker_pack_projection"
)


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError("Qualified review predecessor SQL shape changed")
    return source.replace(old, new, 1)


capture_freeze = lifecycle.freeze_sql.replace(
    "app_private.freeze_review_cycle", "app_private.freeze_capture_review_cycle"
)
start = capture_freeze.index(" manifest:=jsonb_build_object(")
end = capture_freeze.index(";", start) + 1
capture_freeze = (
    capture_freeze[:start]
    + r"""
 manifest:=jsonb_build_object('schema','stewardence.review_pack.v3','cycle_id',c.id::text,
  'organization_id',org::text,'baseline_pack_id',NULL,'snapshot',snapshot,
  'capture',app_private.review_capture_binding(c.input_snapshot_id,org),
  'selected_decisions','[]'::jsonb,'selection_scope','empty_capture_kernel',
  'artifact_state','not_created','baseline_promotion','blocked');
"""
    + capture_freeze[end:]
)
capture_freeze = replace_once(
    capture_freeze,
    " snapshot:=app_private.review_snapshot_manifest(c.input_snapshot_id,org);",
    " snapshot:=app_private.review_snapshot_manifest_capture(c.input_snapshot_id,org);",
)
capture_freeze = capture_freeze.replace(
    "GRANT EXECUTE ON FUNCTION app_private.freeze_capture_review_cycle(uuid,uuid,uuid,integer) TO agentledger_app;",
    "REVOKE ALL ON FUNCTION app_private.freeze_capture_review_cycle(uuid,uuid,uuid,integer) FROM agentledger_app,agentledger_worker,agentledger_billing_admission;",
)

capture_projection = projection.SQL[
    projection.SQL.index("CREATE FUNCTION app_private.review_pack_projection") :
]
capture_projection = capture_projection.replace(
    "app_private.review_pack_projection", "app_private.capture_pack_projection"
)
capture_projection = capture_projection.replace(
    "stewardence.review_pack.v2", "stewardence.review_pack.v3"
)
capture_projection = capture_projection.replace(
    "stewardence.review_worker_projection.v1", "stewardence.review_worker_projection.v2"
)
capture_projection = capture_projection.replace(
    "IS DISTINCT FROM '1'::jsonb", "IS DISTINCT FROM '2'::jsonb"
)
capture_projection = replace_once(
    capture_projection,
    " FOR selection IN SELECT value",
    r"""
 IF p.manifest->'selected_decisions' IS DISTINCT FROM '[]'::jsonb
  OR p.manifest->>'selection_scope' IS DISTINCT FROM 'empty_capture_kernel'
  OR p.manifest->'baseline_pack_id' IS DISTINCT FROM 'null'::jsonb
  OR p.manifest->>'artifact_state' IS DISTINCT FROM 'not_created'
  OR p.manifest->>'baseline_promotion' IS DISTINCT FROM 'blocked'
  OR q.promote_baseline OR p.manifest->'snapshot' IS DISTINCT FROM app_private.review_snapshot_manifest_capture(s.id,q.organization_id)
  OR p.manifest->'capture' IS DISTINCT FROM app_private.review_capture_binding(s.id,q.organization_id)
  OR (SELECT count(*) FROM jsonb_object_keys(p.manifest))<>10 THEN
  RAISE EXCEPTION 'Capture projection meaning invalid'; END IF;
 FOR selection IN SELECT value""",
)
capture_projection = capture_projection.replace(
    "GRANT EXECUTE ON FUNCTION app_private.capture_pack_projection(uuid,uuid) TO agentledger_worker;",
    "REVOKE ALL ON FUNCTION app_private.capture_pack_projection(uuid,uuid) FROM agentledger_worker;",
)

SQL = "".join(
    (
        r"""
ALTER FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) RENAME TO open_review_cycle_v2;
REVOKE ALL ON FUNCTION app_private.open_review_cycle_v2(uuid,uuid,uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.review_snapshot_manifest(uuid,uuid) RENAME TO review_snapshot_manifest_v1;
REVOKE ALL ON FUNCTION app_private.review_snapshot_manifest_v1(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) RENAME TO freeze_review_cycle_v2;
REVOKE ALL ON FUNCTION app_private.freeze_review_cycle_v2(uuid,uuid,uuid,integer) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) RENAME TO request_review_artifact_v2;
REVOKE ALL ON FUNCTION app_private.request_review_artifact_v2(uuid,uuid,uuid,integer,uuid,uuid,boolean) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.review_pack_projection(uuid,uuid) RENAME TO review_pack_projection_v1;
REVOKE ALL ON FUNCTION app_private.review_pack_projection_v1(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) RENAME TO complete_review_pack_v2;
REVOKE ALL ON FUNCTION app_private.complete_review_pack_v2(uuid,uuid,uuid,text,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.review_capture_binding(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; receipt public.assessment_capture_receipts%ROWTYPE;
 inputs jsonb; results jsonb; frame jsonb; pins jsonb; row jsonb;
BEGIN
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 SELECT * INTO receipt FROM public.assessment_capture_receipts WHERE snapshot_id=sid AND organization_id=org;
 inputs:=s.input_payload; results:=s.result_payload; frame:=receipt.reviewed_frame;
 IF s.id IS NULL OR receipt.id IS NULL OR receipt.id IS DISTINCT FROM s.id OR s.assessment_id IS DISTINCT FROM s.id OR s.version<>1
  OR receipt.created_by_id IS DISTINCT FROM s.created_by_id
  OR receipt.request_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(frame),'UTF8')),'hex')
  OR frame->>'capture_id' IS DISTINCT FROM s.id::text OR frame->>'organization_id' IS DISTINCT FROM org::text
  OR frame->>'actor_id' IS DISTINCT FROM s.created_by_id::text OR frame->>'schema' IS DISTINCT FROM 'core.capture.preview.v1'
  OR (frame->>'reviewed_at')::timestamptz IS DISTINCT FROM s.captured_at
  OR s.captured_at>receipt.admitted_at OR receipt.admitted_at-s.captured_at>interval '15 minutes'
  OR s.created_at IS DISTINCT FROM receipt.admitted_at
  OR inputs->'snapshot_schema_version' IS DISTINCT FROM '2'::jsonb OR results->'snapshot_schema_version' IS DISTINCT FROM '2'::jsonb
  OR inputs->>'capture_contract' IS DISTINCT FROM 'core.capture.declarations.v1' OR results->>'capture_contract' IS DISTINCT FROM 'core.capture.declarations.v1'
  OR inputs->>'organization_id' IS DISTINCT FROM org::text OR inputs->>'created_by_id' IS DISTINCT FROM s.created_by_id::text
  OR inputs->'assessment' IS DISTINCT FROM jsonb_build_object('id',s.id::text,'version',1) OR results->'assessment' IS DISTINCT FROM inputs->'assessment'
  OR inputs->'inventory' IS DISTINCT FROM frame->'inventory_records' OR inputs->'evidence_references' IS DISTINCT FROM '[]'::jsonb
  OR inputs->'workflow_profile' IS DISTINCT FROM (frame->'workflow_profile')||jsonb_build_object('settings_sha256',encode(sha256(convert_to(app_private.queue_canonical(frame->'workflow_profile'->'settings'),'UTF8')),'hex'))
  OR inputs->'industry_applicability'->>'industry' IS DISTINCT FROM frame->>'industry'
  OR inputs->'industry_applicability'->>'generic_exposure' IS DISTINCT FROM 'core.exposure.declarations.v1'
  OR results->'industry_applicability' IS DISTINCT FROM inputs->'industry_applicability'
  OR inputs->'benefit_model' IS DISTINCT FROM '{"state":"not_supplied"}'::jsonb OR results->'benefit_model' IS DISTINCT FROM inputs->'benefit_model'
  OR (inputs->>'captured_at')::timestamptz IS DISTINCT FROM s.captured_at
  OR s.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(inputs),'UTF8')),'hex')
  OR s.result_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(results),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Issued capture receipt or snapshot binding invalid'; END IF;
 IF (SELECT jsonb_agg(value->'inventory_item_id' ORDER BY ord) FROM jsonb_array_elements(results->'inventory_results') WITH ORDINALITY t(value,ord))
  IS DISTINCT FROM (SELECT jsonb_agg(value->'id' ORDER BY ord) FROM jsonb_array_elements(inputs->'inventory') WITH ORDINALITY t(value,ord)) THEN
  RAISE EXCEPTION 'Issued capture membership invalid'; END IF;
 FOR row IN SELECT value FROM jsonb_array_elements(results->'inventory_results') LOOP
  IF row->'risk' IS DISTINCT FROM '{"state":"not_assessed","score":null,"band":null}'::jsonb THEN
   RAISE EXCEPTION 'Issued capture risk meaning invalid'; END IF;
 END LOOP;
 RETURN jsonb_build_object('receipt_id',receipt.id::text,'request_sha256',receipt.request_sha256,
  'contract','core.capture.declarations.v1','exposure_contract','core.exposure.declarations.v1');
END;$fn$;
ALTER FUNCTION app_private.review_capture_binding(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_capture_binding(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.review_snapshot_manifest_capture(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; pins jsonb;
BEGIN
 PERFORM app_private.review_capture_binding(sid,org);
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 pins:=s.input_payload->'workflow_profile';
 RETURN jsonb_build_object('snapshot_id',s.id::text,'assessment_id',s.assessment_id::text,
  'assessment_version',s.version,'input_sha256',s.input_sha256,'result_sha256',s.result_sha256,
  'captured_at',s.input_payload->'captured_at','snapshot_schema',2,
  'workflow_profile_id',pins->'id','workflow_profile',pins->'profile','workflow_settings_sha256',pins->'settings_sha256',
  'rules_sha256',encode(sha256(convert_to(app_private.queue_canonical(s.input_payload->'rulesets'),'UTF8')),'hex'),
  'configuration_sha256',encode(sha256(convert_to(app_private.queue_canonical(s.input_payload->'risk_configuration'),'UTF8')),'hex'),
  'engine_versions',s.input_payload->'engine_versions','capture_contract','core.capture.declarations.v1');
END;$fn$;
ALTER FUNCTION app_private.review_snapshot_manifest_capture(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_snapshot_manifest_capture(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.review_snapshot_manifest(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE schema jsonb;
BEGIN
 SELECT input_payload->'snapshot_schema_version' INTO schema FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 IF schema='1'::jsonb THEN RETURN app_private.review_snapshot_manifest_v1(sid,org); END IF;
 IF schema='2'::jsonb THEN RETURN app_private.review_snapshot_manifest_capture(sid,org); END IF;
 RAISE EXCEPTION 'Unsupported review capture schema';
END;$fn$;
ALTER FUNCTION app_private.review_snapshot_manifest(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_snapshot_manifest(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
""",
        capture_freeze,
        r"""
CREATE FUNCTION app_private.open_review_cycle(cid uuid,org uuid,actor uuid,sid uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE schema jsonb; target uuid;
BEGIN
 SELECT input_payload->'snapshot_schema_version' INTO schema FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 IF schema='1'::jsonb THEN RETURN app_private.open_review_cycle_v2(cid,org,actor,sid); END IF;
 IF schema IS DISTINCT FROM '2'::jsonb THEN RAISE EXCEPTION 'Unsupported review open schema'; END IF;
 PERFORM app_private.require_review_owner(org,actor);
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 PERFORM 1 FROM public.assessment_snapshots WHERE id=sid AND organization_id=org FOR KEY SHARE;
 target:=app_private.open_review_cycle_v2(cid,org,actor,sid);
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Capture open authority unavailable after waits'; END IF;
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) TO agentledger_app;

CREATE FUNCTION app_private.freeze_review_cycle(cid uuid,org uuid,actor uuid,expected integer) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE schema jsonb; target uuid;
BEGIN
 SELECT s.input_payload->'snapshot_schema_version' INTO schema FROM public.review_cycles c JOIN public.assessment_snapshots s ON s.id=c.input_snapshot_id
  WHERE c.id=cid AND c.organization_id=org AND s.organization_id=org;
 IF schema='1'::jsonb THEN RETURN app_private.freeze_review_cycle_v2(cid,org,actor,expected); END IF;
 IF schema='2'::jsonb THEN
  PERFORM app_private.require_review_owner(org,actor);
  PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
  PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
  PERFORM 1 FROM public.assessment_snapshots s JOIN public.review_cycles c ON c.input_snapshot_id=s.id WHERE c.id=cid AND c.organization_id=org FOR KEY SHARE OF s;
  target:=app_private.freeze_capture_review_cycle(cid,org,actor,expected);
  IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
   RAISE EXCEPTION 'Capture freeze authority unavailable after waits'; END IF;
  RETURN target;
 END IF;
 RAISE EXCEPTION 'Unsupported review freeze schema';
END;$fn$;
ALTER FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) TO agentledger_app;

CREATE FUNCTION app_private.validate_capture_pack(pid uuid,org uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE p public.review_pack_identities%ROWTYPE; c public.review_cycles%ROWTYPE;
BEGIN
 SELECT * INTO p FROM public.review_pack_identities WHERE id=pid AND organization_id=org;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=org;
 IF p.id IS NULL OR c.id IS NULL OR p.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(p.manifest),'UTF8')),'hex')
  OR (SELECT count(*) FROM jsonb_object_keys(p.manifest))<>10 OR p.manifest->>'schema' IS DISTINCT FROM 'stewardence.review_pack.v3'
  OR p.manifest->>'cycle_id' IS DISTINCT FROM c.id::text OR p.manifest->>'organization_id' IS DISTINCT FROM org::text
  OR p.manifest->'snapshot' IS DISTINCT FROM app_private.review_snapshot_manifest_capture(c.input_snapshot_id,org)
  OR p.manifest->'capture' IS DISTINCT FROM app_private.review_capture_binding(c.input_snapshot_id,org)
  OR p.manifest->'selected_decisions' IS DISTINCT FROM '[]'::jsonb OR p.manifest->>'selection_scope' IS DISTINCT FROM 'empty_capture_kernel'
  OR p.manifest->'baseline_pack_id' IS DISTINCT FROM 'null'::jsonb OR p.manifest->>'artifact_state' IS DISTINCT FROM 'not_created'
  OR p.manifest->>'baseline_promotion' IS DISTINCT FROM 'blocked' THEN RAISE EXCEPTION 'Capture frozen pack binding invalid'; END IF;
 RETURN true;
END;$fn$;
ALTER FUNCTION app_private.validate_capture_pack(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.validate_capture_pack(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.request_review_artifact(pid uuid,org uuid,actor uuid,expected integer,rid uuid,jid uuid,promote boolean) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE schema text; target uuid; sid uuid;
BEGIN
 SELECT manifest->>'schema' INTO schema FROM public.review_pack_identities WHERE id=pid AND organization_id=org;
 IF schema='stewardence.review_pack.v2' THEN RETURN app_private.request_review_artifact_v2(pid,org,actor,expected,rid,jid,promote); END IF;
 IF schema IS DISTINCT FROM 'stewardence.review_pack.v3' OR promote IS DISTINCT FROM false THEN RAISE EXCEPTION 'Capture request meaning unavailable'; END IF;
 PERFORM app_private.require_review_owner(org,actor);
 PERFORM 1 FROM public.review_lifecycle_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 SELECT c.input_snapshot_id INTO sid FROM public.review_cycles c JOIN public.review_pack_identities p ON p.cycle_id=c.id WHERE p.id=pid AND p.organization_id=org;
 PERFORM 1 FROM public.assessment_snapshots WHERE id=sid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.review_pack_identities WHERE id=pid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.reports WHERE id=rid AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.background_jobs WHERE id=jid AND organization_id=org FOR KEY SHARE;
 PERFORM app_private.validate_capture_pack(pid,org);
 target:=app_private.request_review_artifact_v2(pid,org,actor,expected,rid,jid,false);
 IF NOT EXISTS(SELECT 1 FROM public.review_lifecycle_gate WHERE id=1 AND enabled) OR NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Capture request authority unavailable after waits'; END IF;
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) TO agentledger_app;
""",
        capture_projection,
        r"""
CREATE FUNCTION app_private.review_pack_projection(jid uuid,token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE target uuid; schema text;
BEGIN
 target:=app_private.review_job_target(jid,token);
 IF target IS NULL THEN RETURN app_private.review_pack_projection_v1(jid,token); END IF;
 SELECT p.manifest->>'schema' INTO schema FROM public.review_pack_identities p JOIN public.review_artifact_requests q ON q.pack_id=p.id WHERE q.id=target;
 IF schema='stewardence.review_pack.v2' THEN RETURN app_private.review_pack_projection_v1(jid,token); END IF;
 IF schema='stewardence.review_pack.v3' THEN RETURN app_private.capture_pack_projection(jid,token); END IF;
 RAISE EXCEPTION 'Unsupported review projection schema';
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
 IF schema='stewardence.review_pack.v2' THEN RETURN app_private.complete_review_pack_v2(request_id,artifact_id,jid,worker_id,token); END IF;
 IF schema IS DISTINCT FROM 'stewardence.review_pack.v3' OR q.promote_baseline IS DISTINCT FROM false THEN RAISE EXCEPTION 'Capture completion meaning unavailable'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||q.organization_id::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('review:'||q.organization_id::text||':capacity',0));
 PERFORM 1 FROM public.review_lifecycle_gate WHERE id=1 FOR SHARE;
 PERFORM 1 FROM public.accounts_user WHERE id=q.created_by_id FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=q.organization_id FOR KEY SHARE;
 PERFORM 1 FROM public.review_artifact_requests WHERE id=q.id FOR KEY SHARE;
 PERFORM 1 FROM public.review_pack_identities WHERE id=q.pack_id FOR KEY SHARE;
 PERFORM 1 FROM public.reports WHERE id=q.report_id AND organization_id=q.organization_id FOR KEY SHARE;
 PERFORM 1 FROM public.report_artifacts WHERE id=artifact_id AND report_id=q.report_id AND organization_id=q.organization_id FOR KEY SHARE;
 PERFORM 1 FROM public.review_capacity_reservations r JOIN public.review_pack_identities p ON p.cycle_id=r.cycle_id WHERE p.id=q.pack_id FOR KEY SHARE OF r;
 PERFORM app_private.validate_capture_pack(q.pack_id,q.organization_id);
 target:=app_private.complete_review_pack_v2(request_id,artifact_id,jid,worker_id,token);
 IF app_private.review_job_target(jid,token) IS DISTINCT FROM q.id THEN RAISE EXCEPTION 'Capture completion authority unavailable after waits'; END IF;
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) FROM PUBLIC,agentledger_app,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) TO agentledger_worker;
""",
    )
)


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0003_worker_pack_projection"),
        ("assessments", "0003_deliberate_capture"),
    ]
    operations = [migrations.RunSQL(SQL)]
