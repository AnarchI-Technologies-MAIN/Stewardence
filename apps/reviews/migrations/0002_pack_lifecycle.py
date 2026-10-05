"""Closed lifecycle candidate. Qualified storage handler remains mandatory.

No existing frozen identity changes and no worker table access. The operator
switch alone cannot enable the application API or install a worker handler.
"""

import importlib

import django.db.models.deletion
from django.db import migrations, models

initial = importlib.import_module("apps.reviews.migrations.0001_initial")

# Copy the qualified predecessor function unchanged except the two explicit
# state projections. Never alter the historical migration or frozen payload.
freeze_sql = initial.SQL[
    initial.SQL.index("CREATE FUNCTION app_private.freeze_review_cycle") :
]
freeze_sql = freeze_sql.replace(
    "CREATE FUNCTION app_private.freeze_review_cycle",
    "CREATE OR REPLACE FUNCTION app_private.freeze_review_cycle",
    1,
)
if not (freeze_sql.count("IN ('FINALIZATION_REQUESTED','FROZEN')") == 1):
    raise RuntimeError("Qualified predecessor SQL shape changed")
freeze_sql = freeze_sql.replace(
    "IN ('FINALIZATION_REQUESTED','FROZEN')",
    "IN ('FINALIZATION_REQUESTED','FROZEN','ARTIFACT_PENDING')",
)
old_reserved = "WHERE organization_id=org AND state IN ('reserved','reconciliation');"
if not (freeze_sql.count(old_reserved) == 1):
    raise RuntimeError("Qualified predecessor SQL shape changed")
freeze_sql = freeze_sql.replace(
    old_reserved,
    "WHERE organization_id=org AND coalesce((SELECT e.state FROM public.review_reservation_events e "
    "WHERE e.reservation_id=review_capacity_reservations.id ORDER BY revision DESC LIMIT 1),state) "
    "IN ('reserved','reconciliation');",
)

# Existing frozen packs replay their recorded selection, never current events.
replay_start = freeze_sql.index(
    " SELECT * INTO pack FROM public.review_pack_identities WHERE cycle_id=cid;"
)
replay_end = freeze_sql.index(
    " SELECT * INTO event FROM public.review_cycle_events", replay_start
)
freeze_sql = freeze_sql[:replay_start] + freeze_sql[replay_end:]
anchor = " snapshot:=app_private.review_snapshot_manifest(c.input_snapshot_id,org);"
if not (freeze_sql.count(anchor) == 1):
    raise RuntimeError("Qualified predecessor SQL shape changed")
stored_replay = r"""
 SELECT * INTO pack FROM public.review_pack_identities WHERE cycle_id=cid;
 IF FOUND THEN
  IF pack.admitted_revision IS DISTINCT FROM expected
   OR pack.organization_id IS DISTINCT FROM org OR pack.created_by_id IS DISTINCT FROM actor
   OR pack.manifest->>'cycle_id' IS DISTINCT FROM cid::text
   OR pack.manifest->>'organization_id' IS DISTINCT FROM org::text
   OR pack.manifest->'snapshot'->>'snapshot_id' IS DISTINCT FROM c.input_snapshot_id::text
   OR pack.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(pack.manifest),'UTF8')),'hex') THEN
   RAISE EXCEPTION 'Frozen review identity replay changed'; END IF;
  RETURN pack.id;
 END IF;
"""
freeze_sql = freeze_sql.replace(anchor, stored_replay + anchor)
if not (
    freeze_sql.count(
        "'selected_decisions','[]'::jsonb,'selection_scope','empty_initial_kernel'"
    )
    == 1
):
    raise RuntimeError("Qualified predecessor SQL shape changed")
freeze_sql = freeze_sql.replace(
    "'selected_decisions','[]'::jsonb,'selection_scope','empty_initial_kernel'",
    "'selected_decisions',app_private.selected_core_decisions(c.input_snapshot_id,org),"
    "'selection_scope',CASE WHEN EXISTS(SELECT 1 FROM public.core_decision_desk_gate WHERE id=1 AND enabled) "
    "THEN 'owner_statement_events' ELSE 'empty_initial_kernel' END",
)

SQL = r"""
ALTER TABLE public.review_lifecycle_gate OWNER TO agentledger_owner;
REVOKE ALL ON public.review_lifecycle_gate FROM PUBLIC,agentledger_app,agentledger_worker;
INSERT INTO public.review_lifecycle_gate(id,enabled) VALUES(1,false);
DO $fn$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['review_artifact_requests','review_pack_completions','review_baseline_heads'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO agentledger_owner',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,agentledger_app,agentledger_worker',t);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY review_owner ON public.%I TO agentledger_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('CREATE POLICY review_app_read ON public.%I FOR SELECT TO agentledger_app USING(organization_id=app_private.current_organization_id() AND EXISTS(SELECT 1 FROM public.organizations_organizationmember m WHERE m.organization_id=%I.organization_id AND m.user_id=app_private.current_user_id() AND m.role=''owner''))',t,t);
  EXECUTE format('GRANT SELECT ON public.%I TO agentledger_app',t);
 END LOOP;
 FOREACH t IN ARRAY ARRAY['review_artifact_requests','review_pack_completions'] LOOP
  EXECUTE format('CREATE TRIGGER review_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION app_private.reject_review_mutation()',t);
 END LOOP;
END;$fn$;
"""

LIFECYCLE_SQL = r"""
CREATE FUNCTION app_private.request_review_artifact(pid uuid,org uuid,actor uuid,expected integer,rid uuid,jid uuid,promote boolean) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE p public.review_pack_identities%ROWTYPE; c public.review_cycles%ROWTYPE;
 r public.reports%ROWTYPE; j public.background_jobs%ROWTYPE; previous public.review_artifact_requests%ROWTYPE;
 h public.review_baseline_heads%ROWTYPE; e public.review_cycle_events%ROWTYPE; target uuid; payload jsonb;
BEGIN
 PERFORM app_private.require_review_owner(org,actor);
 IF NOT EXISTS(SELECT 1 FROM public.review_lifecycle_gate WHERE id=1 AND enabled)
  THEN RAISE EXCEPTION 'Review lifecycle deployment gate closed'; END IF;
 IF expected IS DISTINCT FROM 3 OR promote IS NULL THEN RAISE EXCEPTION 'Review request revision or choice invalid'; END IF;
 SELECT * INTO p FROM public.review_pack_identities WHERE id=pid AND organization_id=org;
 IF NOT FOUND OR p.created_by_id IS DISTINCT FROM actor OR p.sha256 IS DISTINCT FROM
  encode(sha256(convert_to(app_private.queue_canonical(p.manifest),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Frozen review request identity invalid'; END IF;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=org FOR UPDATE;
 SELECT * INTO previous FROM public.review_artifact_requests WHERE pack_id=pid;
 IF FOUND THEN
  IF previous.report_id IS DISTINCT FROM rid OR previous.job_id IS DISTINCT FROM jid
   OR previous.promote_baseline IS DISTINCT FROM promote OR previous.manifest_sha256 IS DISTINCT FROM p.sha256 THEN
   RAISE EXCEPTION 'Review artifact request replay changed'; END IF;
  RETURN previous.id;
 END IF;
 SELECT * INTO e FROM public.review_cycle_events WHERE cycle_id=c.id ORDER BY revision DESC LIMIT 1;
 IF e.revision IS DISTINCT FROM expected OR e.state IS DISTINCT FROM 'FROZEN' THEN
  RAISE EXCEPTION 'Review request compare and swap failed'; END IF;
 SELECT * INTO r FROM public.reports WHERE id=rid AND organization_id=org;
 IF NOT FOUND OR r.assessment_snapshot_id IS DISTINCT FROM c.input_snapshot_id
  OR r.created_by_id IS DISTINCT FROM actor OR EXISTS(SELECT 1 FROM public.report_artifacts WHERE report_id=rid) THEN
  RAISE EXCEPTION 'Review report identity unavailable'; END IF;
 SELECT * INTO j FROM public.background_jobs WHERE id=jid AND organization_id=org FOR UPDATE;
 IF NOT FOUND OR j.job_type IS DISTINCT FROM 'report_generation' OR j.status IS DISTINCT FROM 'queued'
  OR j.payload IS DISTINCT FROM jsonb_build_object('report_id',rid::text)
  OR j.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(j.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Review job identity unavailable'; END IF;
 SELECT * INTO h FROM public.review_baseline_heads WHERE organization_id=org;
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Review paid owner admission unavailable'; END IF;
 target:=gen_random_uuid();
 INSERT INTO public.review_artifact_requests(id,organization_id,created_by_id,created_at,pack_id,report_id,job_id,manifest_sha256,promote_baseline,observed_head_revision,observed_head_pack_id)
 VALUES(target,org,actor,clock_timestamp(),pid,rid,jid,p.sha256,promote,coalesce(h.revision,0),h.pack_id);
 payload:=jsonb_build_object('schema','stewardence.review_cycle_event.v2','cycle_id',c.id::text,
  'revision',4,'state','ARTIFACT_PENDING','request_id',target::text,'manifest_sha256',p.sha256);
 INSERT INTO public.review_cycle_events(id,organization_id,created_by_id,created_at,cycle_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),org,actor,clock_timestamp(),c.id,4,'ARTIFACT_PENDING',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) FROM PUBLIC,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.request_review_artifact(uuid,uuid,uuid,integer,uuid,uuid,boolean) TO agentledger_app;

CREATE FUNCTION app_private.review_job_target(jid uuid,token uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE j public.background_jobs%ROWTYPE; r public.review_artifact_requests%ROWTYPE;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Review worker requires read committed'; END IF;
 SELECT * INTO j FROM public.background_jobs WHERE id=jid;
 IF NOT FOUND OR j.organization_id IS DISTINCT FROM app_private.current_organization_id()
  OR j.status IS DISTINCT FROM 'running' OR j.claim_token IS DISTINCT FROM token OR token IS NULL
  OR j.lock_expires_at<=clock_timestamp() THEN RAISE EXCEPTION 'Review lease authority unavailable'; END IF;
 SELECT * INTO r FROM public.review_artifact_requests WHERE job_id=jid AND organization_id=j.organization_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.review_lifecycle_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(j.organization_id,r.created_by_id)
  OR NOT app_private.core_work_allowed(j.organization_id) THEN RAISE EXCEPTION 'Review worker admission unavailable'; END IF;
 RETURN r.id;
END;$fn$;
ALTER FUNCTION app_private.review_job_target(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_job_target(uuid,uuid) FROM PUBLIC,agentledger_app;
GRANT EXECUTE ON FUNCTION app_private.review_job_target(uuid,uuid) TO agentledger_worker;

CREATE FUNCTION app_private.complete_review_pack(request_id uuid,artifact_id uuid,jid uuid,worker_id text,token uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE q public.review_artifact_requests%ROWTYPE; p public.review_pack_identities%ROWTYPE;
 c public.review_cycles%ROWTYPE; a public.report_artifacts%ROWTYPE; r public.reports%ROWTYPE;
 j public.background_jobs%ROWTYPE; reservation public.review_capacity_reservations%ROWTYPE;
 h public.review_baseline_heads%ROWTYPE; previous public.review_pack_completions%ROWTYPE;
 old_cycle public.review_cycles%ROWTYPE; payload jsonb; target uuid; promotion text:='not_requested';
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Review worker requires read committed'; END IF;
 SELECT * INTO q FROM public.review_artifact_requests WHERE id=request_id;
 IF NOT FOUND OR q.organization_id IS DISTINCT FROM app_private.current_organization_id() OR q.job_id IS DISTINCT FROM jid THEN
  RAISE EXCEPTION 'Review completion request identity invalid'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||q.organization_id::text||':control',0));
 PERFORM pg_advisory_xact_lock(hashtextextended('review:'||q.organization_id::text||':capacity',0));
 SELECT * INTO p FROM public.review_pack_identities WHERE id=q.pack_id AND organization_id=q.organization_id;
 SELECT * INTO c FROM public.review_cycles WHERE id=p.cycle_id AND organization_id=q.organization_id FOR UPDATE;
 SELECT * INTO j FROM public.background_jobs WHERE id=jid FOR UPDATE;
 IF NOT FOUND OR j.organization_id IS DISTINCT FROM q.organization_id OR j.status IS DISTINCT FROM 'running'
  OR j.claim_token IS DISTINCT FROM token OR token IS NULL OR j.locked_by IS DISTINCT FROM worker_id
  OR j.lock_expires_at<=clock_timestamp() OR NOT EXISTS(SELECT 1 FROM public.review_lifecycle_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(q.organization_id,q.created_by_id)
  OR NOT app_private.core_work_allowed(q.organization_id) THEN RAISE EXCEPTION 'Review completion authority unavailable'; END IF;
 IF p.sha256 IS DISTINCT FROM q.manifest_sha256 OR p.sha256 IS DISTINCT FROM
  encode(sha256(convert_to(app_private.queue_canonical(p.manifest),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Review completion frozen identity invalid'; END IF;
 SELECT * INTO r FROM public.reports WHERE id=q.report_id AND organization_id=q.organization_id;
 SELECT * INTO a FROM public.report_artifacts WHERE id=artifact_id AND report_id=r.id AND organization_id=q.organization_id;
 SELECT * INTO reservation FROM public.review_capacity_reservations WHERE cycle_id=c.id AND organization_id=q.organization_id;
 IF a.id IS NULL OR r.assessment_snapshot_id IS DISTINCT FROM c.input_snapshot_id
  OR a.assessment_snapshot_id IS DISTINCT FROM c.input_snapshot_id OR a.size_bytes>reservation.reserved_bytes
  OR j.payload IS DISTINCT FROM jsonb_build_object('report_id',r.id::text)
  OR j.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(j.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Review completion artifact binding invalid'; END IF;
 SELECT done.* INTO previous FROM public.review_pack_completions done WHERE done.request_id=q.id;
 IF FOUND THEN
  IF previous.artifact_id IS DISTINCT FROM artifact_id THEN RAISE EXCEPTION 'Review completion replay changed'; END IF;
  RETURN previous.id;
 END IF;
 IF (SELECT state FROM public.review_cycle_events WHERE cycle_id=c.id ORDER BY revision DESC LIMIT 1) IS DISTINCT FROM 'ARTIFACT_PENDING'
  OR (SELECT state FROM public.review_reservation_events WHERE reservation_id=reservation.id ORDER BY revision DESC LIMIT 1) IS DISTINCT FROM 'reserved' THEN
  RAISE EXCEPTION 'Review completion state invalid'; END IF;
 -- The reads above and artifact readback are not renewable authority. Check
 -- live paid/pause/lease authority again immediately before protected effects.
 IF j.lock_expires_at<=clock_timestamp() OR NOT app_private.core_owner_entitled(q.organization_id,q.created_by_id)
  OR NOT app_private.core_work_allowed(q.organization_id) THEN
  RAISE EXCEPTION 'Review completion authority unavailable'; END IF;
 SELECT * INTO h FROM public.review_baseline_heads WHERE organization_id=q.organization_id FOR UPDATE;
 -- Even an operator-held head row can delay this transaction. Database clock
 -- authority must be observed after that last row-lock wait, not before it.
 IF j.lock_expires_at<=clock_timestamp() OR NOT EXISTS(SELECT 1 FROM public.review_lifecycle_gate WHERE id=1 AND enabled)
  OR NOT app_private.core_owner_entitled(q.organization_id,q.created_by_id)
  OR NOT app_private.core_work_allowed(q.organization_id) THEN
  RAISE EXCEPTION 'Review completion authority unavailable'; END IF;
 IF q.promote_baseline THEN
  promotion:='stale_head';
  IF coalesce(h.revision,0)=q.observed_head_revision AND h.pack_id IS NOT DISTINCT FROM q.observed_head_pack_id THEN
   IF h.pack_id IS NOT NULL THEN
    SELECT prior.* INTO old_cycle FROM public.review_cycles prior JOIN public.review_pack_identities old ON old.cycle_id=prior.id WHERE old.id=h.pack_id;
   END IF;
   promotion:='older_snapshot';
   IF h.pack_id IS NULL OR ((c.created_at,c.id)>(old_cycle.created_at,old_cycle.id)
    AND (SELECT captured_at FROM public.assessment_snapshots WHERE id=c.input_snapshot_id)>=
        (SELECT captured_at FROM public.assessment_snapshots WHERE id=old_cycle.input_snapshot_id)) THEN
    INSERT INTO public.review_baseline_heads(organization_id,pack_id,revision) VALUES(q.organization_id,p.id,coalesce(h.revision,0)+1)
    ON CONFLICT(organization_id) DO UPDATE SET pack_id=EXCLUDED.pack_id,revision=EXCLUDED.revision;
    promotion:='promoted';
   END IF;
  END IF;
 END IF;
 target:=gen_random_uuid();
 payload:=jsonb_build_object('schema','stewardence.review_pack_completion.v2','request_id',q.id::text,'pack_id',p.id::text,
  'manifest_sha256',p.sha256,'artifact_id',a.id::text,'artifact_sha256',a.sha256,'artifact_bytes',a.size_bytes,
  'verification','trusted_handler_storage_readback','baseline_outcome',promotion);
 INSERT INTO public.review_pack_completions(id,organization_id,created_by_id,created_at,request_id,artifact_id,payload,sha256)
 VALUES(target,q.organization_id,q.created_by_id,clock_timestamp(),q.id,a.id,payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 payload:=jsonb_build_object('schema','stewardence.review_cycle_event.v2','cycle_id',c.id::text,'revision',5,
  'state','COMPLETED','completion_id',target::text,'manifest_sha256',p.sha256);
 INSERT INTO public.review_cycle_events(id,organization_id,created_by_id,created_at,cycle_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),q.organization_id,q.created_by_id,clock_timestamp(),c.id,5,'COMPLETED',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 payload:=jsonb_build_object('schema','stewardence.review_reservation_event.v2','reservation_id',reservation.id::text,
  'revision',2,'state','consumed','artifact_id',a.id::text,'actual_bytes',a.size_bytes);
 INSERT INTO public.review_reservation_events(id,organization_id,created_by_id,created_at,reservation_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),q.organization_id,q.created_by_id,clock_timestamp(),reservation.id,2,'consumed',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 RETURN target;
END;$fn$;
ALTER FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) FROM PUBLIC,agentledger_app;
GRANT EXECUTE ON FUNCTION app_private.complete_review_pack(uuid,uuid,uuid,text,uuid) TO agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0001_initial"),
        ("billing", "0007_ingester_effects"),
        ("jobs", "0014_decision_desk"),
    ]
    operations = [
        migrations.CreateModel(
            name="ReviewLifecycleGate",
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
                "db_table": "review_lifecycle_gate",
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(id=1), name="review_lifecycle_gate_singleton"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ArtifactRequest",
            fields=initial.common_fields()
            + [
                (
                    "pack",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="artifact_request",
                        to="reviews.packidentity",
                    ),
                ),
                (
                    "report",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT, to="reports.report"
                    ),
                ),
                (
                    "job",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="jobs.backgroundjob",
                    ),
                ),
                ("manifest_sha256", models.CharField(max_length=64)),
                ("promote_baseline", models.BooleanField(default=False)),
                ("observed_head_revision", models.PositiveIntegerField()),
                ("observed_head_pack_id", models.UUIDField(null=True)),
            ],
            options={"db_table": "review_artifact_requests"},
        ),
        migrations.CreateModel(
            name="PackCompletion",
            fields=initial.common_fields()
            + [
                (
                    "request",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="completion",
                        to="reviews.artifactrequest",
                    ),
                ),
                (
                    "artifact",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="reports.reportartifact",
                    ),
                ),
                ("payload", models.JSONField()),
                ("sha256", models.CharField(max_length=64)),
            ],
            options={"db_table": "review_pack_completions"},
        ),
        migrations.CreateModel(
            name="BaselineHead",
            fields=[
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        serialize=False,
                        to="organizations.organization",
                    ),
                ),
                (
                    "pack",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="reviews.packidentity",
                    ),
                ),
                ("revision", models.PositiveIntegerField()),
            ],
            options={"db_table": "review_baseline_heads"},
        ),
        migrations.RunSQL(SQL + freeze_sql + LIFECYCLE_SQL),
    ]
