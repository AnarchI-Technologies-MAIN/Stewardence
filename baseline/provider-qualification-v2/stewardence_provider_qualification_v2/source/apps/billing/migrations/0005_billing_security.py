from django.db import migrations

TABLES = (
    "billing_billingcustomer",
    "billing_subscription",
    "billing_founderslot",
    "billing_stripewebhookevent",
)
FORWARD_SQL = (
    "\n".join(  # noqa: S608 -- fixed migration identifiers only
        f"""
ALTER TABLE {table} OWNER TO agentledger_owner;
REVOKE ALL ON {table} FROM PUBLIC, agentledger_app, agentledger_worker;
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
CREATE POLICY billing_owner_all ON {table} TO agentledger_owner
USING (true) WITH CHECK (true);
"""
        for table in TABLES
    )
    + r"""
GRANT SELECT, INSERT, UPDATE ON billing_billingcustomer, billing_subscription,
    billing_founderslot TO agentledger_app;
GRANT SELECT, INSERT ON billing_stripewebhookevent TO agentledger_app;
ALTER SEQUENCE billing_stripewebhookevent_id_seq OWNER TO agentledger_owner;
REVOKE ALL ON SEQUENCE billing_stripewebhookevent_id_seq FROM PUBLIC;
GRANT USAGE, SELECT ON SEQUENCE billing_stripewebhookevent_id_seq TO agentledger_app;

CREATE POLICY billing_customer_self ON billing_billingcustomer TO agentledger_app
USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

CREATE POLICY billing_subscription_self ON billing_subscription TO agentledger_app
USING (EXISTS (SELECT 1 FROM billing_billingcustomer c
    WHERE c.id = billing_customer_id))
WITH CHECK (EXISTS (SELECT 1 FROM billing_billingcustomer c
    WHERE c.id = billing_customer_id)
    AND (organization_id IS NULL OR EXISTS (
        SELECT 1 FROM organizations_organizationmember m
        WHERE m.organization_id = billing_subscription.organization_id
          AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
          AND m.role = 'owner'
    )));

CREATE POLICY billing_founder_self_or_free ON billing_founderslot TO agentledger_app
USING (billing_customer_id IS NULL OR EXISTS (
    SELECT 1 FROM billing_billingcustomer c WHERE c.id = billing_customer_id))
WITH CHECK (billing_customer_id IS NULL OR EXISTS (
    SELECT 1 FROM billing_billingcustomer c WHERE c.id = billing_customer_id));

CREATE POLICY billing_receipt_read ON billing_stripewebhookevent
FOR SELECT TO agentledger_app USING (true);
CREATE POLICY billing_receipt_insert ON billing_stripewebhookevent
FOR INSERT TO agentledger_app WITH CHECK (true);

GRANT SELECT ON billing_subscription TO agentledger_worker;
CREATE POLICY billing_worker_entitlement ON billing_subscription
FOR SELECT TO agentledger_worker
USING (organization_id = NULLIF(current_setting('app.current_organization_id', true), '')::uuid);

-- Only aggregate availability is public to the authenticated billing workflow.
CREATE FUNCTION app_private.billing_founder_claimed() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT count(*) FROM public.billing_founderslot WHERE claimed_at IS NOT NULL;
$$;
ALTER FUNCTION app_private.billing_founder_claimed() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.billing_founder_claimed() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.billing_founder_claimed() TO agentledger_app;

-- Signed Stripe events arrive without a browser identity. Resolve only the exact
-- stored external identifier, then process inside the customer's identity context.
CREATE FUNCTION app_private.billing_event_user(external_id text, is_schedule boolean)
RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $$
    SELECT c.user_id FROM public.billing_subscription s
    JOIN public.billing_billingcustomer c ON c.id = s.billing_customer_id
    WHERE (NOT is_schedule AND s.stripe_subscription_id = external_id)
       OR (is_schedule AND s.stripe_schedule_id = external_id);
$$;
ALTER FUNCTION app_private.billing_event_user(text, boolean) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.billing_event_user(text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.billing_event_user(text, boolean) TO agentledger_app;
"""
)

# Reversal must also remove grants: never leave formerly private rows readable.
REVERSE_SQL = r"""
DROP FUNCTION app_private.billing_event_user(text, boolean);
DROP FUNCTION app_private.billing_founder_claimed();
REVOKE ALL ON SEQUENCE billing_stripewebhookevent_id_seq FROM agentledger_app;
DROP POLICY billing_customer_self ON billing_billingcustomer;
DROP POLICY billing_subscription_self ON billing_subscription;
DROP POLICY billing_founder_self_or_free ON billing_founderslot;
DROP POLICY billing_receipt_read ON billing_stripewebhookevent;
DROP POLICY billing_receipt_insert ON billing_stripewebhookevent;
DROP POLICY billing_worker_entitlement ON billing_subscription;
""" + "\n".join(
    f"""
REVOKE ALL ON {table} FROM agentledger_app, agentledger_worker;
DROP POLICY billing_owner_all ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""
    for table in TABLES
)


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0004_founderslot_reservation_token"),
        ("inventory", "0002_database_security"),
    ]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
