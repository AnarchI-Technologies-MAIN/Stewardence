"""Narrow database transition authority; runtime workers cannot UPDATE jobs."""
from django.db import migrations

SQL=r"""
CREATE FUNCTION app_private.claim_job(w text, lease interval, token uuid)
RETURNS SETOF public.background_jobs LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
BEGIN
 IF length(w) NOT BETWEEN 1 AND 255 OR lease<=interval '0 seconds' OR lease>interval '10 minutes' OR token IS NULL THEN
  RAISE EXCEPTION 'Invalid claim parameters';
 END IF;
 RETURN QUERY WITH candidate AS (
  SELECT id FROM public.background_jobs WHERE status='queued' AND available_at<=clock_timestamp()
  AND (job_type<>'report_generation' OR app_private.core_work_allowed(organization_id))
  ORDER BY priority,available_at,id FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE public.background_jobs j SET status='running',locked_by=w,locked_at=clock_timestamp(),
  lock_expires_at=clock_timestamp()+lease,claim_token=token,attempts=j.attempts+1
  FROM candidate c WHERE j.id=c.id RETURNING j.*;
END;$fn$;

CREATE FUNCTION app_private.finish_job(jid uuid,w text,token uuid,action text,lease interval,
 code text,summary text,fingerprint text,retry boolean) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE j public.background_jobs%ROWTYPE;
BEGIN
 SELECT * INTO j FROM public.background_jobs WHERE id=jid;
 IF NOT FOUND THEN RETURN false; END IF;
 IF j.job_type='report_generation' AND current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Report persistence requires read committed control admission';
 END IF;
 -- All persistence/control transitions take this lock before any job row lock.
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||j.organization_id::text||':control',0));
 SELECT * INTO j FROM public.background_jobs WHERE id=jid FOR UPDATE;
 IF j.status<>'running' OR j.locked_by IS DISTINCT FROM w OR j.claim_token IS DISTINCT FROM token
  OR j.lock_expires_at IS NULL OR j.lock_expires_at<=clock_timestamp() THEN RETURN false; END IF;
 IF action IN ('complete','heartbeat') AND j.job_type='report_generation'
  AND NOT app_private.core_work_allowed(j.organization_id) THEN RETURN false; END IF;
 IF action='heartbeat' THEN
  IF lease<=interval '0 seconds' OR lease>interval '10 minutes' THEN RAISE EXCEPTION 'Invalid heartbeat lease'; END IF;
  UPDATE public.background_jobs SET lock_expires_at=clock_timestamp()+lease WHERE id=jid;
 ELSIF action='complete' THEN
  UPDATE public.background_jobs SET status='completed',completed_at=clock_timestamp(),available_at=clock_timestamp(),
   locked_at=NULL,lock_expires_at=NULL,locked_by=NULL,claim_token=NULL WHERE id=jid;
 ELSIF action='fail' THEN
  IF code IS NULL OR code='' OR summary IS NULL OR summary='' OR fingerprint IS NULL OR fingerprint='' THEN
   RAISE EXCEPTION 'Safe failure evidence required';
  END IF;
  retry:=coalesce(retry,false) AND j.job_type='report_generation';
  UPDATE public.background_jobs SET status=CASE WHEN retry AND attempts<5 THEN 'queued' ELSE 'failed' END,
   available_at=clock_timestamp()+CASE attempts WHEN 1 THEN interval '1 minute' WHEN 2 THEN interval '5 minutes'
    WHEN 3 THEN interval '30 minutes' WHEN 4 THEN interval '2 hours' ELSE interval '0 seconds' END,
   completed_at=CASE WHEN retry AND attempts<5 THEN NULL ELSE clock_timestamp() END,
   locked_at=NULL,lock_expires_at=NULL,locked_by=NULL,claim_token=NULL,
   error_code=CASE WHEN retry AND attempts>=5 THEN 'retry_limit_reached' ELSE code END,
   safe_error_summary=CASE WHEN retry AND attempts>=5 THEN 'Retry limit reached; review required.' ELSE summary END,
   error_fingerprint=fingerprint WHERE id=jid;
 ELSE RAISE EXCEPTION 'Unsupported job transition'; END IF;
 RETURN true;
END;$fn$;

CREATE FUNCTION app_private.lock_job_persistence(jid uuid,w text,token uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $fn$
DECLARE j public.background_jobs%ROWTYPE;
BEGIN
 SELECT * INTO j FROM public.background_jobs WHERE id=jid;
 IF NOT FOUND THEN RETURN false; END IF;
 IF j.job_type='report_generation' AND current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Report persistence requires read committed control admission';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended('core:'||j.organization_id::text||':control',0));
 SELECT * INTO j FROM public.background_jobs WHERE id=jid FOR UPDATE;
 RETURN j.status='running' AND j.locked_by=w AND j.claim_token=token AND j.lock_expires_at>clock_timestamp()
  AND (j.job_type<>'report_generation' OR app_private.core_work_allowed(j.organization_id));
END;$fn$;

CREATE FUNCTION app_private.recover_jobs() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,public AS $fn$
DECLARE candidate record; j public.background_jobs%ROWTYPE; recovered integer:=0;
BEGIN
 FOR candidate IN SELECT id,organization_id FROM public.background_jobs
  WHERE status='running' AND lock_expires_at<clock_timestamp() ORDER BY lock_expires_at,id LIMIT 100 LOOP
  PERFORM pg_advisory_xact_lock(hashtextextended('core:'||candidate.organization_id::text||':control',0));
  SELECT * INTO j FROM public.background_jobs WHERE id=candidate.id FOR UPDATE SKIP LOCKED;
  IF FOUND AND j.status='running' AND j.lock_expires_at<clock_timestamp() THEN
   UPDATE public.background_jobs SET status=CASE WHEN attempts<5 AND job_type='report_generation' THEN 'queued' ELSE 'failed' END,
    available_at=clock_timestamp(),completed_at=CASE WHEN attempts<5 AND job_type='report_generation' THEN NULL ELSE clock_timestamp() END,
    locked_at=NULL,lock_expires_at=NULL,locked_by=NULL,claim_token=NULL,error_code='lease_expired',
    safe_error_summary='The worker lease expired before completion.',error_fingerprint='worker_lease_expired' WHERE id=j.id;
   recovered:=recovered+1;
  END IF;
 END LOOP;
 RETURN recovered;
END;$fn$;
DO $fn$ DECLARE f regprocedure; BEGIN
 FOREACH f IN ARRAY ARRAY['app_private.claim_job(text,interval,uuid)'::regprocedure,
  'app_private.finish_job(uuid,text,uuid,text,interval,text,text,text,boolean)'::regprocedure,
  'app_private.lock_job_persistence(uuid,text,uuid)'::regprocedure,'app_private.recover_jobs()'::regprocedure] LOOP
  EXECUTE format('ALTER FUNCTION %s OWNER TO agentledger_owner',f);
  EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC',f);
  EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO agentledger_worker',f);
 END LOOP;
END;$fn$;
REVOKE UPDATE ON public.background_jobs FROM agentledger_worker;
"""

class Migration(migrations.Migration):
    dependencies=[('jobs','0007_core_workflow_security')]
    operations=[migrations.RunSQL(SQL)]
