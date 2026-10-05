"""Capture reports require owner access even before pack request association."""

from django.db import migrations

SQL = r"""
CREATE OR REPLACE FUNCTION app_private.report_read_allowed(rid uuid,org uuid)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
 SELECT org=app_private.current_organization_id() AND (
  (NOT EXISTS(SELECT 1 FROM public.review_artifact_requests
              WHERE report_id=rid AND organization_id=org)
   AND NOT EXISTS(SELECT 1 FROM public.reports r
                  JOIN public.assessment_snapshots s ON s.id=r.assessment_snapshot_id
                  WHERE r.id=rid AND r.organization_id=org AND s.organization_id=org
                   AND s.input_payload->'snapshot_schema_version'='2'::jsonb))
  OR EXISTS(SELECT 1 FROM public.organizations_organizationmember
            WHERE organization_id=org AND user_id=app_private.current_user_id()
             AND role='owner'))
$fn$;
ALTER FUNCTION app_private.report_read_allowed(uuid,uuid) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.report_read_allowed(uuid,uuid)
 FROM PUBLIC,agentledger_worker,agentledger_billing_admission;
GRANT EXECUTE ON FUNCTION app_private.report_read_allowed(uuid,uuid) TO agentledger_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0005_review_pack_read_authority"),
        ("assessments", "0003_deliberate_capture"),
    ]
    operations = [migrations.RunSQL(SQL)]
