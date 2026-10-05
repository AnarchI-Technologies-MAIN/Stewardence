from django.db import migrations

FORWARD_SQL = r"""
CREATE SCHEMA IF NOT EXISTS app_private AUTHORIZATION agentledger_owner;
ALTER SCHEMA app_private OWNER TO agentledger_owner;
REVOKE ALL ON SCHEMA app_private FROM PUBLIC;
GRANT USAGE ON SCHEMA app_private
    TO agentledger_owner, agentledger_app, agentledger_worker;

CREATE OR REPLACE FUNCTION app_private.current_user_id()
RETURNS UUID
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
    user_value TEXT;
BEGIN
    user_value := current_setting('app.current_user_id', true);
    IF user_value IS NULL OR user_value = '' THEN
        RAISE EXCEPTION 'Authenticated user context is not set'
            USING ERRCODE = '42501';
    END IF;
    RETURN user_value::UUID;
END;
$$;

CREATE OR REPLACE FUNCTION app_private.current_organization_id_or_null()
RETURNS UUID
LANGUAGE sql
STABLE
SET search_path = pg_catalog
AS $$
    SELECT NULLIF(
        current_setting('app.current_organization_id', true),
        ''
    )::UUID;
$$;

CREATE OR REPLACE FUNCTION app_private.current_organization_id()
RETURNS UUID
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
    tenant_value TEXT;
BEGIN
    tenant_value := current_setting('app.current_organization_id', true);
    IF tenant_value IS NULL OR tenant_value = '' THEN
        RAISE EXCEPTION 'AgentLedger tenant context is not set'
            USING ERRCODE = '42501';
    END IF;
    RETURN tenant_value::UUID;
END;
$$;

ALTER FUNCTION app_private.current_user_id() OWNER TO agentledger_owner;
ALTER FUNCTION app_private.current_organization_id_or_null()
    OWNER TO agentledger_owner;
ALTER FUNCTION app_private.current_organization_id() OWNER TO agentledger_owner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA app_private FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.current_user_id()
    TO agentledger_owner, agentledger_app;
GRANT EXECUTE ON FUNCTION app_private.current_organization_id_or_null()
    TO agentledger_owner, agentledger_app;
GRANT EXECUTE ON FUNCTION app_private.current_organization_id()
    TO agentledger_owner, agentledger_app, agentledger_worker;

ALTER TABLE accounts_user OWNER TO agentledger_owner;
ALTER TABLE accounts_user_groups OWNER TO agentledger_owner;
ALTER TABLE accounts_user_user_permissions OWNER TO agentledger_owner;
ALTER TABLE auth_group OWNER TO agentledger_owner;
ALTER TABLE auth_group_permissions OWNER TO agentledger_owner;
ALTER TABLE auth_permission OWNER TO agentledger_owner;
ALTER TABLE django_content_type OWNER TO agentledger_owner;
ALTER TABLE django_migrations OWNER TO agentledger_owner;
ALTER TABLE django_session OWNER TO agentledger_owner;
ALTER TABLE organizations_organization OWNER TO agentledger_owner;
ALTER TABLE organizations_organizationmember OWNER TO agentledger_owner;
ALTER TABLE inventory_items OWNER TO agentledger_owner;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT SELECT, UPDATE ON accounts_user TO agentledger_app;
GRANT SELECT ON accounts_user_groups, accounts_user_user_permissions,
    auth_group, auth_group_permissions, auth_permission, django_content_type,
    django_migrations TO agentledger_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON django_session TO agentledger_app;
GRANT SELECT ON organizations_organization,
    organizations_organizationmember TO agentledger_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON inventory_items
    TO agentledger_app, agentledger_worker;

ALTER TABLE organizations_organization ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations_organization FORCE ROW LEVEL SECURITY;
ALTER TABLE organizations_organizationmember ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations_organizationmember FORCE ROW LEVEL SECURITY;
ALTER TABLE inventory_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_items FORCE ROW LEVEL SECURITY;

CREATE POLICY organizations_owner_all
ON organizations_organization
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY organizations_member_read
ON organizations_organization
FOR SELECT TO agentledger_app
USING (
    EXISTS (
        SELECT 1
        FROM organizations_organizationmember AS membership
        WHERE membership.organization_id = organizations_organization.id
          AND membership.user_id = app_private.current_user_id()
    )
);

CREATE POLICY membership_owner_all
ON organizations_organizationmember
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY membership_self_bootstrap
ON organizations_organizationmember
FOR SELECT TO agentledger_app
USING (user_id = app_private.current_user_id());

CREATE POLICY inventory_owner_all
ON inventory_items
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY inventory_items_tenant_policy
ON inventory_items
FOR ALL TO agentledger_app, agentledger_worker
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());
"""


REVERSE_SQL = r"""
DROP POLICY IF EXISTS inventory_items_tenant_policy ON inventory_items;
DROP POLICY IF EXISTS inventory_owner_all ON inventory_items;
DROP POLICY IF EXISTS membership_self_bootstrap
    ON organizations_organizationmember;
DROP POLICY IF EXISTS membership_owner_all
    ON organizations_organizationmember;
DROP POLICY IF EXISTS organizations_member_read
    ON organizations_organization;
DROP POLICY IF EXISTS organizations_owner_all
    ON organizations_organization;
ALTER TABLE inventory_items DISABLE ROW LEVEL SECURITY;
ALTER TABLE organizations_organizationmember DISABLE ROW LEVEL SECURITY;
ALTER TABLE organizations_organization DISABLE ROW LEVEL SECURITY;
DROP FUNCTION IF EXISTS app_private.current_organization_id();
DROP FUNCTION IF EXISTS app_private.current_organization_id_or_null();
DROP FUNCTION IF EXISTS app_private.current_user_id();
DROP SCHEMA IF EXISTS app_private;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("organizations", "0001_initial"),
        ("inventory", "0001_initial"),
        ("sessions", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
