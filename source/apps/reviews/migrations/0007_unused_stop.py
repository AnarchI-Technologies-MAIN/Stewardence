"""Explicit original owner may terminate only positively unused frozen work."""

from django.db import migrations, models

SQL = r"""
ALTER TABLE public.review_unused_stop_gate OWNER TO agentledger_owner;
REVOKE ALL ON public.review_unused_stop_gate FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE public.review_unused_stop_gate ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.review_unused_stop_gate FORCE ROW LEVEL SECURITY;
CREATE POLICY review_unused_stop_operator ON public.review_unused_stop_gate TO agentledger_owner USING(true) WITH CHECK(true);
INSERT INTO public.review_unused_stop_gate(id,enabled) VALUES(1,false);

CREATE FUNCTION app_private.require_unused_stop_owner(org uuid,actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM public.review_unused_stop_gate WHERE id=1 AND enabled)
  OR NOT EXISTS(SELECT 1 FROM public.organizations_organizationmember
   WHERE organization_id=org AND user_id=actor AND role='owner') THEN
  RAISE EXCEPTION 'Unused review stop owner authority unavailable'; END IF;
END;$fn$;
ALTER FUNCTION app_private.require_unused_stop_owner(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.require_unused_stop_owner(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.require_unused_review_work_absence(pid uuid,sid uuid,org uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF EXISTS(SELECT 1 FROM public.review_artifact_requests WHERE pack_id=pid OR (organization_id=org AND report_id IN (SELECT id FROM public.reports WHERE assessment_snapshot_id=sid)))
  OR EXISTS(SELECT 1 FROM public.review_pack_completions c JOIN public.review_artifact_requests q ON q.id=c.request_id WHERE q.pack_id=pid)
  OR EXISTS(SELECT 1 FROM public.reports WHERE assessment_snapshot_id=sid)
  OR EXISTS(SELECT 1 FROM public.report_artifacts WHERE assessment_snapshot_id=sid)
  OR EXISTS(SELECT 1 FROM public.background_jobs j JOIN public.reports r ON j.payload->>'report_id'=r.id::text WHERE r.assessment_snapshot_id=sid) THEN
  RAISE EXCEPTION 'Unused stop cannot release admitted or ambiguous report work'; END IF;
END;$fn$;
ALTER FUNCTION app_private.require_unused_review_work_absence(uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.require_unused_review_work_absence(uuid,uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;

CREATE FUNCTION app_private.stop_unused_review_pack(pid uuid,org uuid,actor uuid,reason text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE p public.review_pack_identities%ROWTYPE; c public.review_cycles%ROWTYPE;
 r public.review_capacity_reservations%ROWTYPE; e public.review_cycle_events%ROWTYPE;
 re public.review_reservation_events%ROWTYPE; receipt jsonb; release jsonb; target uuid; issued timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR pid IS NULL OR org IS NULL OR actor IS NULL
  OR org IS DISTINCT FROM app_private.current_organization_id() OR actor IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Unused review stop context invalid'; END IF;
 IF reason IS NULL OR reason NOT IN ('context_too_large','owner_stopped') THEN RAISE EXCEPTION 'Unused review stop reason invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('review:'||org::text||':capacity',0));
 PERFORM 1 FROM public.review_unused_stop_gate WHERE id=1 FOR SHARE;
 PERFORM app_private.require_unused_stop_owner(org,actor);
 SELECT * INTO p FROM public.review_pack_identities WHERE id=pid AND organization_id=org;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=org FOR UPDATE;
 IF p.id IS NULL OR c.id IS NULL OR p.created_by_id IS DISTINCT FROM actor OR c.created_by_id IS DISTINCT FROM actor
  OR p.manifest->>'schema' IS DISTINCT FROM 'stewardence.review_pack.v4' THEN RAISE EXCEPTION 'Unused review stop original pack owner required'; END IF;
 PERFORM 1 FROM public.accounts_user WHERE id=actor FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organization WHERE id=org FOR KEY SHARE;
 -- Report admission takes a conflicting snapshot key-share lock and checks
 -- terminal history after its wait. This closes the absence-read phantom.
 PERFORM 1 FROM public.assessment_snapshots WHERE id=c.input_snapshot_id AND organization_id=org FOR UPDATE;
 PERFORM 1 FROM public.review_pack_identities WHERE id=p.id FOR KEY SHARE;
 SELECT * INTO r FROM public.review_capacity_reservations WHERE cycle_id=c.id AND organization_id=org FOR KEY SHARE;
 PERFORM 1 FROM public.organizations_organizationmember WHERE organization_id=org AND user_id=actor FOR SHARE;
 SELECT * INTO e FROM public.review_cycle_events WHERE cycle_id=c.id ORDER BY revision DESC LIMIT 1 FOR KEY SHARE;
 SELECT * INTO re FROM public.review_reservation_events WHERE reservation_id=r.id ORDER BY revision DESC LIMIT 1 FOR KEY SHARE;
 PERFORM app_private.validate_capture_proposal_pack(p.id,org);
 PERFORM app_private.require_capture_pack_creator(c.input_snapshot_id,org,actor);
 PERFORM app_private.require_unused_review_work_absence(p.id,c.input_snapshot_id,org);
 PERFORM app_private.require_unused_stop_owner(org,actor);
 IF r.id IS NULL OR r.created_by_id IS DISTINCT FROM actor OR e.id IS NULL OR re.id IS NULL
  OR e.created_by_id IS DISTINCT FROM actor OR e.organization_id IS DISTINCT FROM org
  OR re.created_by_id IS DISTINCT FROM actor OR re.organization_id IS DISTINCT FROM org
  OR e.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(e.payload),'UTF8')),'hex')
  OR re.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(re.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Unused review stop event integrity invalid'; END IF;
 receipt:=jsonb_build_object('schema','stewardence.review_unused_stop.v1','cycle_id',c.id::text,'pack_id',p.id::text,
  'manifest_sha256',p.sha256,'reservation_id',r.id::text,'actor_id',actor::text,'reason',reason,
  'state','TERMINATED_UNUSED','reservation_state','proven_unused','monthly_allowance_refunded',false,
  'proof_scope','no_admitted_report_work');
 IF e.state='TERMINATED_UNUSED' THEN
  IF e.revision<>4 OR e.created_by_id IS DISTINCT FROM actor OR e.payload IS DISTINCT FROM receipt
   OR re.revision<>2 OR re.state IS DISTINCT FROM 'proven_unused'
   OR re.payload IS DISTINCT FROM jsonb_build_object('schema','stewardence.review_unused_release.v1',
    'reservation_id',r.id::text,'revision',2,'state','proven_unused','stop_event_id',e.id::text,
    'pack_id',p.id::text,'manifest_sha256',p.sha256,'monthly_allowance_refunded',false,
    'proof_scope','no_admitted_report_work') THEN RAISE EXCEPTION 'Unused review stop replay changed'; END IF;
  RETURN e.id;
 END IF;
 IF e.state IS DISTINCT FROM 'FROZEN' OR e.revision<>3 OR re.state IS DISTINCT FROM 'reserved' OR re.revision<>1
  OR r.state IS DISTINCT FROM 'reserved'
  OR e.payload IS DISTINCT FROM jsonb_build_object('schema','stewardence.review_cycle_event.v2',
   'cycle_id',c.id::text,'revision',3,'state','FROZEN','pack_id',p.id::text,'manifest_sha256',p.sha256)
  OR re.payload IS DISTINCT FROM jsonb_build_object('schema','stewardence.review_reservation_event.v2',
   'reservation_id',r.id::text,'cycle_id',c.id::text,'revision',1,'state','reserved',
   'paid_coverage_id',r.paid_coverage_id::text,'reserved_bytes',r.reserved_bytes) THEN
  RAISE EXCEPTION 'Unused review stop requires unused frozen reservation'; END IF;
 issued:=clock_timestamp();
 IF issued<p.created_at OR issued<e.created_at OR issued<re.created_at THEN RAISE EXCEPTION 'Unused review stop clock discontinuity'; END IF;
 -- No further row/FK waits precede effects: all identity targets are locked.
 PERFORM app_private.require_unused_stop_owner(org,actor);
 PERFORM app_private.require_unused_review_work_absence(p.id,c.input_snapshot_id,org);
 target:=gen_random_uuid();
 INSERT INTO public.review_cycle_events(id,organization_id,created_by_id,created_at,cycle_id,revision,state,payload,sha256)
 VALUES(target,org,actor,issued,c.id,4,'TERMINATED_UNUSED',receipt,
  encode(sha256(convert_to(app_private.queue_canonical(receipt),'UTF8')),'hex'));
 release:=jsonb_build_object('schema','stewardence.review_unused_release.v1','reservation_id',r.id::text,
  'revision',2,'state','proven_unused','stop_event_id',target::text,'pack_id',p.id::text,
  'manifest_sha256',p.sha256,'monthly_allowance_refunded',false,'proof_scope','no_admitted_report_work');
 INSERT INTO public.review_reservation_events(id,organization_id,created_by_id,created_at,reservation_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),org,actor,issued,r.id,2,'proven_unused',release,
  encode(sha256(convert_to(app_private.queue_canonical(release),'UTF8')),'hex'));
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.stop_unused_review_pack(uuid,uuid,uuid,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.stop_unused_review_pack(uuid,uuid,uuid,text) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.stop_unused_review_pack(uuid,uuid,uuid,text) TO agentledger_app;

CREATE FUNCTION app_private.fence_unused_capture_report() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE schema jsonb;
BEGIN
 IF session_user IN ('agentledger_app','agentledger_worker')
  AND NEW.organization_id IS DISTINCT FROM app_private.current_organization_id() THEN
  RAISE EXCEPTION 'Report tenant context unavailable' USING ERRCODE='42501'; END IF;
 SELECT input_payload->'snapshot_schema_version' INTO schema FROM public.assessment_snapshots
  WHERE id=NEW.assessment_snapshot_id AND organization_id=NEW.organization_id;
 IF schema IS DISTINCT FROM '2'::jsonb THEN RETURN NEW; END IF;
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Capture report admission requires read committed'; END IF;
 PERFORM 1 FROM public.assessment_snapshots WHERE id=NEW.assessment_snapshot_id
  AND organization_id=NEW.organization_id FOR KEY SHARE;
 IF EXISTS(SELECT 1 FROM public.review_cycles c
  JOIN public.review_cycle_events e ON e.cycle_id=c.id
  WHERE c.input_snapshot_id=NEW.assessment_snapshot_id AND c.organization_id=NEW.organization_id
   AND e.state='TERMINATED_UNUSED') THEN
  RAISE EXCEPTION 'Unused terminated capture cannot admit report work'; END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.fence_unused_capture_report() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.fence_unused_capture_report() FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
CREATE TRIGGER capture_unused_report_fence BEFORE INSERT ON public.reports FOR EACH ROW EXECUTE FUNCTION app_private.fence_unused_capture_report();
"""


class Migration(migrations.Migration):
    dependencies = [("reviews", "0006_capture_proposal_packs")]
    operations = [
        migrations.CreateModel(
            name="UnusedStopGate",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, primary_key=True, editable=False, serialize=False
                    ),
                ),
                ("enabled", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "review_unused_stop_gate",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1),
                        name="review_unused_stop_gate_singleton",
                    )
                ],
            },
        ),
        migrations.RunSQL(SQL),
    ]
