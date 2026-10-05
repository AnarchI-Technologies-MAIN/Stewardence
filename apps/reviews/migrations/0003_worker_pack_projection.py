"""Lease-scoped immutable render projection; no additional table grants."""

from django.db import migrations

SQL = r"""
ALTER TABLE public.review_lifecycle_gate ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.review_lifecycle_gate FORCE ROW LEVEL SECURITY;
CREATE POLICY review_lifecycle_gate_owner ON public.review_lifecycle_gate TO agentledger_owner USING(true) WITH CHECK(true);
CREATE FUNCTION app_private.review_pack_projection(jid uuid,token uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE target uuid; q public.review_artifact_requests%ROWTYPE;
 p public.review_pack_identities%ROWTYPE; c public.review_cycles%ROWTYPE;
 s public.assessment_snapshots%ROWTYPE; report public.reports%ROWTYPE;
 j public.background_jobs%ROWTYPE; d public.core_decision_events%ROWTYPE;
 revision public.core_action_card_revisions%ROWTYPE; selection jsonb;
 selected jsonb:='[]'::jsonb; expected_selection jsonb; idx integer;
BEGIN
 target:=app_private.review_job_target(jid,token);
 IF target IS NULL THEN RETURN NULL; END IF;
 SELECT * INTO q FROM public.review_artifact_requests WHERE id=target;
 SELECT * INTO p FROM public.review_pack_identities WHERE id=q.pack_id AND organization_id=q.organization_id;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=q.organization_id;
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=c.input_snapshot_id AND organization_id=q.organization_id;
 SELECT * INTO report FROM public.reports WHERE id=q.report_id AND organization_id=q.organization_id;
 SELECT * INTO j FROM public.background_jobs WHERE id=jid AND organization_id=q.organization_id;
 IF p.id IS NULL OR c.id IS NULL OR s.id IS NULL OR report.id IS NULL OR j.id IS NULL
  OR p.created_by_id IS DISTINCT FROM q.created_by_id OR c.created_by_id IS DISTINCT FROM q.created_by_id
  OR report.created_by_id IS DISTINCT FROM q.created_by_id
  OR report.assessment_snapshot_id IS DISTINCT FROM s.id OR j.job_type IS DISTINCT FROM 'report_generation'
  OR j.payload IS DISTINCT FROM jsonb_build_object('report_id',report.id::text)
  OR j.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(j.payload),'UTF8')),'hex')
  OR p.sha256 IS DISTINCT FROM q.manifest_sha256
  OR p.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(p.manifest),'UTF8')),'hex')
  OR p.manifest->>'schema' IS DISTINCT FROM 'stewardence.review_pack.v2'
  OR p.manifest->>'cycle_id' IS DISTINCT FROM c.id::text
  OR p.manifest->>'organization_id' IS DISTINCT FROM q.organization_id::text
  OR p.manifest->'snapshot'->>'snapshot_id' IS DISTINCT FROM s.id::text
  OR p.manifest->'snapshot'->>'assessment_id' IS DISTINCT FROM s.assessment_id::text
  OR p.manifest->'snapshot'->'assessment_version' IS DISTINCT FROM to_jsonb(s.version)
  OR p.manifest->'snapshot'->>'input_sha256' IS DISTINCT FROM s.input_sha256
  OR p.manifest->'snapshot'->>'result_sha256' IS DISTINCT FROM s.result_sha256
  OR p.manifest->'snapshot'->'captured_at' IS DISTINCT FROM s.input_payload->'captured_at'
  OR jsonb_typeof(p.manifest->'selected_decisions') IS DISTINCT FROM 'array'
  OR s.input_payload->>'organization_id' IS DISTINCT FROM q.organization_id::text
  OR s.input_payload->'assessment' IS DISTINCT FROM jsonb_build_object('id',s.assessment_id::text,'version',s.version)
  OR s.result_payload->'assessment' IS DISTINCT FROM jsonb_build_object('id',s.assessment_id::text,'version',s.version)
  OR s.input_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR s.result_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR (s.input_payload->>'captured_at')::timestamptz IS DISTINCT FROM s.captured_at
  OR s.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(s.input_payload),'UTF8')),'hex')
  OR s.result_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(s.result_payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Review projection immutable binding invalid'; END IF;
 FOR selection IN SELECT value FROM jsonb_array_elements(p.manifest->'selected_decisions') LOOP
  SELECT * INTO d FROM public.core_decision_events WHERE id=(selection->>'event_id')::uuid AND organization_id=q.organization_id;
  SELECT * INTO revision FROM public.core_action_card_revisions WHERE id=d.revision_id AND organization_id=q.organization_id;
  idx:=d.card_index;
  IF d.id IS NULL OR revision.id IS NULL OR jsonb_typeof(revision.cards) IS DISTINCT FROM 'array'
   OR idx<0 OR idx>=jsonb_array_length(revision.cards) OR revision.snapshot_id IS DISTINCT FROM s.id
   OR revision.input_sha256 IS DISTINCT FROM s.result_sha256 OR d.snapshot_id IS DISTINCT FROM s.id
   OR d.snapshot_result_sha256 IS DISTINCT FROM s.result_sha256
   OR revision.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(revision.cards),'UTF8')),'hex')
   OR d.revision_sha256 IS DISTINCT FROM revision.sha256
   OR d.card_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(revision.cards->idx),'UTF8')),'hex')
   OR d.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(d.payload),'UTF8')),'hex')
   OR d.payload->>'id' IS DISTINCT FROM d.id::text
   OR d.payload->>'organization_id' IS DISTINCT FROM q.organization_id::text
   OR d.payload->>'revision_id' IS DISTINCT FROM revision.id::text
   OR d.payload->>'revision_sha256' IS DISTINCT FROM revision.sha256
   OR d.payload->>'snapshot_id' IS DISTINCT FROM s.id::text
   OR d.payload->>'snapshot_result_sha256' IS DISTINCT FROM s.result_sha256
   OR d.payload->'card_index' IS DISTINCT FROM to_jsonb(idx)
   OR d.payload->>'card_sha256' IS DISTINCT FROM d.card_sha256
   OR d.payload->>'event_kind' IS DISTINCT FROM d.event_kind OR d.payload->>'state' IS DISTINCT FROM d.state
   OR d.payload->'owner_statement_only' IS DISTINCT FROM 'true'::jsonb
   OR d.payload->'resolution_verified' IS DISTINCT FROM 'false'::jsonb THEN
   RAISE EXCEPTION 'Review projection decision binding invalid'; END IF;
  expected_selection:=jsonb_build_object('event_id',d.id,'event_sha256',d.sha256,'revision_id',revision.id,
   'revision_sha256',revision.sha256,'card_index',idx,'card_sha256',d.card_sha256,'snapshot_id',s.id,
   'snapshot_result_sha256',s.result_sha256,'event_kind',d.event_kind,'state',d.state,
   'owner_statement_only',true,'resolution_verified',false);
  IF selection IS DISTINCT FROM expected_selection THEN RAISE EXCEPTION 'Review projection frozen selection invalid'; END IF;
  selected:=selected||jsonb_build_array(jsonb_build_object('selection',selection,'payload',d.payload,
   'event_sha256',d.sha256,'proposal',revision.cards->idx));
 END LOOP;
 -- No waiting locks are acquired by this read projection. Current admission
 -- is still checked again after all work; persistence later fences separately.
 PERFORM app_private.review_job_target(jid,token);
 RETURN jsonb_build_object('schema','stewardence.review_worker_projection.v1','request_id',q.id,
  'job_id',j.id,'report_id',report.id,'organization_id',q.organization_id,'pack_id',p.id,
  'manifest',p.manifest,'manifest_sha256',p.sha256,'snapshot_input',s.input_payload,
  'snapshot_result',s.result_payload,'selected_decisions',selected);
END;$fn$;
ALTER FUNCTION app_private.review_pack_projection(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_pack_projection(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.review_pack_projection(uuid,uuid) TO agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies = [("reviews", "0002_pack_lifecycle")]
    operations = [migrations.RunSQL(SQL)]
