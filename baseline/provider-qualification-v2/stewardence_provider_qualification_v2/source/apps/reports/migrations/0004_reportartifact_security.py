from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE report_artifacts OWNER TO agentledger_owner;

REVOKE ALL ON report_artifacts FROM PUBLIC;
REVOKE ALL ON report_artifacts FROM agentledger_app;
REVOKE ALL ON report_artifacts FROM agentledger_worker;

GRANT SELECT
ON report_artifacts
TO agentledger_app;

GRANT SELECT, INSERT
ON report_artifacts
TO agentledger_worker;

ALTER TABLE report_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_artifacts FORCE ROW LEVEL SECURITY;


CREATE POLICY report_artifacts_owner_all
ON report_artifacts
FOR ALL
TO agentledger_owner
USING (true)
WITH CHECK (true);


CREATE POLICY report_artifacts_app_tenant
ON report_artifacts
FOR SELECT
TO agentledger_app
USING (
    organization_id = app_private.current_organization_id()
);


CREATE POLICY report_artifacts_worker_tenant
ON report_artifacts
FOR ALL
TO agentledger_worker
USING (
    organization_id = app_private.current_organization_id()
)
WITH CHECK (
    organization_id = app_private.current_organization_id()
);


CREATE OR REPLACE FUNCTION app_private.enforce_report_artifact_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    expected_snapshot uuid;
    expected_organization uuid;
    expected_key text;
BEGIN
    SELECT
        assessment_snapshot_id,
        organization_id
    INTO
        expected_snapshot,
        expected_organization
    FROM reports
    WHERE id = NEW.report_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'report artifact report does not exist';
    END IF;

    IF expected_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'report artifact tenant must match report tenant';
    END IF;

    IF expected_snapshot <> NEW.assessment_snapshot_id THEN
        RAISE EXCEPTION 'report artifact snapshot must match report snapshot';
    END IF;

    expected_key :=
        'organizations/' || NEW.organization_id::text ||
        '/assessments/' || NEW.assessment_snapshot_id::text ||
        '/reports/' || NEW.report_id::text || '.pdf';

    IF NEW.object_key <> expected_key THEN
        RAISE EXCEPTION 'report artifact object key is not canonical';
    END IF;

    IF NEW.content_type <> 'application/pdf' THEN
        RAISE EXCEPTION 'report artifact content type must be application/pdf';
    END IF;

    IF NEW.sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'report artifact SHA-256 must be lowercase hexadecimal';
    END IF;

    IF NEW.size_bytes < 1 THEN
        RAISE EXCEPTION 'report artifact size must be positive';
    END IF;

    RETURN NEW;
END;
$function$;

ALTER FUNCTION app_private.enforce_report_artifact_identity()
OWNER TO agentledger_owner;

REVOKE ALL
ON FUNCTION app_private.enforce_report_artifact_identity()
FROM PUBLIC;


CREATE TRIGGER report_artifacts_identity
BEFORE INSERT
ON report_artifacts
FOR EACH ROW
EXECUTE FUNCTION app_private.enforce_report_artifact_identity();


CREATE OR REPLACE FUNCTION app_private.reject_report_artifact_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'report artifact metadata is immutable';
END;
$function$;

ALTER FUNCTION app_private.reject_report_artifact_mutation()
OWNER TO agentledger_owner;

REVOKE ALL
ON FUNCTION app_private.reject_report_artifact_mutation()
FROM PUBLIC;


CREATE TRIGGER report_artifacts_immutable
BEFORE UPDATE OR DELETE
ON report_artifacts
FOR EACH ROW
EXECUTE FUNCTION app_private.reject_report_artifact_mutation();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS report_artifacts_immutable ON report_artifacts;
DROP FUNCTION IF EXISTS app_private.reject_report_artifact_mutation();

DROP TRIGGER IF EXISTS report_artifacts_identity ON report_artifacts;
DROP FUNCTION IF EXISTS app_private.enforce_report_artifact_identity();

DROP POLICY IF EXISTS report_artifacts_worker_tenant ON report_artifacts;
DROP POLICY IF EXISTS report_artifacts_app_tenant ON report_artifacts;
DROP POLICY IF EXISTS report_artifacts_owner_all ON report_artifacts;

ALTER TABLE report_artifacts DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0003_reportartifact"),
    ]

    operations = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            reverse_sql=REVERSE_SQL,
        ),
    ]
