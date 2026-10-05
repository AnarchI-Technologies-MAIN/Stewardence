"""Frozen standard checkout intent; observations cannot prove payment/expiry."""
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

SQL = r"""
ALTER TABLE billing_checkout_intents OWNER TO agentledger_owner;
REVOKE ALL ON billing_checkout_intents FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE billing_checkout_intents ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_checkout_intents FORCE ROW LEVEL SECURITY;
CREATE POLICY checkout_owner ON billing_checkout_intents TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY checkout_app_read ON billing_checkout_intents FOR SELECT TO agentledger_app
 USING(owner_id=app_private.current_user_id());
GRANT SELECT ON billing_checkout_intents TO agentledger_app;
CREATE FUNCTION app_private.protect_checkout_intent() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Checkout history cannot be deleted'; END IF;
 IF current_user<>'agentledger_owner' OR
  (to_jsonb(NEW)-ARRAY['state','stripe_session_id','observed_session_id','observed_url']) IS DISTINCT FROM
  (to_jsonb(OLD)-ARRAY['state','stripe_session_id','observed_session_id','observed_url']) THEN
  RAISE EXCEPTION 'Checkout request identity is immutable'; END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.protect_checkout_intent() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_checkout_intent() FROM PUBLIC;
CREATE TRIGGER immutable_checkout_request BEFORE UPDATE OR DELETE ON billing_checkout_intents
 FOR EACH ROW EXECUTE FUNCTION app_private.protect_checkout_intent();

CREATE FUNCTION app_private.reserve_standard_checkout(customer uuid,actor uuid,success text,cancel text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE c public.billing_billingcustomer%ROWTYPE; a public.billing_paid_coverage_authority%ROWTYPE;
 i public.billing_checkout_intents%ROWTYPE; contract jsonb; request jsonb; iid uuid; gen uuid; expiry timestamptz;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR actor IS NULL
  OR actor IS DISTINCT FROM app_private.current_user_id() THEN RAISE EXCEPTION 'Checkout owner admission required'; END IF;
 SELECT * INTO c FROM public.billing_billingcustomer WHERE id=customer FOR UPDATE;
 IF NOT FOUND OR c.user_id IS DISTINCT FROM actor OR c.stripe_customer_id IS NULL
  OR c.stripe_customer_id !~ '^cus_[A-Za-z0-9_]+$' THEN RAISE EXCEPTION 'Checkout customer binding unavailable'; END IF;
 SELECT * INTO i FROM public.billing_checkout_intents WHERE billing_customer_id=customer AND state IN ('pending','attached','complete');
 IF FOUND THEN RETURN i.id; END IF;
 IF EXISTS(SELECT 1 FROM public.billing_subscription WHERE billing_customer_id=customer
  AND stripe_subscription_id IS NOT NULL AND status<>'canceled') THEN
  RAISE EXCEPTION 'Existing subscription generation requires billing recovery'; END IF;
 SELECT * INTO a FROM public.billing_paid_coverage_authority WHERE id=1 FOR SHARE;
 IF NOT FOUND OR a.stripe_account_id !~ '^acct_[A-Za-z0-9_]+$' THEN RAISE EXCEPTION 'Checkout authority unavailable'; END IF;
 contract:=a.contracts->'standard';
 IF jsonb_typeof(contract) IS DISTINCT FROM 'object' OR contract->>'contract_version' IS DISTINCT FROM 'core.monthly.v1'
  OR contract->'amount_cents' IS DISTINCT FROM '9900'::jsonb OR contract->>'price_id' IS NULL
  OR contract->>'price_id' !~ '^price_[A-Za-z0-9_]+$' THEN RAISE EXCEPTION 'Checkout price contract unavailable'; END IF;
 IF success IS NULL OR cancel IS NULL OR length(success)>2048 OR length(cancel)>2048
  OR success !~ '^https?://' OR cancel !~ '^https?://' OR success ~ '[[:space:]]' OR cancel ~ '[[:space:]]' THEN
  RAISE EXCEPTION 'Unsupported checkout return URLs'; END IF;
 iid:=gen_random_uuid(); gen:=gen_random_uuid(); expiry:=to_timestamp(floor(extract(epoch FROM clock_timestamp()))+3600);
 request:=jsonb_build_object('mode','subscription','customer',c.stripe_customer_id,
  'client_reference_id',actor::text,'line_items',jsonb_build_array(jsonb_build_object('price',contract->>'price_id','quantity',1)),
  'success_url',success,'cancel_url',cancel,'expires_at',extract(epoch FROM expiry)::bigint,
  'metadata',jsonb_build_object('stewardence_user_id',actor::text,'portfolio','core','checkout_intent_id',iid::text,'checkout_generation',gen::text),
  'subscription_data',jsonb_build_object('metadata',jsonb_build_object('stewardence_user_id',actor::text,'portfolio','core','checkout_intent_id',iid::text,'checkout_generation',gen::text)),
  'integration_identifier','stewardence-core-'||translate(left(replace(customer::text,'-',''),8),'0123456789abcdef','abcdefghijklmnop'));
 INSERT INTO public.billing_checkout_intents(id,billing_customer_id,owner_id,generation,stripe_customer_id,stripe_account_id,
  livemode,stripe_price_id,contract_version,params,params_sha256,idempotency_key,expires_at,created_at,state)
 VALUES(iid,customer,actor,gen,c.stripe_customer_id,a.stripe_account_id,a.livemode,contract->>'price_id',
  'core.monthly.v1',request,encode(sha256(convert_to(app_private.queue_canonical(request),'UTF8')),'hex'),
  'stewardence-core-checkout-v1:'||gen::text,expiry,clock_timestamp(),'pending');
 RETURN iid;
END;$fn$;
ALTER FUNCTION app_private.reserve_standard_checkout(uuid,uuid,text,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.reserve_standard_checkout(uuid,uuid,text,text) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.reserve_standard_checkout(uuid,uuid,text,text) TO agentledger_app;

CREATE FUNCTION app_private.checkout_create_allowed(iid uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY INVOKER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_checkout_intents i
  JOIN public.billing_paid_coverage_authority a ON a.id=1 AND a.stripe_account_id=i.stripe_account_id AND a.livemode=i.livemode
  JOIN public.billing_billingcustomer c ON c.id=i.billing_customer_id AND c.stripe_customer_id=i.stripe_customer_id
  WHERE i.id=iid AND i.state='pending' AND i.expires_at>clock_timestamp()+interval '31 minutes'
   AND a.contracts->'standard'->>'price_id'=i.stripe_price_id
   AND a.contracts->'standard'->>'contract_version'=i.contract_version
   AND a.contracts->'standard'->'amount_cents'='9900'::jsonb
   AND i.params_sha256=encode(sha256(convert_to(app_private.queue_canonical(i.params),'UTF8')),'hex'))
$fn$;
ALTER FUNCTION app_private.checkout_create_allowed(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.checkout_create_allowed(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.checkout_create_allowed(uuid) TO agentledger_app;

CREATE FUNCTION app_private.record_checkout_observation(iid uuid,gen uuid,sess text,redirect text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE i public.billing_checkout_intents%ROWTYPE;
BEGIN
 SELECT * INTO i FROM public.billing_checkout_intents WHERE id=iid FOR UPDATE;
 IF NOT FOUND OR i.owner_id IS DISTINCT FROM app_private.current_user_id() OR gen IS DISTINCT FROM i.generation
  OR sess IS NULL OR sess !~ '^cs_[A-Za-z0-9_]+$' OR length(sess)>255
  OR redirect IS NULL OR length(redirect)>2048 OR redirect !~ '^https://checkout\.stripe\.com/'
  OR redirect ~ '[[:space:]]' THEN RAISE EXCEPTION 'Checkout observation binding invalid'; END IF;
 IF i.observed_session_id IS NOT NULL AND (i.observed_session_id IS DISTINCT FROM sess OR i.observed_url IS DISTINCT FROM redirect) THEN
  RAISE EXCEPTION 'Checkout observation requires reconciliation'; END IF;
 UPDATE public.billing_checkout_intents SET observed_session_id=sess,observed_url=redirect WHERE id=iid;
END;$fn$;
ALTER FUNCTION app_private.record_checkout_observation(uuid,uuid,text,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.record_checkout_observation(uuid,uuid,text,text) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.record_checkout_observation(uuid,uuid,text,text) TO agentledger_app;

CREATE FUNCTION app_private.admit_checkout_outcome(iid uuid,gen uuid,sess text,outcome text,customer text,account text,mode boolean,expiry bigint) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE i public.billing_checkout_intents%ROWTYPE; next_state text;
BEGIN
 SELECT * INTO i FROM public.billing_checkout_intents WHERE id=iid FOR UPDATE;
 IF NOT FOUND OR gen IS DISTINCT FROM i.generation OR customer IS DISTINCT FROM i.stripe_customer_id
  OR account IS DISTINCT FROM i.stripe_account_id OR mode IS DISTINCT FROM i.livemode
  OR expiry IS DISTINCT FROM extract(epoch FROM i.expires_at)::bigint
  OR sess IS NULL OR sess !~ '^cs_[A-Za-z0-9_]+$' OR length(sess)>255
  OR outcome IS NULL OR outcome NOT IN ('open','complete','expired') THEN RAISE EXCEPTION 'Authoritative checkout binding invalid'; END IF;
 IF i.stripe_session_id IS NOT NULL AND i.stripe_session_id IS DISTINCT FROM sess THEN RAISE EXCEPTION 'Checkout session changed'; END IF;
 next_state:=CASE outcome WHEN 'open' THEN 'attached' ELSE outcome END;
 IF i.state IN ('complete','expired') AND i.state IS DISTINCT FROM next_state THEN RAISE EXCEPTION 'Checkout terminal state cannot change'; END IF;
 IF outcome='expired' AND clock_timestamp()<i.expires_at THEN RAISE EXCEPTION 'Expiry is not yet authoritative'; END IF;
 UPDATE public.billing_checkout_intents SET stripe_session_id=sess,state=next_state WHERE id=iid;
 RETURN next_state;
END;$fn$;
ALTER FUNCTION app_private.admit_checkout_outcome(uuid,uuid,text,text,text,text,boolean,bigint) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.admit_checkout_outcome(uuid,uuid,text,text,text,text,boolean,bigint) FROM PUBLIC,agentledger_app,agentledger_worker;
GRANT EXECUTE ON FUNCTION app_private.admit_checkout_outcome(uuid,uuid,text,text,text,text,boolean,bigint) TO agentledger_billing_admission;
"""

class Migration(migrations.Migration):
    dependencies = [("billing", "0007_ingester_effects")]
    operations = [migrations.CreateModel(name="CheckoutIntent", fields=[
        ("id",models.UUIDField(default=uuid.uuid4,primary_key=True,editable=False,serialize=False)),
        ("generation",models.UUIDField(unique=True,editable=False)),
        *[(name,models.CharField(max_length=255)) for name in ("stripe_customer_id","stripe_account_id","stripe_price_id")],
        ("livemode",models.BooleanField()),("contract_version",models.CharField(max_length=64)),
        ("params",models.JSONField(editable=False)),("params_sha256",models.CharField(max_length=64,editable=False)),
        ("idempotency_key",models.CharField(max_length=255,unique=True,editable=False)),
        ("expires_at",models.DateTimeField(editable=False)),("created_at",models.DateTimeField(editable=False)),
        ("state",models.CharField(default="pending",max_length=16)),
        ("stripe_session_id",models.CharField(max_length=255,null=True,unique=True)),
        ("observed_session_id",models.CharField(max_length=255,null=True)),("observed_url",models.CharField(max_length=2048,null=True)),
        ("billing_customer",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to="billing.billingcustomer")),
        ("owner",models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
    ],options={"db_table":"billing_checkout_intents","constraints":[models.UniqueConstraint(fields=("billing_customer",),condition=models.Q(state__in=("pending","attached","complete")),name="checkout_one_unresolved_customer")]}),migrations.RunSQL(SQL)]
