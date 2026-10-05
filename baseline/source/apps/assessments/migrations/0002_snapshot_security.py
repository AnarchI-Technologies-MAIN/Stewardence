from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE assessment_snapshots OWNER TO agentledger_owner;

REVOKE ALL ON assessment_snapshots FROM PUBLIC;
GRANT SELECT, INSERT ON assessment_snapshots
    TO agentledger_app, agentledger_worker;

ALTER TABLE assessment_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_snapshots FORCE ROW LEVEL SECURITY;

CREATE POLICY assessment_snapshots_owner_all
ON assessment_snapshots
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY assessment_snapshots_tenant_policy
ON assessment_snapshots
FOR ALL TO agentledger_app, agentledger_worker
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());

CREATE OR REPLACE FUNCTION app_private.reject_assessment_snapshot_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'assessment snapshots are immutable';
END;
$function$;

ALTER FUNCTION app_private.reject_assessment_snapshot_mutation()
    OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.reject_assessment_snapshot_mutation()
    FROM PUBLIC;

CREATE TRIGGER assessment_snapshots_immutable
BEFORE UPDATE OR DELETE ON assessment_snapshots
FOR EACH ROW
EXECUTE FUNCTION app_private.reject_assessment_snapshot_mutation();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS assessment_snapshots_immutable ON assessment_snapshots;
DROP FUNCTION IF EXISTS app_private.reject_assessment_snapshot_mutation();
DROP POLICY IF EXISTS assessment_snapshots_tenant_policy
    ON assessment_snapshots;
DROP POLICY IF EXISTS assessment_snapshots_owner_all
    ON assessment_snapshots;
ALTER TABLE assessment_snapshots DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("assessments", "0001_initial"),
        ("inventory", "0003_remove_inventoryitem_product_id_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
