"""RFC8785 equality on a closed queue domain, not arbitrary JSON numbers.

New queue inputs accept ASCII object keys, Unicode strings, booleans, null,
safe integers and bounded arrays/objects. Financial decimals belong in admitted
artifact/snapshot evidence, never queue control envelopes. Existing inputs stay
immutable and retain their original application-bound digest.
"""
from django.db import migrations

SQL=r"""
CREATE FUNCTION app_private.queue_canonical(p jsonb,depth integer DEFAULT 0) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path=pg_catalog,public AS $fn$
DECLARE kind text; output text; n numeric;
BEGIN
 IF depth>12 OR octet_length(p::text)>1048576 THEN RAISE EXCEPTION 'Queue input exceeds admission bounds'; END IF;
 kind:=jsonb_typeof(p);
 IF kind='null' OR kind='boolean' THEN RETURN p::text;
 ELSIF kind='string' THEN RETURN to_json(p#>>'{}')::text;
 ELSIF kind='number' THEN
  n:=p::text::numeric;
  IF n<>trunc(n) OR abs(n)>9007199254740991 THEN RAISE EXCEPTION 'Queue numbers require safe integers'; END IF;
  RETURN n::bigint::text;
 ELSIF kind='array' THEN
  IF jsonb_array_length(p)>1000 THEN RAISE EXCEPTION 'Queue array exceeds admission bounds'; END IF;
  SELECT '['||coalesce(string_agg(app_private.queue_canonical(value,depth+1),',' ORDER BY ordinal),'')||']'
   INTO output FROM jsonb_array_elements(p) WITH ORDINALITY e(value,ordinal);
  RETURN output;
 ELSIF kind='object' THEN
  IF (SELECT count(*) FROM jsonb_object_keys(p))>1000 OR EXISTS(SELECT 1 FROM jsonb_object_keys(p) k WHERE k !~ '^[ -~]*$') THEN
   RAISE EXCEPTION 'Queue object keys require bounded ASCII identifiers';
  END IF;
  SELECT '{'||coalesce(string_agg(to_json(key)::text||':'||app_private.queue_canonical(value,depth+1),',' ORDER BY key COLLATE "C"),'')||'}'
   INTO output FROM jsonb_each(p);
  RETURN output;
 END IF;
 RAISE EXCEPTION 'Unsupported queue input kind';
END;$fn$;
ALTER FUNCTION app_private.queue_canonical(jsonb,integer) OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.queue_canonical(jsonb,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_private.queue_canonical(jsonb,integer) TO agentledger_app,agentledger_worker;

CREATE FUNCTION app_private.admit_job_digest() RETURNS trigger LANGUAGE plpgsql
SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF NEW.input_sha256 IS DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(NEW.payload),'UTF8')),'hex') THEN
  RAISE EXCEPTION 'Queue input digest does not match admitted payload';
 END IF;
 RETURN NEW;
END;$fn$;
ALTER FUNCTION app_private.admit_job_digest() OWNER TO agentledger_owner;
REVOKE ALL ON FUNCTION app_private.admit_job_digest() FROM PUBLIC;
CREATE TRIGGER job_digest_admission BEFORE INSERT ON public.background_jobs
 FOR EACH ROW EXECUTE FUNCTION app_private.admit_job_digest();
"""

class Migration(migrations.Migration):
    dependencies=[('jobs','0009_core_issuance_authority')]
    operations=[migrations.RunSQL(SQL)]
