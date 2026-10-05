from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE background_jobs OWNER TO agentledger_owner;

REVOKE ALL ON background_jobs FROM PUBLIC;

GRANT SELECT, INSERT
    ON background_jobs TO agentledger_app;

GRANT SELECT, INSERT, UPDATE
    ON background_jobs TO agentledger_worker;

ALTER TABLE background_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE background_jobs FORCE ROW LEVEL SECURITY;

CREATE POLICY background_jobs_owner_all
ON background_jobs
FOR ALL TO agentledger_owner
USING (true) WITH CHECK (true);

CREATE POLICY background_jobs_app_tenant
ON background_jobs
FOR ALL TO agentledger_app
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());

CREATE POLICY background_jobs_worker_queue
ON background_jobs
FOR ALL TO agentledger_worker
USING (true)
WITH CHECK (true);

CREATE OR REPLACE FUNCTION app_private.notify_background_job()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.status = 'queued'
       AND NEW.available_at <= clock_timestamp()
       AND (
            TG_OP = 'INSERT'
            OR OLD.status IS DISTINCT FROM NEW.status
            OR OLD.available_at IS DISTINCT FROM NEW.available_at
       )
    THEN
        PERFORM pg_notify(
            'agentledger_job_channel',
            NEW.organization_id::text
        );
    END IF;

    RETURN NEW;
END;
$function$;

ALTER FUNCTION app_private.notify_background_job()
    OWNER TO agentledger_owner;

REVOKE ALL ON FUNCTION app_private.notify_background_job()
    FROM PUBLIC;

CREATE TRIGGER background_jobs_notify
AFTER INSERT OR UPDATE OF status, available_at
ON background_jobs
FOR EACH ROW
EXECUTE FUNCTION app_private.notify_background_job();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS background_jobs_notify ON background_jobs;
DROP FUNCTION IF EXISTS app_private.notify_background_job();

DROP POLICY IF EXISTS background_jobs_worker_queue
    ON background_jobs;

DROP POLICY IF EXISTS background_jobs_app_tenant
    ON background_jobs;

DROP POLICY IF EXISTS background_jobs_owner_all
    ON background_jobs;

ALTER TABLE background_jobs DISABLE ROW LEVEL SECURITY;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0001_initial"),
        ("inventory", "0002_database_security"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
