import uuid
from django.db import migrations, models
import django.db.models.deletion

SQL = """
ALTER TABLE job_recovery_receipts OWNER TO agentledger_owner;
REVOKE ALL ON job_recovery_receipts FROM PUBLIC;
GRANT SELECT, INSERT ON job_recovery_receipts TO agentledger_app, agentledger_worker;
ALTER TABLE job_recovery_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_recovery_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY recovery_owner ON job_recovery_receipts FOR ALL TO agentledger_owner USING (true) WITH CHECK (true);
CREATE POLICY recovery_tenant ON job_recovery_receipts FOR ALL TO agentledger_app, agentledger_worker
USING (organization_id = app_private.current_organization_id())
WITH CHECK (organization_id = app_private.current_organization_id());
CREATE FUNCTION app_private.protect_recovery_receipt() RETURNS trigger LANGUAGE plpgsql AS $body$
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Recovery receipts are append-only'; END IF;
 IF NOT EXISTS (SELECT 1 FROM background_jobs WHERE id = NEW.job_id AND organization_id = NEW.organization_id AND attempts = NEW.attempt
   AND ((NEW.outcome = 'completed' AND status = 'completed') OR (NEW.outcome = 'retry' AND status = 'queued') OR (NEW.outcome = 'review' AND status = 'failed'))) THEN
  RAISE EXCEPTION 'Recovery receipt job binding is invalid';
 END IF;
 RETURN NEW;
END;
$body$;
ALTER FUNCTION app_private.protect_recovery_receipt() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_recovery_receipt() FROM PUBLIC;
CREATE TRIGGER recovery_receipt_immutable BEFORE INSERT OR UPDATE OR DELETE ON job_recovery_receipts
FOR EACH ROW EXECUTE FUNCTION app_private.protect_recovery_receipt();
"""


class Migration(migrations.Migration):
    dependencies = [("jobs", "0002_job_security")]
    operations = [
        migrations.CreateModel(name="RecoveryReceipt", fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("attempt", models.PositiveSmallIntegerField()),
            ("outcome", models.CharField(max_length=16, choices=[("completed", "Completed"), ("retry", "Retry admitted"), ("review", "Review required")])),
            ("payload", models.JSONField()), ("sha256", models.CharField(max_length=64)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("organization", models.ForeignKey(to="organizations.organization", on_delete=django.db.models.deletion.PROTECT)),
            ("job", models.ForeignKey(to="jobs.backgroundjob", on_delete=django.db.models.deletion.PROTECT)),
        ], options={"db_table":"job_recovery_receipts", "constraints":[models.UniqueConstraint(fields=("job", "attempt", "outcome"), name="recovery_receipt_attempt_unique")]}),
        migrations.RunSQL(SQL, "DROP FUNCTION app_private.protect_recovery_receipt() CASCADE;"),
    ]
