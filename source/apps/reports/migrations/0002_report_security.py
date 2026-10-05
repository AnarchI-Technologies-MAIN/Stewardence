from django.db import migrations

FORWARD_SQL = r"""
CREATE SEQUENCE report_identifier_sequence
AS BIGINT
START WITH 1
INCREMENT BY 1
NO CYCLE;

ALTER SEQUENCE report_identifier_sequence
OWNER TO agentledger_owner;

REVOKE ALL ON SEQUENCE report_identifier_sequence FROM PUBLIC;
GRANT USAGE, SELECT ON SEQUENCE report_identifier_sequence
TO agentledger_app;

ALTER TABLE reports OWNER TO agentledger_owner;
REVOKE ALL ON reports FROM PUBLIC;
GRANT SELECT, INSERT ON reports TO agentledger_app;
GRANT SELECT ON reports TO agentledger_worker;

ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE reports FORCE ROW LEVEL SECURITY;

CREATE POLICY reports_owner_all
ON reports
FOR ALL
TO agentledger_owner
USING (true)
WITH CHECK (true);

CREATE POLICY reports_app_tenant
ON reports
FOR ALL
TO agentledger_app
USING (
    organization_id = app_private.current_organization_id()
)
WITH CHECK (
    organization_id = app_private.current_organization_id()
);

CREATE POLICY reports_worker_tenant
ON reports
FOR SELECT
TO agentledger_worker
USING (
    organization_id = app_private.current_organization_id()
);

CREATE OR REPLACE FUNCTION app_private.enforce_report_snapshot_tenant()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM assessment_snapshots
        WHERE id = NEW.assessment_snapshot_id
          AND organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'report snapshot must belong to the report tenant';
    END IF;

    RETURN NEW;
END;
$function$;

ALTER FUNCTION app_private.enforce_report_snapshot_tenant()
OWNER TO agentledger_owner;

REVOKE ALL
ON FUNCTION app_private.enforce_report_snapshot_tenant()
FROM PUBLIC;

CREATE TRIGGER reports_snapshot_tenant
BEFORE INSERT
ON reports
FOR EACH ROW
EXECUTE FUNCTION app_private.enforce_report_snapshot_tenant();

CREATE OR REPLACE FUNCTION app_private.reject_report_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'report identity records are immutable';
END;
$function$;

ALTER FUNCTION app_private.reject_report_mutation()
OWNER TO agentledger_owner;

REVOKE ALL
ON FUNCTION app_private.reject_report_mutation()
FROM PUBLIC;

CREATE TRIGGER reports_immutable
BEFORE UPDATE OR DELETE
ON reports
FOR EACH ROW
EXECUTE FUNCTION app_private.reject_report_mutation();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS reports_immutable ON reports;
DROP FUNCTION IF EXISTS app_private.reject_report_mutation();

DROP TRIGGER IF EXISTS reports_snapshot_tenant ON reports;
DROP FUNCTION IF EXISTS app_private.enforce_report_snapshot_tenant();

DROP POLICY IF EXISTS reports_worker_tenant ON reports;
DROP POLICY IF EXISTS reports_app_tenant ON reports;
DROP POLICY IF EXISTS reports_owner_all ON reports;

ALTER TABLE reports DISABLE ROW LEVEL SECURITY;
DROP SEQUENCE IF EXISTS report_identifier_sequence;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0001_initial"),
        ("audit", "0002_audit_security"),
    ]

    operations = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            reverse_sql=REVERSE_SQL,
        ),
    ]
