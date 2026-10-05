"""Freeze create body and hold ambiguous customer creation after 23 hours."""
import uuid
from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion

SQL=r"""
CREATE FUNCTION app_private.protect_bound_stripe_customer() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fn$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
  OR (OLD.stripe_customer_id IS NOT NULL AND NEW.stripe_customer_id IS DISTINCT FROM OLD.stripe_customer_id) THEN
  RAISE EXCEPTION 'Bound billing customer identity is immutable'; END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.protect_bound_stripe_customer() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_bound_stripe_customer() FROM PUBLIC;
CREATE TRIGGER immutable_bound_billing_customer BEFORE UPDATE ON billing_billingcustomer
 FOR EACH ROW EXECUTE FUNCTION app_private.protect_bound_stripe_customer();
ALTER TABLE billing_customer_requests OWNER TO agentledger_owner;
REVOKE ALL ON billing_customer_requests FROM PUBLIC,agentledger_app,agentledger_worker,agentledger_billing_admission;
ALTER TABLE billing_customer_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_customer_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY customer_request_owner ON billing_customer_requests TO agentledger_owner USING(true) WITH CHECK(true);
CREATE POLICY customer_request_app ON billing_customer_requests FOR SELECT TO agentledger_app USING(owner_id=app_private.current_user_id());
GRANT SELECT ON billing_customer_requests TO agentledger_app;
CREATE FUNCTION app_private.protect_customer_request() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $fn$
BEGIN
 IF TG_OP='DELETE' OR current_user<>'agentledger_owner' THEN RAISE EXCEPTION 'Customer request history cannot change'; END IF;
 IF to_jsonb(NEW)-'observed_customer_id' IS DISTINCT FROM to_jsonb(OLD)-'observed_customer_id'
  OR (OLD.observed_customer_id IS NOT NULL AND NEW.observed_customer_id IS DISTINCT FROM OLD.observed_customer_id) THEN
  RAISE EXCEPTION 'Customer request identity is immutable'; END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.protect_customer_request() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_customer_request() FROM PUBLIC;
CREATE TRIGGER immutable_customer_request BEFORE UPDATE OR DELETE ON billing_customer_requests
 FOR EACH ROW EXECUTE FUNCTION app_private.protect_customer_request();

CREATE FUNCTION app_private.reserve_customer_request(customer uuid,actor uuid,email_value text,name_value text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE c public.billing_billingcustomer%ROWTYPE; r public.billing_customer_requests%ROWTYPE;
 a public.billing_paid_coverage_authority%ROWTYPE; params jsonb; rid uuid;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' OR actor IS NULL OR actor IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Customer request owner required'; END IF;
 SELECT * INTO c FROM public.billing_billingcustomer WHERE id=customer FOR UPDATE;
 IF NOT FOUND OR c.user_id IS DISTINCT FROM actor THEN RAISE EXCEPTION 'Customer request ownership mismatch'; END IF;
 SELECT * INTO r FROM public.billing_customer_requests WHERE billing_customer_id=customer;
 IF FOUND THEN RETURN r.id; END IF;
 SELECT * INTO a FROM public.billing_paid_coverage_authority WHERE id=1 FOR SHARE;
 IF NOT FOUND OR a.stripe_account_id !~ '^acct_[A-Za-z0-9_]+$' THEN RAISE EXCEPTION 'Customer create authority unavailable'; END IF;
 IF c.stripe_customer_id IS NOT NULL THEN RAISE EXCEPTION 'Customer is already bound; creation unavailable'; END IF;
 IF email_value IS NULL OR length(email_value)>254 OR email_value !~ '^[^[:space:]@]+@[^[:space:]@]+$'
  OR length(coalesce(name_value,''))>255 THEN RAISE EXCEPTION 'Unsupported customer create body'; END IF;
 params:=jsonb_build_object('email',email_value,'name',NULLIF(name_value,''),'metadata',jsonb_build_object('stewardence_user_id',actor::text));
 rid:=gen_random_uuid();
 INSERT INTO public.billing_customer_requests(id,billing_customer_id,owner_id,generation,stripe_account_id,livemode,params,params_sha256,idempotency_key,created_at)
 VALUES(rid,customer,actor,gen_random_uuid(),a.stripe_account_id,a.livemode,params,encode(sha256(convert_to(app_private.queue_canonical(params),'UTF8')),'hex'),
  'stewardence-customer-v1:'||customer::text,clock_timestamp());
 RETURN rid;
END;$fn$;
ALTER FUNCTION app_private.reserve_customer_request(uuid,uuid,text,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.reserve_customer_request(uuid,uuid,text,text) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.reserve_customer_request(uuid,uuid,text,text) TO agentledger_app;

CREATE FUNCTION app_private.customer_create_allowed(rid uuid) RETURNS boolean
LANGUAGE sql VOLATILE SECURITY INVOKER SET search_path=pg_catalog,public AS $fn$
 SELECT EXISTS(SELECT 1 FROM public.billing_customer_requests r JOIN public.billing_billingcustomer c ON c.id=r.billing_customer_id
  JOIN public.billing_paid_coverage_authority a ON a.id=1 AND a.stripe_account_id=r.stripe_account_id AND a.livemode=r.livemode
  WHERE r.id=rid AND c.stripe_customer_id IS NULL AND r.observed_customer_id IS NULL
   AND r.created_at>clock_timestamp()-interval '23 hours'
   AND r.created_at<=clock_timestamp()
   AND r.params_sha256=encode(sha256(convert_to(app_private.queue_canonical(r.params),'UTF8')),'hex'))
$fn$;
ALTER FUNCTION app_private.customer_create_allowed(uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.customer_create_allowed(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.customer_create_allowed(uuid) TO agentledger_app;

CREATE FUNCTION app_private.record_customer_observation(rid uuid,gen uuid,external text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE r public.billing_customer_requests%ROWTYPE; c public.billing_billingcustomer%ROWTYPE;
BEGIN
 -- Customer first matches reservation ordering; avoid request/customer inversion.
 SELECT * INTO r FROM public.billing_customer_requests WHERE id=rid;
 IF NOT FOUND OR r.owner_id IS DISTINCT FROM app_private.current_user_id() OR gen IS DISTINCT FROM r.generation
  OR external IS NULL OR length(external)>255 OR external !~ '^cus_[A-Za-z0-9_]+$' THEN RAISE EXCEPTION 'Customer observation binding invalid'; END IF;
 SELECT * INTO c FROM public.billing_billingcustomer WHERE id=r.billing_customer_id FOR UPDATE;
 SELECT * INTO r FROM public.billing_customer_requests WHERE id=rid FOR UPDATE;
 IF c.user_id IS DISTINCT FROM app_private.current_user_id() OR
  (c.stripe_customer_id IS NOT NULL AND c.stripe_customer_id IS DISTINCT FROM external)
  OR (r.observed_customer_id IS NOT NULL AND r.observed_customer_id IS DISTINCT FROM external) THEN
  RAISE EXCEPTION 'Customer observation requires reconciliation'; END IF;
 UPDATE public.billing_billingcustomer SET stripe_customer_id=external WHERE id=c.id;
 UPDATE public.billing_customer_requests SET observed_customer_id=external WHERE id=rid;
END;$fn$;
ALTER FUNCTION app_private.record_customer_observation(uuid,uuid,text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.record_customer_observation(uuid,uuid,text) FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.record_customer_observation(uuid,uuid,text) TO agentledger_app;
"""

class Migration(migrations.Migration):
    dependencies=[('billing','0008_checkout_intent')]
    operations=[migrations.CreateModel(name='BillingCustomerRequest',fields=[
        ('id',models.UUIDField(default=uuid.uuid4,primary_key=True,editable=False,serialize=False)),
        ('generation',models.UUIDField(unique=True,editable=False)),('params',models.JSONField(editable=False)),
        ('stripe_account_id',models.CharField(max_length=255,editable=False)),('livemode',models.BooleanField(editable=False)),
        ('params_sha256',models.CharField(max_length=64,editable=False)),
        ('idempotency_key',models.CharField(max_length=255,unique=True,editable=False)),
        ('created_at',models.DateTimeField(editable=False)),('observed_customer_id',models.CharField(max_length=255,null=True,editable=False)),
        ('billing_customer',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,to='billing.billingcustomer')),
        ('owner',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
    ],options={'db_table':'billing_customer_requests'}),migrations.RunSQL(SQL)]
