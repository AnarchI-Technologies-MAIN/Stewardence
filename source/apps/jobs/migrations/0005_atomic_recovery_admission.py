"""Database-issued transition receipts, with no worker INSERT authority.

Receipt canonicalization is deliberately restricted to the nine fixed fields:
an integer and ASCII identifiers/enums/digests. Arbitrary job JSON remains
RFC8785-canonicalized by the application at admission, never jsonb::text.
"""
import hashlib
import rfc8785
from django.db import migrations, models


def bind_existing_inputs(apps, schema_editor):
    Job = apps.get_model('jobs', 'BackgroundJob')
    for job in Job.objects.using(schema_editor.connection.alias).all().iterator():
        Job.objects.using(schema_editor.connection.alias).filter(pk=job.pk).update(
            input_sha256=hashlib.sha256(rfc8785.dumps(job.payload)).hexdigest())


SQL = r"""
CREATE FUNCTION app_private.recovery_canonical(p jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT SET search_path = pg_catalog, public AS $fn$
 SELECT '{"attempt":' || (p->>'attempt') ||
 ',"failure_fingerprint":' || to_json(p->>'failure_fingerprint')::text ||
 ',"input_sha256":' || to_json(p->>'input_sha256')::text ||
 ',"job_id":' || to_json(p->>'job_id')::text ||
 ',"operation":' || to_json(p->>'operation')::text ||
 ',"organization_id":' || to_json(p->>'organization_id')::text ||
 ',"outcome":' || to_json(p->>'outcome')::text ||
 ',"reason_code":' || to_json(p->>'reason_code')::text ||
 ',"schema":' || to_json(p->>'schema')::text || '}'
$fn$;
ALTER FUNCTION app_private.recovery_canonical(jsonb) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.recovery_canonical(jsonb) FROM PUBLIC;

CREATE FUNCTION app_private.protect_job_inputs() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
BEGIN
 IF TG_OP = 'INSERT' AND (NEW.status <> 'queued' OR NEW.attempts <> 0) THEN
  RAISE EXCEPTION 'New jobs require an unclaimed queued state';
 END IF;
 IF TG_OP = 'UPDATE' THEN
  IF OLD.status='running' AND NEW.status IN ('queued','completed','failed') AND NOT (
    OLD.lock_expires_at > clock_timestamp() OR
    (NEW.error_code='lease_expired' AND OLD.lock_expires_at < clock_timestamp() AND NEW.status IN ('queued','failed'))) THEN
   RAISE EXCEPTION 'Expired claims require lease recovery';
  END IF;
  IF NEW.status='queued' AND NEW.attempts >= 5 THEN RAISE EXCEPTION 'Retry limit exhausted'; END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (
    (OLD.status='queued' AND NEW.status='running' AND NEW.attempts=OLD.attempts+1)
    OR (OLD.status='running' AND NEW.status IN ('queued','completed','failed') AND NEW.attempts=OLD.attempts)) THEN
   RAISE EXCEPTION 'Unsupported job state transition';
  END IF;
  IF NEW.status=OLD.status AND NEW.attempts IS DISTINCT FROM OLD.attempts THEN
   RAISE EXCEPTION 'Attempt identity changes only on claim';
  END IF;
  IF OLD.status='running' AND NEW.status='running' AND
    (NEW.claim_token IS DISTINCT FROM OLD.claim_token OR NEW.locked_by IS DISTINCT FROM OLD.locked_by OR NEW.locked_at IS DISTINCT FROM OLD.locked_at) THEN
   RAISE EXCEPTION 'Running claim identity is immutable';
  END IF;
 END IF;
 IF TG_OP = 'UPDATE' AND (NEW.id IS DISTINCT FROM OLD.id OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
   OR NEW.job_type IS DISTINCT FROM OLD.job_type OR NEW.payload IS DISTINCT FROM OLD.payload
   OR NEW.input_sha256 IS DISTINCT FROM OLD.input_sha256 OR NEW.created_at IS DISTINCT FROM OLD.created_at) THEN
  RAISE EXCEPTION 'Job identities and admitted inputs are immutable';
 END IF;
 IF NEW.input_sha256 IS NULL OR NEW.input_sha256 !~ '^[0-9a-f]{64}$'
   OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
   OR NEW.job_type NOT IN ('report_generation','risk_reassessment','catalog_refresh','audit_batch_seal') THEN
  RAISE EXCEPTION 'Invalid admitted job inputs';
 END IF;
 RETURN NEW;
END;
$fn$;
ALTER FUNCTION app_private.protect_job_inputs() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.protect_job_inputs() FROM PUBLIC;
CREATE TRIGGER job_input_immutable BEFORE INSERT OR UPDATE ON public.background_jobs
FOR EACH ROW EXECUTE FUNCTION app_private.protect_job_inputs();

CREATE OR REPLACE FUNCTION app_private.protect_recovery_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public AS $fn$
DECLARE j public.background_jobs%ROWTYPE;
BEGIN
 IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'Recovery receipts are append-only'; END IF;
 SELECT * INTO j FROM public.background_jobs WHERE id=NEW.job_id;
 IF NOT FOUND OR j.organization_id IS DISTINCT FROM NEW.organization_id OR j.attempts IS DISTINCT FROM NEW.attempt
   OR NEW.attempt < 1 OR NOT ((NEW.outcome='completed' AND j.status='completed')
   OR (NEW.outcome='retry' AND j.status='queued') OR (NEW.outcome='review' AND j.status='failed')) THEN
  RAISE EXCEPTION 'Recovery receipt job binding is invalid';
 END IF;
 IF jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object' THEN
  RAISE EXCEPTION 'Recovery receipt requires an object';
 END IF;
 IF (SELECT count(*) FROM jsonb_object_keys(NEW.payload)) <> 9
   OR NOT NEW.payload ?& ARRAY['schema','job_id','organization_id','operation','attempt','outcome','input_sha256','reason_code','failure_fingerprint']
   OR jsonb_typeof(NEW.payload->'attempt') IS DISTINCT FROM 'number'
   OR NEW.payload->>'attempt' IS DISTINCT FROM NEW.attempt::text
   OR NEW.payload->>'schema' IS DISTINCT FROM 'stewardence.recovery.v1'
   OR NEW.payload->>'job_id' IS DISTINCT FROM NEW.job_id::text
   OR NEW.payload->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
   OR NEW.payload->>'operation' IS DISTINCT FROM j.job_type
   OR NEW.payload->>'outcome' IS DISTINCT FROM NEW.outcome
   OR NEW.payload->>'input_sha256' IS DISTINCT FROM j.input_sha256
   OR EXISTS (SELECT 1 FROM jsonb_each(NEW.payload) WHERE key <> 'attempt' AND jsonb_typeof(value) <> 'string') THEN
  RAISE EXCEPTION 'Recovery receipt schema binding is invalid';
 END IF;
 IF NEW.outcome='completed' THEN
  IF NEW.payload->>'reason_code' IS DISTINCT FROM '' OR NEW.payload->>'failure_fingerprint' IS DISTINCT FROM '' THEN
   RAISE EXCEPTION 'Invalid completion receipt';
  END IF;
 ELSE
  IF NEW.payload->>'reason_code' NOT IN ('job_execution_failed','job_requires_review','retry_limit_reached','lease_expired')
    OR NEW.payload->>'failure_fingerprint' !~ '^[0-9a-f]{64}$'
    OR (NEW.outcome='retry' AND NEW.payload->>'reason_code' NOT IN ('job_execution_failed','lease_expired'))
    OR (NEW.outcome='review' AND NEW.payload->>'reason_code' = 'job_execution_failed') THEN
   RAISE EXCEPTION 'Invalid failure receipt';
  END IF;
 END IF;
 IF NEW.sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.recovery_canonical(NEW.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Recovery receipt canonical digest is invalid';
 END IF;
 RETURN NEW;
END;
$fn$;

CREATE FUNCTION app_private.issue_job_transition_receipt() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$
DECLARE p jsonb; result text; reason text; fingerprint text;
BEGIN
 IF OLD.status <> 'running' OR NEW.status NOT IN ('completed','queued','failed') THEN RETURN NEW; END IF;
 result := CASE NEW.status WHEN 'completed' THEN 'completed' WHEN 'queued' THEN 'retry' ELSE 'review' END;
 reason := CASE WHEN NEW.status='completed' THEN '' WHEN NEW.error_code='lease_expired' THEN 'lease_expired'
   WHEN NEW.error_code='retry_limit_reached' THEN 'retry_limit_reached'
   WHEN NEW.status='queued' THEN 'job_execution_failed' ELSE 'job_requires_review' END;
 fingerprint := CASE WHEN NEW.status='completed' THEN ''
   WHEN NEW.error_fingerprint ~ '^[0-9a-f]{64}$' THEN NEW.error_fingerprint
   ELSE encode(sha256(convert_to(COALESCE(NEW.error_fingerprint,'unclassified'),'UTF8')),'hex') END;
 p := jsonb_build_object('schema','stewardence.recovery.v1','job_id',NEW.id::text,
   'organization_id',NEW.organization_id::text,'operation',NEW.job_type,'attempt',NEW.attempts,
   'outcome',result,'input_sha256',NEW.input_sha256,'reason_code',reason,'failure_fingerprint',fingerprint);
 INSERT INTO public.job_recovery_receipts(id,organization_id,job_id,attempt,outcome,payload,sha256,created_at)
 VALUES(gen_random_uuid(),NEW.organization_id,NEW.id,NEW.attempts,result,p,
   encode(sha256(convert_to(app_private.recovery_canonical(p),'UTF8')),'hex'),clock_timestamp());
 RETURN NEW;
END;
$fn$;
ALTER FUNCTION app_private.issue_job_transition_receipt() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.issue_job_transition_receipt() FROM PUBLIC;
CREATE TRIGGER job_transition_receipt AFTER UPDATE OF status ON public.background_jobs
FOR EACH ROW EXECUTE FUNCTION app_private.issue_job_transition_receipt();
REVOKE INSERT ON public.job_recovery_receipts FROM agentledger_worker;
"""


class Migration(migrations.Migration):
    dependencies = [('jobs','0004_receipt_admission')]
    operations = [
        migrations.AddField(model_name='backgroundjob',name='input_sha256',field=models.CharField(max_length=64,null=True,editable=False)),
        migrations.RunPython(bind_existing_inputs, migrations.RunPython.noop),
        migrations.AlterField(model_name='backgroundjob',name='input_sha256',field=models.CharField(max_length=64,editable=False)),
        migrations.RunSQL(SQL),
    ]
