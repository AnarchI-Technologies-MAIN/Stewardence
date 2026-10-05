from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE audit_events OWNER TO agentledger_owner;
ALTER TABLE audit_merkle_blocks OWNER TO agentledger_owner;
ALTER TABLE audit_chain_heads OWNER TO agentledger_owner;

REVOKE ALL ON audit_events FROM PUBLIC;
REVOKE ALL ON audit_merkle_blocks FROM PUBLIC;
REVOKE ALL ON audit_chain_heads FROM PUBLIC;

GRANT SELECT, INSERT ON audit_events TO agentledger_app;
GRANT SELECT ON audit_merkle_blocks TO agentledger_app;
GRANT SELECT ON audit_chain_heads TO agentledger_app;

GRANT SELECT ON audit_events TO agentledger_worker;
GRANT UPDATE (
    node_hash,
    batch_block_id,
    batch_position
) ON audit_events TO agentledger_worker;

GRANT SELECT, INSERT ON audit_merkle_blocks TO agentledger_worker;
GRANT SELECT, INSERT, UPDATE ON audit_chain_heads TO agentledger_worker;

ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;

ALTER TABLE audit_merkle_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_merkle_blocks FORCE ROW LEVEL SECURITY;

ALTER TABLE audit_chain_heads ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_chain_heads FORCE ROW LEVEL SECURITY;


CREATE POLICY audit_events_owner_all
ON audit_events
FOR ALL
TO agentledger_owner
USING (true)
WITH CHECK (true);

CREATE POLICY audit_events_app_tenant
ON audit_events
FOR ALL
TO agentledger_app
USING (
    organization_id = app_private.current_organization_id()
)
WITH CHECK (
    organization_id = app_private.current_organization_id()
);

CREATE POLICY audit_events_worker_tenant
ON audit_events
FOR ALL
TO agentledger_worker
USING (
    organization_id = app_private.current_organization_id()
)
WITH CHECK (
    organization_id = app_private.current_organization_id()
);


CREATE POLICY audit_merkle_blocks_owner_all
ON audit_merkle_blocks
FOR ALL
TO agentledger_owner
USING (true)
WITH CHECK (true);

CREATE POLICY audit_merkle_blocks_app_tenant
ON audit_merkle_blocks
FOR SELECT
TO agentledger_app
USING (
    organization_id = app_private.current_organization_id()
);

CREATE POLICY audit_merkle_blocks_worker_tenant
ON audit_merkle_blocks
FOR ALL
TO agentledger_worker
USING (
    organization_id = app_private.current_organization_id()
)
WITH CHECK (
    organization_id = app_private.current_organization_id()
);


CREATE POLICY audit_chain_heads_owner_all
ON audit_chain_heads
FOR ALL
TO agentledger_owner
USING (true)
WITH CHECK (true);

CREATE POLICY audit_chain_heads_app_tenant
ON audit_chain_heads
FOR SELECT
TO agentledger_app
USING (
    organization_id = app_private.current_organization_id()
);

CREATE POLICY audit_chain_heads_worker_tenant
ON audit_chain_heads
FOR ALL
TO agentledger_worker
USING (
    organization_id = app_private.current_organization_id()
)
WITH CHECK (
    organization_id = app_private.current_organization_id()
);


CREATE OR REPLACE FUNCTION app_private.protect_audit_event()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit events cannot be deleted';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.occurred_at IS DISTINCT FROM OLD.occurred_at
       OR NEW.actor_user_id IS DISTINCT FROM OLD.actor_user_id
       OR NEW.event_type IS DISTINCT FROM OLD.event_type
       OR NEW.entity_type IS DISTINCT FROM OLD.entity_type
       OR NEW.entity_id IS DISTINCT FROM OLD.entity_id
       OR NEW.data IS DISTINCT FROM OLD.data
    THEN
        RAISE EXCEPTION 'audit event envelope is immutable';
    END IF;

    IF OLD.node_hash IS NOT NULL
       OR OLD.batch_block_id IS NOT NULL
       OR OLD.batch_position IS NOT NULL
    THEN
        RAISE EXCEPTION 'sealed audit event cannot be modified';
    END IF;

    IF NEW.node_hash IS NULL
       OR NEW.batch_block_id IS NULL
       OR NEW.batch_position IS NULL
    THEN
        RAISE EXCEPTION 'audit event sealing metadata must be complete';
    END IF;

    RETURN NEW;
END;
$function$;

ALTER FUNCTION app_private.protect_audit_event()
OWNER TO agentledger_owner;

REVOKE ALL
ON FUNCTION app_private.protect_audit_event()
FROM PUBLIC;

CREATE TRIGGER audit_events_protect
BEFORE UPDATE OR DELETE
ON audit_events
FOR EACH ROW
EXECUTE FUNCTION app_private.protect_audit_event();


CREATE OR REPLACE FUNCTION app_private.protect_audit_merkle_block()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'audit Merkle blocks are immutable';
END;
$function$;

ALTER FUNCTION app_private.protect_audit_merkle_block()
OWNER TO agentledger_owner;

REVOKE ALL
ON FUNCTION app_private.protect_audit_merkle_block()
FROM PUBLIC;

CREATE TRIGGER audit_merkle_blocks_protect
BEFORE UPDATE OR DELETE
ON audit_merkle_blocks
FOR EACH ROW
EXECUTE FUNCTION app_private.protect_audit_merkle_block();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS audit_merkle_blocks_protect
ON audit_merkle_blocks;

DROP FUNCTION IF EXISTS
app_private.protect_audit_merkle_block();

DROP TRIGGER IF EXISTS audit_events_protect
ON audit_events;

DROP FUNCTION IF EXISTS
app_private.protect_audit_event();

DROP POLICY IF EXISTS
audit_chain_heads_worker_tenant
ON audit_chain_heads;

DROP POLICY IF EXISTS
audit_chain_heads_app_tenant
ON audit_chain_heads;

DROP POLICY IF EXISTS
audit_chain_heads_owner_all
ON audit_chain_heads;

DROP POLICY IF EXISTS
audit_merkle_blocks_worker_tenant
ON audit_merkle_blocks;

DROP POLICY IF EXISTS
audit_merkle_blocks_app_tenant
ON audit_merkle_blocks;

DROP POLICY IF EXISTS
audit_merkle_blocks_owner_all
ON audit_merkle_blocks;

DROP POLICY IF EXISTS
audit_events_worker_tenant
ON audit_events;

DROP POLICY IF EXISTS
audit_events_app_tenant
ON audit_events;

DROP POLICY IF EXISTS
audit_events_owner_all
ON audit_events;

ALTER TABLE audit_events DISABLE ROW LEVEL SECURITY;
ALTER TABLE audit_merkle_blocks DISABLE ROW LEVEL SECURITY;
ALTER TABLE audit_chain_heads DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0001_initial"),
        ("inventory", "0002_database_security"),
    ]

    operations = [
        migrations.RunSQL(
            sql=FORWARD_SQL,
            reverse_sql=REVERSE_SQL,
        ),
    ]
