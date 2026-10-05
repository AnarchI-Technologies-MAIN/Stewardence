from django.db import migrations

FORWARD = r"""
ALTER TABLE discovery_scans OWNER TO agentledger_owner;
ALTER TABLE detection_evidence OWNER TO agentledger_owner;
REVOKE ALL ON discovery_scans, detection_evidence FROM PUBLIC;
GRANT SELECT, INSERT ON discovery_scans, detection_evidence TO agentledger_app;
GRANT SELECT ON discovery_scans, detection_evidence TO agentledger_worker;
ALTER TABLE discovery_scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE discovery_scans FORCE ROW LEVEL SECURITY;
ALTER TABLE detection_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE detection_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY discovery_owner ON discovery_scans TO agentledger_owner
USING (true) WITH CHECK (true);
CREATE POLICY evidence_owner ON detection_evidence TO agentledger_owner
USING (true) WITH CHECK (true);
CREATE POLICY discovery_tenant ON discovery_scans TO agentledger_app, agentledger_worker
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());
CREATE POLICY evidence_tenant ON detection_evidence TO agentledger_app, agentledger_worker
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());
ALTER TABLE detection_evidence ADD CONSTRAINT evidence_parent_same_tenant
FOREIGN KEY (scan_id, organization_id) REFERENCES discovery_scans(id, organization_id);
"""

REVERSE = r"""
ALTER TABLE detection_evidence DROP CONSTRAINT evidence_parent_same_tenant;
DROP POLICY evidence_tenant ON detection_evidence;
DROP POLICY discovery_tenant ON discovery_scans;
DROP POLICY evidence_owner ON detection_evidence;
DROP POLICY discovery_owner ON discovery_scans;
REVOKE ALL ON discovery_scans, detection_evidence FROM agentledger_app, agentledger_worker;
ALTER TABLE discovery_scans DISABLE ROW LEVEL SECURITY;
ALTER TABLE detection_evidence DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [("inventory", "0004_discovery_evidence")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
