"""Synthetic-fixture-only SQL0012 identity predicate observations.

Never imported by application code. Records contain no provider credentials.
"""

import hashlib
import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime

SQL = """
WITH supplied AS (
 SELECT %s::uuid org,%s::uuid actor,%s::text op,%s::timestamptz effective,
        %s::jsonb p,clock_timestamp() observed_clock,
        statement_timestamp() observed_statement,current_timestamp observed_transaction
), evaluated AS (
 SELECT supplied.*,p->'request' req,
  (SELECT w.profile FROM public.organization_workflow_profiles w
   WHERE w.organization_id=org) profile
 FROM supplied
)
SELECT jsonb_build_object(
 'predicates',jsonb_build_object(
  'request_type_not_object',jsonb_typeof(req) IS DISTINCT FROM 'object',
  'request_key_count_not_six',(SELECT count(*) FROM jsonb_object_keys(req))<>6,
  'request_schema_mismatch',req->>'schema' IS DISTINCT FROM 'stewardence.workflow.v1',
  'organization_mismatch',req->>'organization_id' IS DISTINCT FROM org::text,
  'profile_mismatch',req->>'branch_profile' IS DISTINCT FROM profile,
  'operation_mismatch',req->>'operation' IS DISTINCT FROM op,
  'effective_roundtrip_mismatch',
   (req->>'effective_at')::timestamptz IS DISTINCT FROM effective,
  'effective_future',effective>observed_clock,
  'effective_not_explicit_utc',req->>'effective_at' !~ '[+]00:00$',
  'receipt_ids_not_array',jsonb_typeof(req->'receipt_ids') IS DISTINCT FROM 'array',
  'result_schema_mismatch',
   p->>'schema' IS DISTINCT FROM 'stewardence.workflow_receipt.v1',
  'result_authority_mismatch',p->>'authority' IS DISTINCT FROM 'proposal_only'),
 'request',req,'payload_schema',p->>'schema','payload_authority',p->>'authority',
 'bound_org',org,'bound_actor',actor,'bound_operation',op,'profile',profile,
 'bound_effective_pg',effective::text,
 'request_effective_pg',(req->>'effective_at')::timestamptz::text,
 'roundtrip_difference_microseconds',
  (extract(epoch FROM ((req->>'effective_at')::timestamptz-effective))*1000000)::text,
 'clock_timestamp',observed_clock::text,'statement_timestamp',observed_statement::text,
 'transaction_timestamp',observed_transaction::text,
 'wall_regression_us',
  (extract(epoch FROM (observed_clock-observed_transaction))*1000000)::bigint,
 'effective_minus_clock_microseconds',
  (extract(epoch FROM (effective-observed_clock))*1000000)::text,
 'session_user',session_user,'current_user',current_user,
 'isolation',current_setting('transaction_isolation'),'database_timezone',current_setting('TimeZone'),
 'organization_context',app_private.current_organization_id(),
 'actor_context',app_private.current_user_id())
FROM evaluated
"""


def observer(records):
    def observe(execute, sql, params, many, context):
        if "app_private.issue_workflow_run(" in sql:
            before_probe = {
                "python_wall_before_probe": datetime.now(UTC).isoformat(),
                "python_monotonic_before_probe_ns": time.monotonic_ns(),
                "python_monotonic_raw_before_probe_ns": time.clock_gettime_ns(
                    time.CLOCK_MONOTONIC_RAW
                ),
            }
            execute(
                SQL,
                [params[1], params[2], params[3], params[5], params[6]],
                False,
                context,
            )
            record = context["cursor"].fetchone()[0]
            if isinstance(record, str):
                record = json.loads(record)
            record.update(before_probe)
            record["python_wall_after_probe"] = datetime.now(UTC).isoformat()
            record["python_monotonic_after_probe_ns"] = time.monotonic_ns()
            record["python_monotonic_raw_after_probe_ns"] = time.clock_gettime_ns(
                time.CLOCK_MONOTONIC_RAW
            )
            record["python_bound_effective"] = params[5].isoformat()
            records.append(record)
        issue_started = time.monotonic_ns()
        issue_raw_started = time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
        issue_wall_before = datetime.now(UTC).isoformat()
        try:
            result = execute(sql, params, many, context)
            if "app_private.issue_workflow_run(" in sql and records:
                records[-1]["issuer_outcome"] = "accepted"
                records[-1]["python_wall_before_issuer"] = issue_wall_before
                records[-1]["python_monotonic_before_issuer_ns"] = issue_started
                records[-1]["python_monotonic_raw_before_issuer_ns"] = issue_raw_started
                records[-1]["python_wall_after_issuer"] = datetime.now(UTC).isoformat()
                records[-1]["python_monotonic_after_issuer_ns"] = time.monotonic_ns()
                records[-1]["python_monotonic_raw_after_issuer_ns"] = (
                    time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                )
                records[-1]["issuer_elapsed_monotonic_ns"] = (
                    time.monotonic_ns() - issue_started
                )
                records[-1]["monotonic_elapsed_ns"] = records[-1][
                    "issuer_elapsed_monotonic_ns"
                ]
            return result
        except Exception as error:
            if "app_private.issue_workflow_run(" in sql and records:
                records[-1]["issuer_outcome"] = "rejected"
                records[-1]["python_wall_before_issuer"] = issue_wall_before
                records[-1]["python_monotonic_before_issuer_ns"] = issue_started
                records[-1]["python_monotonic_raw_before_issuer_ns"] = issue_raw_started
                records[-1]["python_wall_after_issuer"] = datetime.now(UTC).isoformat()
                records[-1]["python_monotonic_after_issuer_ns"] = time.monotonic_ns()
                records[-1]["python_monotonic_raw_after_issuer_ns"] = (
                    time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW)
                )
                records[-1]["issuer_elapsed_monotonic_ns"] = (
                    time.monotonic_ns() - issue_started
                )
                records[-1]["monotonic_elapsed_ns"] = records[-1][
                    "issuer_elapsed_monotonic_ns"
                ]
                records[-1]["issuer_exception"] = str(error)
                print(
                    "SYNTHETIC_IDENTITY_FAILURE "
                    + json.dumps(records[-1], sort_keys=True)
                )
            raise

    return observe


@contextmanager
def instrumented_issuer(connection):
    """Disposable debug issuer: same guards, ACLs, owner and isolation.

    Capture the identity clock immediately before its IF, preventing the probe
    from masking a future-time veto. Always restore the original definition.
    """
    signature = (
        "app_private.issue_workflow_run(uuid,uuid,uuid,text,text,"
        "timestamptz,jsonb,text,text,uuid)"
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_functiondef(%s::regprocedure),proacl::text,"
            "proowner,prosecdef FROM pg_proc WHERE oid=%s::regprocedure",
            [signature, signature],
        )
        original, acl, owner, security = cursor.fetchone()
    declaration = "DECLARE req jsonb;"
    anchor = "IF jsonb_typeof(req) IS DISTINCT FROM 'object'"
    exception = "RAISE EXCEPTION 'Workflow request identity invalid';"
    assert (
        original.count(declaration)
        == original.count(anchor)
        == original.count(exception)
        == 1
    )
    assert original.count("effective>clock_timestamp()") == 1
    projection = (
        "SELECT jsonb_build_object("
        + SQL.split("SELECT jsonb_build_object(", 1)[1].rsplit("FROM evaluated", 1)[0]
    )
    capture = (
        "identity_clock:=clock_timestamp();\n"
        + projection
        + " INTO identity_probe FROM (SELECT identity_clock observed_clock,"
        "statement_timestamp() observed_statement,"
        "current_timestamp observed_transaction) diagnostic_clock;\n"
    )
    altered = original.replace(
        declaration, declaration + " identity_clock timestamptz; identity_probe jsonb;"
    )
    altered = altered.replace(anchor, capture + anchor)
    altered = altered.replace("effective>clock_timestamp()", "effective>identity_clock")
    altered = altered.replace(
        exception,
        "RAISE EXCEPTION 'Workflow request identity invalid INSTRUMENTED %',"
        "identity_probe;",
    )
    with connection.cursor() as cursor:
        cursor.execute(altered)
        cursor.execute(
            "SELECT proacl::text,proowner,prosecdef FROM pg_proc "
            "WHERE oid=%s::regprocedure",
            [signature],
        )
        assert cursor.fetchone() == (acl, owner, security)
    try:
        yield {
            "mode": "fixture_instrumented",
            "canonical_definition_sha256": hashlib.sha256(
                original.encode()
            ).hexdigest(),
            "instrumented_definition_sha256": hashlib.sha256(
                altered.encode()
            ).hexdigest(),
        }
    finally:
        with connection.cursor() as cursor:
            cursor.execute(original)
            cursor.execute(
                "SELECT pg_get_functiondef(%s::regprocedure),proacl::text,"
                "proowner,prosecdef FROM pg_proc WHERE oid=%s::regprocedure",
                [signature, signature],
            )
            assert cursor.fetchone() == (original, acl, owner, security)
