"""Separately admitted payment intervals; no inferred historical coverage."""
import uuid

from django.db import migrations, models
import django.db.models.deletion


SQL = r"""
ALTER TABLE billing_paid_coverage OWNER TO agentledger_owner;
ALTER TABLE billing_paid_coverage_authority OWNER TO agentledger_owner;
REVOKE ALL ON billing_paid_coverage, billing_paid_coverage_authority FROM PUBLIC, agentledger_app, agentledger_worker, agentledger_billing_admission;
ALTER TABLE billing_paid_coverage ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_paid_coverage FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_paid_coverage_authority ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_paid_coverage_authority FORCE ROW LEVEL SECURITY;
CREATE POLICY coverage_owner ON billing_paid_coverage TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY coverage_authority_owner ON billing_paid_coverage_authority TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY coverage_authority_read ON billing_paid_coverage_authority FOR SELECT TO agentledger_app,agentledger_worker USING(true);
CREATE POLICY coverage_app_read ON billing_paid_coverage FOR SELECT TO agentledger_app
 USING(EXISTS(SELECT 1 FROM billing_subscription s WHERE s.id=subscription_id));
CREATE POLICY coverage_worker_read ON billing_paid_coverage FOR SELECT TO agentledger_worker
 USING(EXISTS(SELECT 1 FROM billing_subscription s WHERE s.id=subscription_id));
GRANT SELECT ON billing_paid_coverage, billing_paid_coverage_authority TO agentledger_app,agentledger_worker;
GRANT SELECT ON billing_billingcustomer TO agentledger_worker;
CREATE POLICY coverage_worker_customer_read ON billing_billingcustomer FOR SELECT TO agentledger_worker
 USING(EXISTS(SELECT 1 FROM billing_subscription s WHERE s.billing_customer_id=billing_billingcustomer.id));

CREATE FUNCTION app_private.prevent_paid_coverage_mutation() RETURNS trigger LANGUAGE plpgsql AS $fn$
BEGIN RAISE EXCEPTION 'Paid coverage is immutable'; END;$fn$;
ALTER FUNCTION app_private.prevent_paid_coverage_mutation() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.prevent_paid_coverage_mutation() FROM PUBLIC;
CREATE TRIGGER immutable_paid_coverage BEFORE UPDATE OR DELETE ON billing_paid_coverage
 FOR EACH ROW EXECUTE FUNCTION app_private.prevent_paid_coverage_mutation();

CREATE FUNCTION app_private.issue_paid_coverage(e jsonb) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE s public.billing_subscription%ROWTYPE; c public.billing_billingcustomer%ROWTYPE;
 a public.billing_paid_coverage_authority%ROWTYPE; existing public.billing_paid_coverage%ROWTYPE;
 receipt uuid; starts timestamptz; ends timestamptz; paid timestamptz; amount integer;
 required text[]:=ARRAY['schema','subscription_id','stripe_subscription_id','stripe_customer_id',
 'stripe_account_id','livemode','stripe_invoice_id','stripe_event_id','contract_version','phase',
 'stripe_price_id','amount_cents','currency','service_start','service_end','paid_at','evidence_sha256'];
 key text; contract jsonb;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Read committed admission required'; END IF;
 IF jsonb_typeof(e)<>'object' OR octet_length(e::text)>8192 OR NOT e ?& required
  OR EXISTS(SELECT 1 FROM jsonb_object_keys(e) k WHERE NOT k=ANY(required)) THEN
  RAISE EXCEPTION 'Invalid coverage envelope'; END IF;
 FOREACH key IN ARRAY required LOOP
  IF key NOT IN ('livemode','amount_cents','service_start','service_end','paid_at')
   AND (jsonb_typeof(e->key)<>'string' OR length(e->>key)<1 OR length(e->>key)>255) THEN
   RAISE EXCEPTION 'Invalid coverage identity'; END IF;
 END LOOP;
 IF e->>'schema'<>'stewardence.paid_coverage.v1' OR e->>'contract_version'<>'core.monthly.v1'
  OR e->>'currency'<>'usd' OR jsonb_typeof(e->'livemode')<>'boolean'
  OR e->>'evidence_sha256' !~ '^[0-9a-f]{64}$'
  OR e->>'stripe_subscription_id' !~ '^sub_[A-Za-z0-9_]+$'
  OR e->>'stripe_customer_id' !~ '^cus_[A-Za-z0-9_]+$'
  OR e->>'stripe_account_id' !~ '^acct_[A-Za-z0-9_]+$'
  OR e->>'stripe_invoice_id' !~ '^in_[A-Za-z0-9_]+$'
  OR e->>'stripe_event_id' !~ '^evt_[A-Za-z0-9_]+$'
  OR e->>'stripe_price_id' !~ '^price_[A-Za-z0-9_]+$' THEN RAISE EXCEPTION 'Unsupported payment identity'; END IF;
 FOREACH key IN ARRAY ARRAY['amount_cents','service_start','service_end','paid_at'] LOOP
  IF jsonb_typeof(e->key)<>'number' OR e->>key !~ '^[0-9]{1,12}$' THEN
   RAISE EXCEPTION 'Coverage quantities must be exact positive integers'; END IF;
 END LOOP;
 amount:=(e->>'amount_cents')::integer;
 starts:=to_timestamp((e->>'service_start')::bigint);
 ends:=to_timestamp((e->>'service_end')::bigint);
 paid:=to_timestamp((e->>'paid_at')::bigint);
 IF starts<=to_timestamp(0) OR ends<=starts OR ends-starts>interval '32 days'
  OR paid<starts OR paid>clock_timestamp() OR paid>=ends THEN RAISE EXCEPTION 'Invalid paid interval'; END IF;
 SELECT * INTO a FROM public.billing_paid_coverage_authority WHERE id=1 FOR SHARE;
 IF NOT FOUND OR a.stripe_account_id<>e->>'stripe_account_id' OR a.livemode<>(e->>'livemode')::boolean THEN
  RAISE EXCEPTION 'Unconfigured or mismatched payment authority'; END IF;
 contract:=a.contracts->(e->>'phase');
 IF contract IS NULL OR jsonb_typeof(contract)<>'object'
  OR contract->>'price_id' IS DISTINCT FROM e->>'stripe_price_id'
  OR contract->>'contract_version' IS DISTINCT FROM e->>'contract_version'
  OR contract->'amount_cents' IS DISTINCT FROM e->'amount_cents' THEN
  RAISE EXCEPTION 'Unregistered payment price contract'; END IF;
 SELECT * INTO s FROM public.billing_subscription WHERE id=(e->>'subscription_id')::uuid FOR UPDATE;
 IF NOT FOUND OR s.portfolio<>'core' OR s.stripe_subscription_id IS DISTINCT FROM e->>'stripe_subscription_id'
  OR s.status='canceled' THEN RAISE EXCEPTION 'Payment subscription generation mismatch'; END IF;
 SELECT * INTO c FROM public.billing_billingcustomer WHERE id=s.billing_customer_id;
 IF c.stripe_customer_id IS DISTINCT FROM e->>'stripe_customer_id' THEN RAISE EXCEPTION 'Payment customer mismatch'; END IF;
 IF NOT ((e->>'phase'='standard' AND amount=9900 AND NOT s.is_founder)
  OR (e->>'phase'='founder_intro' AND amount=4900 AND s.is_founder AND s.founder_sequence IS NOT NULL
   AND s.founder_intro_ends_at IS NOT NULL AND starts<s.founder_intro_ends_at AND ends<=s.founder_intro_ends_at)
  OR (e->>'phase'='founder_ongoing' AND amount=7500 AND s.is_founder AND s.founder_sequence IS NOT NULL
   AND s.founder_intro_ends_at IS NOT NULL AND starts>=s.founder_intro_ends_at)) THEN
  RAISE EXCEPTION 'Unsupported paid contract'; END IF;
 SELECT * INTO existing FROM public.billing_paid_coverage WHERE stripe_account_id=a.stripe_account_id
  AND livemode=a.livemode AND stripe_invoice_id=e->>'stripe_invoice_id';
 IF FOUND THEN
  IF existing.admission_payload - 'stripe_event_id' IS DISTINCT FROM e - 'stripe_event_id' THEN
   RAISE EXCEPTION 'Conflicting invoice admission'; END IF;
  RETURN existing.id;
 END IF;
 receipt:=gen_random_uuid();
 INSERT INTO public.billing_paid_coverage(id,subscription_id,stripe_subscription_id,stripe_customer_id,
  stripe_account_id,livemode,stripe_invoice_id,stripe_event_id,contract_version,phase,stripe_price_id,
  amount_cents,currency,service_start,service_end,paid_at,evidence_sha256,admitted_at,admission_payload)
 VALUES(receipt,s.id,s.stripe_subscription_id,c.stripe_customer_id,a.stripe_account_id,a.livemode,
  e->>'stripe_invoice_id',e->>'stripe_event_id',e->>'contract_version',e->>'phase',e->>'stripe_price_id',
  amount,'usd',starts,ends,paid,e->>'evidence_sha256',clock_timestamp(),e);
 RETURN receipt;
END;$fn$;
ALTER FUNCTION app_private.issue_paid_coverage(jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_paid_coverage(jsonb) FROM PUBLIC,agentledger_app,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.issue_paid_coverage(jsonb) TO agentledger_billing_admission;
GRANT USAGE ON SCHEMA app_private TO agentledger_billing_admission;

CREATE FUNCTION app_private.paid_subscription_access(sid uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY INVOKER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_subscription s
  JOIN public.billing_billingcustomer c ON c.id=s.billing_customer_id
  JOIN public.billing_paid_coverage p ON p.subscription_id=s.id AND p.stripe_subscription_id=s.stripe_subscription_id
   AND p.stripe_customer_id=c.stripe_customer_id
  JOIN public.billing_paid_coverage_authority a ON a.id=1 AND a.stripe_account_id=p.stripe_account_id AND a.livemode=p.livemode
  WHERE s.id=sid AND s.portfolio='core' AND s.status IN ('active','canceling','past_due')
   AND p.service_start<=clock_timestamp() AND p.service_end>clock_timestamp())
$fn$;
ALTER FUNCTION app_private.paid_subscription_access(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.paid_subscription_access(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.paid_subscription_access(uuid) TO agentledger_app,agentledger_worker;

CREATE FUNCTION app_private.paid_subscription_export_access(sid uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY INVOKER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_subscription s
  JOIN public.billing_billingcustomer c ON c.id=s.billing_customer_id
  JOIN public.billing_paid_coverage p ON p.subscription_id=s.id AND p.stripe_customer_id=c.stripe_customer_id
  JOIN public.billing_paid_coverage_authority a ON a.id=1 AND a.stripe_account_id=p.stripe_account_id AND a.livemode=p.livemode
  WHERE s.id=sid AND s.portfolio='core' AND p.service_start<=clock_timestamp()
   AND p.service_end+interval '90 days'>clock_timestamp())
$fn$;
ALTER FUNCTION app_private.paid_subscription_export_access(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.paid_subscription_export_access(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.paid_subscription_export_access(uuid) TO agentledger_app,agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies = [("billing", "0005_billing_security"), ("jobs", "0012_core_authority_successor")]
    operations = [
        migrations.CreateModel(name="PaidCoverageAuthority", fields=[
            ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
            ("stripe_account_id", models.CharField(max_length=255)), ("livemode", models.BooleanField()),
            ("contracts", models.JSONField(default=dict)),
        ], options={"db_table": "billing_paid_coverage_authority", "constraints": [models.CheckConstraint(condition=models.Q(id=1), name="paid_authority_singleton")]}),
        migrations.CreateModel(name="PaidCoverage", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            *[(name, models.CharField(max_length=255)) for name in ("stripe_subscription_id", "stripe_customer_id", "stripe_account_id", "stripe_invoice_id", "stripe_event_id", "stripe_price_id")],
            ("livemode", models.BooleanField()), ("contract_version", models.CharField(max_length=64)),
            ("phase", models.CharField(max_length=32)), ("amount_cents", models.PositiveIntegerField()),
            ("currency", models.CharField(max_length=3)),
            *[(name, models.DateTimeField()) for name in ("service_start", "service_end", "paid_at")],
            ("evidence_sha256", models.CharField(max_length=64)),
            ("admitted_at", models.DateTimeField(editable=False)), ("admission_payload", models.JSONField(editable=False)),
            ("subscription", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="billing.subscription")),
        ], options={"db_table": "billing_paid_coverage", "constraints": [
            models.UniqueConstraint(fields=("stripe_account_id", "livemode", "stripe_invoice_id"), name="paid_coverage_invoice_unique"),
            models.CheckConstraint(condition=models.Q(service_end__gt=models.F("service_start")), name="paid_coverage_positive_interval"),
        ]}),
        migrations.RunSQL(SQL),
    ]
