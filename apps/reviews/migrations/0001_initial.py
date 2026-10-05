"""Initial immutable review kernel. FROZEN reserves capacity, not completion."""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def common_fields():
    return [
        (
            "id",
            models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        ("created_at", models.DateTimeField(editable=False)),
        (
            "organization",
            models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="organizations.organization",
            ),
        ),
        (
            "created_by",
            models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL
            ),
        ),
    ]


SQL = r"""
CREATE FUNCTION app_private.reject_review_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog AS $fn$
BEGIN RAISE EXCEPTION 'Review identity and events are immutable'; END;$fn$;
ALTER FUNCTION app_private.reject_review_mutation() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.reject_review_mutation() FROM PUBLIC;
DO $fn$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['review_cycles','review_cycle_events','review_pack_identities',
  'review_capacity_reservations','review_reservation_events'] LOOP
  EXECUTE format('ALTER TABLE public.%I OWNER TO agentledger_owner',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,agentledger_app,agentledger_worker',t);
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('CREATE POLICY review_owner ON public.%I TO agentledger_owner USING(true) WITH CHECK(true)',t);
  EXECUTE format('CREATE POLICY review_app_read ON public.%I FOR SELECT TO agentledger_app USING(organization_id=app_private.current_organization_id() AND EXISTS(SELECT 1 FROM public.organizations_organizationmember m WHERE m.organization_id=%I.organization_id AND m.user_id=app_private.current_user_id() AND m.role=''owner''))',t,t);
  EXECUTE format('GRANT SELECT ON public.%I TO agentledger_app',t);
  EXECUTE format('CREATE TRIGGER review_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION app_private.reject_review_mutation()',t);
 END LOOP;
END;$fn$;

CREATE FUNCTION app_private.require_review_owner(org uuid,actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Review admission requires read committed'; END IF;
 IF org IS NULL OR actor IS NULL OR org IS DISTINCT FROM app_private.current_organization_id()
  OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Review actor tenant binding required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||org::text||':control',0));
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Review paid owner admission unavailable'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('review:'||org::text||':capacity',0));
 -- Capacity waits can outlive paid authority. READ COMMITTED rechecks after
 -- the complete ordered lock set; an earlier observation cannot authorize.
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Review paid owner admission unavailable'; END IF;
END;$fn$;
ALTER FUNCTION app_private.require_review_owner(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.require_review_owner(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker;

CREATE FUNCTION app_private.review_snapshot_manifest(sid uuid,org uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.assessment_snapshots%ROWTYPE; profile public.organization_workflow_profiles%ROWTYPE;
BEGIN
 SELECT * INTO s FROM public.assessment_snapshots WHERE id=sid AND organization_id=org;
 IF NOT FOUND OR s.input_payload->>'organization_id' IS DISTINCT FROM org::text
  OR s.input_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR s.result_payload->'snapshot_schema_version' IS DISTINCT FROM '1'::jsonb
  OR s.input_payload->'assessment' IS DISTINCT FROM jsonb_build_object('id',s.assessment_id::text,'version',s.version)
  OR s.result_payload->'assessment' IS DISTINCT FROM jsonb_build_object('id',s.assessment_id::text,'version',s.version)
  OR jsonb_typeof(s.input_payload->'captured_at') IS DISTINCT FROM 'string'
  OR (s.input_payload->>'captured_at')::timestamptz IS DISTINCT FROM s.captured_at
  OR s.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(s.input_payload),'UTF8')),'hex')
  OR s.result_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(s.result_payload),'UTF8')),'hex')
  OR jsonb_typeof(s.input_payload->'rulesets') IS DISTINCT FROM 'object'
  OR jsonb_typeof(s.input_payload->'risk_configuration') IS DISTINCT FROM 'object'
  OR jsonb_typeof(s.input_payload->'engine_versions') IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'Review snapshot binding or integrity invalid'; END IF;
 SELECT * INTO profile FROM public.organization_workflow_profiles WHERE organization_id=org;
 IF NOT FOUND OR profile.profile NOT IN ('business.v1','development.v1') THEN
  RAISE EXCEPTION 'Review workflow meaning is unresolved'; END IF;
 RETURN jsonb_build_object('snapshot_id',s.id::text,'assessment_id',s.assessment_id::text,
  'assessment_version',s.version,'input_sha256',s.input_sha256,'result_sha256',s.result_sha256,
  'captured_at',s.input_payload->'captured_at',
  'snapshot_schema',s.input_payload->'snapshot_schema_version',
  'workflow_profile_id',profile.id::text,'workflow_profile',profile.profile,
  'workflow_settings_sha256',encode(sha256(convert_to(app_private.queue_canonical(profile.settings),'UTF8')),'hex'),
  'rules_sha256',encode(sha256(convert_to(app_private.queue_canonical(s.input_payload->'rulesets'),'UTF8')),'hex'),
  'configuration_sha256',encode(sha256(convert_to(app_private.queue_canonical(s.input_payload->'risk_configuration'),'UTF8')),'hex'),
  'engine_versions',s.input_payload->'engine_versions');
END;$fn$;
ALTER FUNCTION app_private.review_snapshot_manifest(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.review_snapshot_manifest(uuid,uuid) FROM PUBLIC,agentledger_app,agentledger_worker;

CREATE FUNCTION app_private.open_review_cycle(cid uuid,org uuid,actor uuid,sid uuid) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE payload jsonb; existing public.review_cycles%ROWTYPE;
BEGIN
 PERFORM app_private.require_review_owner(org,actor);
 IF cid IS NULL OR sid IS NULL THEN RAISE EXCEPTION 'Review identities required'; END IF;
 PERFORM app_private.review_snapshot_manifest(sid,org);
 SELECT * INTO existing FROM public.review_cycles WHERE id=cid;
 IF FOUND THEN
  IF existing.organization_id IS DISTINCT FROM org OR existing.created_by_id IS DISTINCT FROM actor
   OR existing.input_snapshot_id IS DISTINCT FROM sid THEN RAISE EXCEPTION 'Review identity replay changed'; END IF;
  RETURN cid;
 END IF;
 IF EXISTS(SELECT 1 FROM public.review_cycles c WHERE c.organization_id=org
   AND (SELECT state FROM public.review_cycle_events e WHERE e.cycle_id=c.id ORDER BY revision DESC LIMIT 1)='OPEN') THEN
  RAISE EXCEPTION 'Review active or open capacity exhausted'; END IF;
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Review paid owner admission unavailable'; END IF;
 INSERT INTO public.review_cycles(id,organization_id,created_by_id,created_at,input_snapshot_id,baseline_pack_id)
 VALUES(cid,org,actor,clock_timestamp(),sid,NULL);
 payload:=jsonb_build_object('schema','stewardence.review_cycle_event.v2','cycle_id',cid::text,
  'revision',1,'state','OPEN','input_snapshot_id',sid::text,'baseline_pack_id',NULL);
 INSERT INTO public.review_cycle_events(id,organization_id,created_by_id,created_at,cycle_id,revision,state,payload,sha256)
 VALUES(gen_random_uuid(),org,actor,clock_timestamp(),cid,1,'OPEN',payload,
  encode(sha256(convert_to(app_private.queue_canonical(payload),'UTF8')),'hex'));
 RETURN cid;
END;$fn$;
ALTER FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) FROM PUBLIC,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.open_review_cycle(uuid,uuid,uuid,uuid) TO agentledger_app;

CREATE FUNCTION app_private.freeze_review_cycle(cid uuid,org uuid,actor uuid,expected integer) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE c public.review_cycles%ROWTYPE; event public.review_cycle_events%ROWTYPE;
 pack public.review_pack_identities%ROWTYPE; coverage public.billing_paid_coverage%ROWTYPE;
 snapshot jsonb; manifest jsonb; payload jsonb; rid uuid; pid uuid; retained bigint; reserved bigint;
BEGIN
 PERFORM app_private.require_review_owner(org,actor);
 IF expected IS DISTINCT FROM 1 THEN RAISE EXCEPTION 'Review revision compare and swap failed'; END IF;
 SELECT * INTO c FROM public.review_cycles WHERE id=cid AND organization_id=org FOR UPDATE;
 IF NOT FOUND OR c.created_by_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'Review cycle owner binding invalid'; END IF;
 snapshot:=app_private.review_snapshot_manifest(c.input_snapshot_id,org);
 manifest:=jsonb_build_object('schema','stewardence.review_pack.v2','cycle_id',c.id::text,
  'organization_id',org::text,'baseline_pack_id',NULL,'snapshot',snapshot,
  'selected_decisions','[]'::jsonb,'selection_scope','empty_initial_kernel',
  'artifact_state','not_created','baseline_promotion','blocked');
 SELECT * INTO pack FROM public.review_pack_identities WHERE cycle_id=cid;
 IF FOUND THEN
  IF pack.admitted_revision IS DISTINCT FROM expected OR pack.manifest IS DISTINCT FROM manifest
   OR pack.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(manifest),'UTF8')),'hex') THEN
   RAISE EXCEPTION 'Frozen review identity replay changed'; END IF;
  RETURN pack.id;
 END IF;
 SELECT * INTO event FROM public.review_cycle_events WHERE cycle_id=cid ORDER BY revision DESC LIMIT 1;
 IF NOT FOUND OR event.revision<>expected OR event.state<>'OPEN'
  OR event.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(event.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Review state compare and swap failed'; END IF;
 IF EXISTS(SELECT 1 FROM public.review_cycles pending WHERE pending.organization_id=org AND pending.id<>cid
  AND (SELECT state FROM public.review_cycle_events e WHERE e.cycle_id=pending.id ORDER BY revision DESC LIMIT 1) IN ('FINALIZATION_REQUESTED','FROZEN')) THEN
  RAISE EXCEPTION 'Review frozen pending capacity exhausted'; END IF;
 SELECT p.* INTO coverage FROM public.billing_paid_coverage p
  JOIN public.billing_subscription s ON s.id=p.subscription_id
  JOIN public.billing_billingcustomer b ON b.id=s.billing_customer_id
  JOIN public.billing_paid_coverage_authority a ON a.id=1 AND a.stripe_account_id=p.stripe_account_id AND a.livemode=p.livemode
  WHERE s.organization_id=org AND b.user_id=actor AND s.portfolio='core'
   AND app_private.paid_subscription_access(s.id) AND p.stripe_subscription_id=s.stripe_subscription_id
   AND p.stripe_customer_id=b.stripe_customer_id AND p.service_start<=clock_timestamp() AND p.service_end>clock_timestamp()
  ORDER BY p.service_start DESC,p.service_end DESC,p.id LIMIT 1;
 IF NOT FOUND THEN RAISE EXCEPTION 'Admitted billing interval required for review reservation'; END IF;
 IF (SELECT count(*) FROM public.review_capacity_reservations r
  JOIN public.billing_paid_coverage p ON p.id=r.paid_coverage_id
  WHERE r.organization_id=org AND r.state IN ('reserved','reconciliation','consumed')
   AND p.subscription_id=coverage.subscription_id AND p.stripe_subscription_id=coverage.stripe_subscription_id
   AND p.service_start=coverage.service_start AND p.service_end=coverage.service_end)>=12 THEN
  RAISE EXCEPTION 'Review billing interval capacity exhausted'; END IF;
 SELECT coalesce(sum(size_bytes),0) INTO retained FROM public.report_artifacts WHERE organization_id=org;
 SELECT coalesce(sum(reserved_bytes),0) INTO reserved FROM public.review_capacity_reservations
  WHERE organization_id=org AND state IN ('reserved','reconciliation');
 IF retained+reserved+16777216>3221225472 THEN RAISE EXCEPTION 'Review storage reservation capacity exhausted'; END IF;
 IF NOT app_private.core_owner_entitled(org,actor) OR NOT app_private.core_work_allowed(org) THEN
  RAISE EXCEPTION 'Review paid owner admission unavailable'; END IF;
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
 RETURN pid;
END;$fn$;
ALTER FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) FROM PUBLIC,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.freeze_review_cycle(uuid,uuid,uuid,integer) TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0013_paid_entitlement"),
        ("billing", "0006_paid_coverage"),
    ]
    operations = [
        migrations.CreateModel(
            name="ReviewCycle",
            fields=common_fields()
            + [
                (
                    "input_snapshot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="assessments.assessmentsnapshot",
                    ),
                ),
                ("baseline_pack_id", models.UUIDField(null=True, editable=False)),
            ],
            options={"db_table": "review_cycles"},
        ),
        migrations.CreateModel(
            name="CycleEvent",
            fields=common_fields()
            + [
                (
                    "cycle",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="events",
                        to="reviews.reviewcycle",
                    ),
                ),
                ("revision", models.PositiveIntegerField()),
                ("state", models.CharField(max_length=32)),
                ("payload", models.JSONField(editable=False)),
                ("sha256", models.CharField(max_length=64, editable=False)),
            ],
            options={
                "db_table": "review_cycle_events",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("cycle", "revision"),
                        name="review_event_revision_unique",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="PackIdentity",
            fields=common_fields()
            + [
                (
                    "cycle",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="frozen_pack",
                        to="reviews.reviewcycle",
                    ),
                ),
                ("admitted_revision", models.PositiveIntegerField()),
                ("manifest", models.JSONField(editable=False)),
                ("sha256", models.CharField(max_length=64, editable=False)),
            ],
            options={"db_table": "review_pack_identities"},
        ),
        migrations.CreateModel(
            name="CapacityReservation",
            fields=common_fields()
            + [
                (
                    "cycle",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="capacity_reservation",
                        to="reviews.reviewcycle",
                    ),
                ),
                (
                    "paid_coverage",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to="billing.paidcoverage",
                    ),
                ),
                ("reserved_bytes", models.PositiveBigIntegerField()),
                ("state", models.CharField(default="reserved", max_length=32)),
            ],
            options={"db_table": "review_capacity_reservations"},
        ),
        migrations.CreateModel(
            name="ReservationEvent",
            fields=common_fields()
            + [
                (
                    "reservation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="events",
                        to="reviews.capacityreservation",
                    ),
                ),
                ("revision", models.PositiveIntegerField()),
                ("state", models.CharField(max_length=32)),
                ("payload", models.JSONField(editable=False)),
                ("sha256", models.CharField(max_length=64, editable=False)),
            ],
            options={
                "db_table": "review_reservation_events",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("reservation", "revision"),
                        name="review_reservation_event_unique",
                    )
                ],
            },
        ),
        migrations.RunSQL(SQL),
    ]
