from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE catalog_vendor OWNER TO agentledger_owner;
ALTER TABLE catalog_product OWNER TO agentledger_owner;
ALTER TABLE catalog_productidentifier OWNER TO agentledger_owner;

REVOKE ALL ON catalog_vendor, catalog_product,
    catalog_productidentifier FROM PUBLIC;
GRANT SELECT ON catalog_vendor, catalog_product,
    catalog_productidentifier TO agentledger_app, agentledger_worker;
"""

REVERSE_SQL = r"""
REVOKE ALL ON catalog_vendor, catalog_product,
    catalog_productidentifier FROM agentledger_app, agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0001_initial"),
        ("inventory", "0002_database_security"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
