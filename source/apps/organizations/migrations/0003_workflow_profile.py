import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

SQL = """
ALTER TABLE organization_workflow_profiles OWNER TO agentledger_owner;
REVOKE ALL ON organization_workflow_profiles FROM PUBLIC;
GRANT SELECT, INSERT ON organization_workflow_profiles TO agentledger_app;
GRANT SELECT ON organization_workflow_profiles TO agentledger_worker;
ALTER TABLE organization_workflow_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_workflow_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY workflow_profile_owner ON organization_workflow_profiles FOR ALL TO agentledger_owner USING (true) WITH CHECK (true);
CREATE POLICY workflow_profile_tenant ON organization_workflow_profiles FOR ALL TO agentledger_app, agentledger_worker
USING (organization_id = app_private.current_organization_id()) WITH CHECK (organization_id = app_private.current_organization_id());
CREATE FUNCTION app_private.protect_workflow_profile() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, public AS $body$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Workflow profile is immutable'; END IF;
 IF NEW.profile NOT IN ('business.v1','development.v1') OR jsonb_typeof(NEW.settings) <> 'object'
    OR COALESCE(NEW.settings->>'name','') = '' THEN RAISE EXCEPTION 'Invalid workflow profile'; END IF;
 IF current_user = 'agentledger_app' AND NEW.created_by_id IS DISTINCT FROM app_private.current_user_id() THEN
  RAISE EXCEPTION 'Workflow profile actor is invalid';
 END IF;
 IF EXISTS (SELECT 1 FROM jsonb_object_keys(NEW.settings) AS fields(key) WHERE
     (NEW.profile = 'business.v1' AND key NOT IN ('name','jurisdiction','parent_branch_id')) OR
     (NEW.profile = 'development.v1' AND key NOT IN ('name','repository_ref','environment'))) THEN
  RAISE EXCEPTION 'Workflow settings do not match selected profile';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM public.organizations_organizationmember WHERE organization_id = NEW.organization_id AND user_id = NEW.created_by_id AND role = 'owner') THEN
  RAISE EXCEPTION 'Workflow profile requires workspace owner';
 END IF;
 RETURN NEW;
END;
$body$;
ALTER FUNCTION app_private.protect_workflow_profile() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_workflow_profile() FROM PUBLIC;
CREATE TRIGGER workflow_profile_guard BEFORE INSERT OR UPDATE OR DELETE ON organization_workflow_profiles
FOR EACH ROW EXECUTE FUNCTION app_private.protect_workflow_profile();
"""

class Migration(migrations.Migration):
    dependencies = [("organizations", "0002_public_onboarding"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name="WorkflowProfile", fields=[
        ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
        ("profile", models.CharField(max_length=32, choices=[("business.v1", "Business branches"), ("development.v1", "Development branches")])),
        ("settings", models.JSONField()), ("created_at", models.DateTimeField(auto_now_add=True)),
        ("created_by", models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT)),
        ("organization", models.OneToOneField(to="organizations.organization", on_delete=django.db.models.deletion.PROTECT)),
    ], options={"db_table":"organization_workflow_profiles"}),
    migrations.RunSQL(SQL, "DROP FUNCTION app_private.protect_workflow_profile() CASCADE;")]
