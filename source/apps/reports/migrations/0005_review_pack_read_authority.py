"""Owner-only review packs must not inherit ordinary report viewer access."""

from django.db import migrations

SQL = r"""
CREATE FUNCTION app_private.report_read_allowed(rid uuid,org uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
 SELECT org=app_private.current_organization_id() AND (
  NOT EXISTS(SELECT 1 FROM public.review_artifact_requests
             WHERE report_id=rid AND organization_id=org)
  OR EXISTS(SELECT 1 FROM public.organizations_organizationmember
            WHERE organization_id=org AND user_id=app_private.current_user_id()
             AND role='owner'))
$fn$;
ALTER FUNCTION app_private.report_read_allowed(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.report_read_allowed(uuid,uuid)
 FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.report_read_allowed(uuid,uuid) TO agentledger_app;

CREATE POLICY reports_review_owner_read ON public.reports AS RESTRICTIVE
 FOR SELECT TO agentledger_app
 USING(app_private.report_read_allowed(id,organization_id));
CREATE POLICY report_artifacts_review_owner_read ON public.report_artifacts AS RESTRICTIVE
 FOR SELECT TO agentledger_app
 USING(app_private.report_read_allowed(report_id,organization_id));
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0004_reportartifact_security"),
        ("reviews", "0003_worker_pack_projection"),
    ]
    operations = [migrations.RunSQL(SQL)]
