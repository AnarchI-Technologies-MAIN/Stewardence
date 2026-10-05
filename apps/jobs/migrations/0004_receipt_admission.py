from django.db import migrations

SQL = """
REVOKE INSERT ON job_recovery_receipts FROM agentledger_app;
CREATE OR REPLACE FUNCTION app_private.protect_recovery_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $body$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Recovery receipts are append-only'; END IF;
 IF NOT EXISTS (SELECT 1 FROM public.background_jobs WHERE id = NEW.job_id AND organization_id = NEW.organization_id AND attempts = NEW.attempt
   AND ((NEW.outcome = 'completed' AND status = 'completed') OR (NEW.outcome = 'retry' AND status = 'queued') OR (NEW.outcome = 'review' AND status = 'failed'))) THEN
  RAISE EXCEPTION 'Recovery receipt job binding is invalid';
 END IF;
 IF jsonb_typeof(NEW.payload) <> 'object' OR NEW.sha256 !~ '^[0-9a-f]{64}$'
    OR NEW.payload->>'schema' IS DISTINCT FROM 'stewardence.recovery.v1'
    OR NEW.payload->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
    OR NEW.payload->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR NEW.payload->>'attempt' IS DISTINCT FROM NEW.attempt::text
    OR NEW.payload->>'outcome' IS DISTINCT FROM NEW.outcome
    OR NEW.payload->>'operation' IS DISTINCT FROM (SELECT job_type FROM public.background_jobs WHERE id = NEW.job_id)
    OR COALESCE(NEW.payload->>'input_sha256', '') !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'Recovery receipt schema binding is invalid';
 END IF;
 RETURN NEW;
END;
$body$;
"""


class Migration(migrations.Migration):
    dependencies = [("jobs", "0003_recovery_receipts")]
    # Reverse is intentionally fail-closed; lowering this guard needs a reviewed migration.
    operations = [migrations.RunSQL(SQL)]
