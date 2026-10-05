"""Exact payment-ingester effects, unavailable to app/worker runtime roles."""
import uuid
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

SQL = r"""
ALTER TABLE public.billing_admission_receipt ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE public.billing_admission_receipt ALTER COLUMN committed_at SET DEFAULT clock_timestamp();
ALTER TABLE public.billing_admission_receipt OWNER TO agentledger_owner;
REVOKE ALL ON public.billing_admission_receipt FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE public.billing_admission_receipt ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.billing_admission_receipt FORCE ROW LEVEL SECURITY;
CREATE POLICY admission_receipt_owner ON public.billing_admission_receipt TO agentledger_owner USING(true) WITH CHECK(true);
CREATE TRIGGER immutable_admission_receipt BEFORE UPDATE OR DELETE ON public.billing_admission_receipt
 FOR EACH ROW EXECUTE FUNCTION app_private.prevent_paid_coverage_mutation();

CREATE FUNCTION app_private.paid_admission_authority_ready(account_external text,mode boolean) RETURNS boolean
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_paid_coverage_authority WHERE id=1
  AND stripe_account_id=account_external AND livemode=mode)
$fn$;
ALTER FUNCTION app_private.paid_admission_authority_ready(text,boolean) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.paid_admission_authority_ready(text,boolean) FROM PUBLIC,agentledger_app,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.paid_admission_authority_ready(text,boolean) TO agentledger_billing_admission;

CREATE FUNCTION app_private.committed_paid_admission(account_external text,mode boolean,event_external text,
 event_kind text,payload_hash text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE receipt public.billing_admission_receipt%ROWTYPE;
BEGIN
 IF account_external IS NULL OR account_external !~ '^acct_[A-Za-z0-9_]+$'
  OR mode IS NULL OR event_kind IS DISTINCT FROM 'invoice.paid' OR event_external IS NULL
  OR event_external !~ '^evt_[A-Za-z0-9_]+$' OR length(event_external)>255
  OR payload_hash IS NULL OR payload_hash !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Unsupported committed event identity'; END IF;
 SELECT * INTO receipt FROM public.billing_admission_receipt WHERE stripe_account_id=account_external
  AND livemode=mode AND stripe_event_id=event_external;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM public.billing_admission_receipt WHERE stripe_event_id=event_external) THEN
   RAISE EXCEPTION 'Committed event environment mismatch'; END IF;
  RETURN NULL;
 END IF;
 IF receipt.event_type IS DISTINCT FROM event_kind OR receipt.payload_sha256 IS DISTINCT FROM payload_hash THEN
  RAISE EXCEPTION 'Conflicting committed admission event'; END IF;
 RETURN receipt.coverage_id;
END;$fn$;
ALTER FUNCTION app_private.committed_paid_admission(text,boolean,text,text,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.committed_paid_admission(text,boolean,text,text,text) FROM PUBLIC,agentledger_app,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.committed_paid_admission(text,boolean,text,text,text) TO agentledger_billing_admission;

CREATE FUNCTION app_private.begin_paid_admission(customer_external text,sub_external text,account_external text,
 mode boolean,owner_external text,portfolio_external text,phase_external text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE c public.billing_billingcustomer%ROWTYPE; s public.billing_subscription%ROWTYPE;
 a public.billing_paid_coverage_authority%ROWTYPE; sid uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN RAISE EXCEPTION 'Read committed admission required'; END IF;
 IF customer_external IS NULL OR sub_external IS NULL OR length(customer_external)>255 OR length(sub_external)>255
  OR customer_external !~ '^cus_[A-Za-z0-9_]+$' OR sub_external !~ '^sub_[A-Za-z0-9_]+$'
  OR portfolio_external IS DISTINCT FROM 'core' OR owner_external IS NULL OR mode IS NULL
  OR phase_external NOT IN ('standard','founder_intro','founder_ongoing') OR phase_external IS NULL THEN
  RAISE EXCEPTION 'Unsupported initial payment identity'; END IF;
 SELECT * INTO a FROM public.billing_paid_coverage_authority WHERE id=1 FOR SHARE;
 IF NOT FOUND OR a.stripe_account_id IS DISTINCT FROM account_external OR a.livemode IS DISTINCT FROM mode THEN
  RAISE EXCEPTION 'Payment authority mismatch'; END IF;
 SELECT * INTO c FROM public.billing_billingcustomer WHERE stripe_customer_id=customer_external FOR UPDATE;
 IF NOT FOUND OR c.user_id::text IS DISTINCT FROM owner_external THEN RAISE EXCEPTION 'Unknown payment owner'; END IF;
 SELECT * INTO s FROM public.billing_subscription WHERE billing_customer_id=c.id FOR UPDATE;
 IF FOUND THEN
  IF s.portfolio<>'core' OR s.status='canceled' OR s.stripe_subscription_id IS DISTINCT FROM sub_external THEN
   RAISE EXCEPTION 'Payment generation mismatch'; END IF;
  IF (phase_external='standard' AND s.is_founder) OR (phase_external<>'standard' AND NOT s.is_founder) THEN
   RAISE EXCEPTION 'Payment founder contract mismatch'; END IF;
  RETURN s.id;
 END IF;
 IF phase_external<>'standard' THEN RAISE EXCEPTION 'New founder allocations are not admitted'; END IF;
 sid:=gen_random_uuid();
 INSERT INTO public.billing_subscription(id,billing_customer_id,portfolio,stripe_subscription_id,status,is_founder,
 founder_entitlement_ends_on_cancel,cancel_at_period_end,created_at,updated_at)
 VALUES(sid,c.id,'core',sub_external,'pending',false,true,false,clock_timestamp(),clock_timestamp());
 RETURN sid;
END;$fn$;
ALTER FUNCTION app_private.begin_paid_admission(text,text,text,boolean,text,text,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.begin_paid_admission(text,text,text,boolean,text,text,text) FROM PUBLIC,agentledger_app,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.begin_paid_admission(text,text,text,boolean,text,text,text) TO agentledger_billing_admission;

CREATE FUNCTION app_private.finish_paid_admission(e jsonb,event_kind text,payload_hash text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE receipt public.billing_admission_receipt%ROWTYPE; coverage uuid; effects text;
 s public.billing_subscription%ROWTYPE; a public.billing_paid_coverage_authority%ROWTYPE;
 latest_paid_end timestamptz; incoming_end timestamptz;
BEGIN
 IF event_kind IS DISTINCT FROM 'invoice.paid' OR payload_hash IS NULL OR payload_hash !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Unsupported admission event'; END IF;
 SELECT * INTO a FROM public.billing_paid_coverage_authority WHERE id=1 FOR SHARE;
 IF NOT FOUND OR a.stripe_account_id IS DISTINCT FROM e->>'stripe_account_id'
  OR a.livemode IS DISTINCT FROM (e->>'livemode')::boolean THEN
  RAISE EXCEPTION 'Payment authority mismatch'; END IF;
 SELECT * INTO s FROM public.billing_subscription WHERE id=(e->>'subscription_id')::uuid FOR UPDATE;
 IF NOT FOUND OR s.status='canceled' OR s.stripe_subscription_id IS DISTINCT FROM e->>'stripe_subscription_id' THEN
  RAISE EXCEPTION 'Terminal or mismatched generation'; END IF;
 incoming_end:=to_timestamp((e->>'service_end')::bigint);
 SELECT max(service_end) INTO latest_paid_end FROM public.billing_paid_coverage
  WHERE subscription_id=s.id AND stripe_subscription_id=s.stripe_subscription_id;
 IF EXISTS(SELECT 1 FROM public.billing_paid_coverage p WHERE p.subscription_id=s.id
  AND p.stripe_subscription_id=s.stripe_subscription_id AND p.service_end=incoming_end
  AND (p.phase IS DISTINCT FROM e->>'phase' OR p.stripe_price_id IS DISTINCT FROM e->>'stripe_price_id'
   OR p.amount_cents IS DISTINCT FROM (e->>'amount_cents')::integer)) THEN
  RAISE EXCEPTION 'Conflicting contract at the same service boundary'; END IF;
 effects:=encode(sha256(convert_to(e::text,'UTF8')),'hex');
 SELECT * INTO receipt FROM public.billing_admission_receipt WHERE stripe_account_id=e->>'stripe_account_id'
  AND livemode=(e->>'livemode')::boolean AND stripe_event_id=e->>'stripe_event_id';
 IF FOUND THEN
  IF receipt.event_type IS DISTINCT FROM event_kind OR receipt.payload_sha256 IS DISTINCT FROM payload_hash
   OR receipt.effect_sha256 IS DISTINCT FROM effects OR receipt.envelope IS DISTINCT FROM e THEN
   RAISE EXCEPTION 'Conflicting committed admission event'; END IF;
  RETURN receipt.coverage_id;
 END IF;
 coverage:=app_private.issue_paid_coverage(e);
 UPDATE public.billing_subscription SET
  status=CASE WHEN status IN ('pending','past_due') AND to_timestamp((e->>'service_end')::bigint)>clock_timestamp()
   THEN 'active' ELSE status END,
  current_period_end=GREATEST(current_period_end,to_timestamp((e->>'service_end')::bigint)),
  current_price_cents=CASE WHEN latest_paid_end IS NULL OR incoming_end>=latest_paid_end
   THEN (e->>'amount_cents')::integer ELSE current_price_cents END,updated_at=clock_timestamp()
 WHERE id=s.id;
 INSERT INTO public.billing_admission_receipt(stripe_account_id,livemode,stripe_event_id,event_type,payload_sha256,
 effect_sha256,envelope,coverage_id) VALUES(e->>'stripe_account_id',(e->>'livemode')::boolean,
 e->>'stripe_event_id',event_kind,payload_hash,effects,e,coverage);
 RETURN coverage;
END;$fn$;
ALTER FUNCTION app_private.finish_paid_admission(jsonb,text,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.finish_paid_admission(jsonb,text,text) FROM PUBLIC,agentledger_app,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.finish_paid_admission(jsonb,text,text) TO agentledger_billing_admission;
"""


class Migration(migrations.Migration):
    dependencies = [("billing", "0006_paid_coverage")]
    operations = [
        migrations.CreateModel(name="BillingAdmissionReceipt", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False, serialize=False)),
            *[(name, models.CharField(max_length=255)) for name in ("stripe_account_id", "stripe_event_id")],
            ("livemode", models.BooleanField()), ("event_type", models.CharField(max_length=64)),
            ("payload_sha256", models.CharField(max_length=64)), ("effect_sha256", models.CharField(max_length=64)),
            ("envelope", models.JSONField(editable=False)),
            ("coverage", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="billing.paidcoverage")),
            ("committed_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
        ], options={"db_table":"billing_admission_receipt", "constraints":[
            models.UniqueConstraint(fields=("stripe_account_id","livemode","stripe_event_id"), name="billing_admission_event_unique"),
            models.CheckConstraint(condition=models.Q(event_type="invoice.paid"), name="billing_admission_event_type"),
        ]}),
        migrations.RunSQL(SQL),
    ]
