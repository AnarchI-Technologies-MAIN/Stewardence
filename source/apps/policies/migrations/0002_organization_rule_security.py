from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE organization_rules OWNER TO agentledger_owner;

REVOKE ALL ON organization_rules FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON organization_rules TO agentledger_app;
GRANT SELECT ON organization_rules TO agentledger_worker;

ALTER TABLE organization_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE organization_rules FORCE ROW LEVEL SECURITY;

CREATE POLICY organization_rules_owner_all
ON organization_rules
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY organization_rules_app_tenant
ON organization_rules
FOR ALL TO agentledger_app
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());

CREATE POLICY organization_rules_worker_read
ON organization_rules
FOR SELECT TO agentledger_worker
USING (organization_id = app_private.current_organization_id());
"""


REVERSE_SQL = r"""
DROP POLICY IF EXISTS organization_rules_worker_read ON organization_rules;
DROP POLICY IF EXISTS organization_rules_app_tenant ON organization_rules;
DROP POLICY IF EXISTS organization_rules_owner_all ON organization_rules;
ALTER TABLE organization_rules DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("policies", "0001_initial"),
        ("inventory", "0003_remove_inventoryitem_product_id_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
