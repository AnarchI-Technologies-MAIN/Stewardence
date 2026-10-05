from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE inventory_import_batches OWNER TO agentledger_owner;
ALTER TABLE inventory_import_rows OWNER TO agentledger_owner;

REVOKE ALL ON inventory_import_batches, inventory_import_rows FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON inventory_import_batches, inventory_import_rows TO agentledger_app;

ALTER TABLE inventory_import_batches
    ADD CONSTRAINT import_batch_id_org_unique UNIQUE (id, organization_id);
ALTER TABLE inventory_import_rows
    ADD CONSTRAINT import_row_batch_org_fk
    FOREIGN KEY (batch_id, organization_id)
    REFERENCES inventory_import_batches (id, organization_id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE inventory_import_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_import_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE inventory_import_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_import_rows FORCE ROW LEVEL SECURITY;

CREATE POLICY import_batches_owner_all
ON inventory_import_batches
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY import_batches_tenant_policy
ON inventory_import_batches
FOR ALL TO agentledger_app
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());

CREATE POLICY import_rows_owner_all
ON inventory_import_rows
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY import_rows_tenant_policy
ON inventory_import_rows
FOR ALL TO agentledger_app
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());
"""

REVERSE_SQL = r"""
DROP POLICY IF EXISTS import_rows_tenant_policy ON inventory_import_rows;
DROP POLICY IF EXISTS import_rows_owner_all ON inventory_import_rows;
DROP POLICY IF EXISTS import_batches_tenant_policy ON inventory_import_batches;
DROP POLICY IF EXISTS import_batches_owner_all ON inventory_import_batches;
ALTER TABLE inventory_import_rows DISABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_import_batches DISABLE ROW LEVEL SECURITY;
ALTER TABLE inventory_import_rows DROP CONSTRAINT IF EXISTS import_row_batch_org_fk;
ALTER TABLE inventory_import_batches
    DROP CONSTRAINT IF EXISTS import_batch_id_org_unique;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0001_initial"),
        ("inventory", "0003_remove_inventoryitem_product_id_and_more"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
