from django.db import migrations

FORWARD = r"""
-- Runtime registration may only create ordinary, active accounts.
CREATE FUNCTION app_private.guard_public_registration()
RETURNS trigger LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
BEGIN
    IF current_user = 'agentledger_app' AND (
        NEW.is_staff IS DISTINCT FROM false OR
        NEW.is_superuser IS DISTINCT FROM false OR
        NEW.is_active IS DISTINCT FROM true
    ) THEN
        RAISE EXCEPTION 'Public registration cannot create privileged accounts'
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END;
$$;
ALTER FUNCTION app_private.guard_public_registration() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.guard_public_registration() FROM PUBLIC;
CREATE TRIGGER public_registration_guard BEFORE INSERT ON public.accounts_user
FOR EACH ROW EXECUTE FUNCTION app_private.guard_public_registration();
GRANT INSERT ON public.accounts_user TO agentledger_app;

-- No runtime INSERT/UPDATE grant on organization or membership tables is needed.
-- The caller cannot supply an existing organization, user, membership, or role.
CREATE FUNCTION app_private.create_owned_workspace(workspace_name text, workspace_industry text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    actor uuid := app_private.current_user_id();
    new_id uuid := gen_random_uuid();
BEGIN
    IF actor IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.accounts_user WHERE id = actor AND is_active
    ) THEN
        RAISE EXCEPTION 'An active authenticated identity is required' USING ERRCODE = '42501';
    END IF;
    IF workspace_name IS NULL OR length(btrim(workspace_name)) NOT BETWEEN 1 AND 200
        OR workspace_industry IS NULL OR workspace_industry NOT IN
        ('accounting_bookkeeping', 'legal', 'healthcare', 'construction', 'agency', 'other') THEN
        RAISE EXCEPTION 'Invalid workspace details' USING ERRCODE = '22023';
    END IF;
    INSERT INTO public.organizations_organization(id, name, industry, created_at, updated_at)
        VALUES (new_id, btrim(workspace_name), workspace_industry, statement_timestamp(), statement_timestamp());
    INSERT INTO public.organizations_organizationmember(id, organization_id, user_id, role, created_at)
        VALUES (gen_random_uuid(), new_id, actor, 'owner', statement_timestamp());
    RETURN new_id;
END;
$$;
ALTER FUNCTION app_private.create_owned_workspace(text, text) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.create_owned_workspace(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.create_owned_workspace(text, text) TO agentledger_app;
"""

REVERSE = r"""
DROP FUNCTION app_private.create_owned_workspace(text, text);
REVOKE INSERT ON public.accounts_user FROM agentledger_app;
DROP TRIGGER public_registration_guard ON public.accounts_user;
DROP FUNCTION app_private.guard_public_registration();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0001_initial"),
        ("inventory", "0002_database_security"),
    ]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
