"""Qualification-only same-connection workflow admission observations.

The extra query changes timing. Its results are observations immediately before
issuance, not a replacement for issuer checks or proof of the historical cause.
"""
import json
from datetime import UTC, datetime
from pathlib import Path

from django.db import transaction


class WorkflowIdentityDiagnostics:
    def __init__(self, test_id):
        self.test_id = test_id

    def __call__(self, execute, sql, params, many, context):
        if 'SELECT app_private.issue_workflow_run(' not in sql:
            return execute(sql, params, many, context)
        facts = {'test_id': self.test_id,
                 'application_wall_clock': datetime.now(UTC).isoformat(),
                 'connection_alias': context['connection'].alias}
        try:
            with transaction.atomic(using=context['connection'].alias):
                with context['connection'].cursor() as cursor:
                    cursor.execute("""
                    WITH v AS (SELECT %s::jsonb p, %s::text canonical,
                      %s::text digest, %s::uuid org, %s::uuid actor,
                      %s::text op, %s::timestamptz effective),
                    r AS (SELECT *, p->'request' req FROM v)
                    SELECT jsonb_build_object(
                      'database_clock',clock_timestamp(),
                      'effective_at',effective,
                      'request_effective_at',req->>'effective_at',
                      'time_equal',(req->>'effective_at')::timestamptz IS NOT DISTINCT FROM effective,
                      'not_future',effective<=clock_timestamp(),
                      'utc_suffix',req->>'effective_at' ~ '[+]00:00$',
                      'request_object',jsonb_typeof(req)='object',
                      'request_fields',(SELECT count(*) FROM jsonb_object_keys(req)),
                      'request_schema',req->>'schema'='stewardence.workflow.v1',
                      'organization_equal',req->>'organization_id'=org::text,
                      'profile_equal',req->>'branch_profile'=(SELECT profile FROM organization_workflow_profiles WHERE organization_id=org),
                      'operation_equal',req->>'operation'=op,
                      'receipt_array',jsonb_typeof(req->'receipt_ids')='array',
                      'result_schema',p->>'schema'='stewardence.workflow_receipt.v1',
                      'proposal_authority',p->>'authority'='proposal_only',
                      'payload_canonical',canonical IS NOT DISTINCT FROM app_private.queue_canonical(p),
                      'payload_digest',digest IS NOT DISTINCT FROM encode(sha256(convert_to(app_private.queue_canonical(p),'UTF8')),'hex'),
                      'tenant_equal',org IS NOT DISTINCT FROM app_private.current_organization_id(),
                      'actor_equal',actor IS NOT DISTINCT FROM app_private.current_user_id(),
                      'owner_entitled',app_private.core_owner_entitled(org,actor),
                      'work_allowed_observer_permission',has_function_privilege(session_user,'app_private.core_work_allowed(uuid)','EXECUTE'),
                      'session_role',session_user,
                      'isolation',current_setting('transaction_isolation')) FROM r
                    """, [params[6], params[7], params[8], params[1],
                          params[2], params[3], params[5]])
                    observed = cursor.fetchone()[0]
                    if isinstance(observed, str):
                        observed = json.loads(observed)
                    facts.update(observed)
        except Exception as diagnostic_error:
            # Keep the original operation/assertion authoritative. No payload
            # or exception text is emitted because it can retain private input.
            facts['diagnostic_error_type'] = type(diagnostic_error).__name__
        try:
            result = execute(sql, params, many, context)
            facts['issuer_outcome'] = 'accepted'
            return result
        except Exception as issuer_error:
            facts['issuer_outcome'] = 'rejected'
            facts['issuer_error_type'] = type(issuer_error).__name__
            print('WORKFLOW_IDENTITY_DIAGNOSTIC ' + json.dumps(facts, sort_keys=True))
            raise
        finally:
            evidence = Path('/qualification-evidence')
            if evidence.is_dir():
                try:
                    with (evidence / 'workflow-identity-diagnostics.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(facts, sort_keys=True) + '\n')
                except OSError as receipt_error:
                    print('WORKFLOW_DIAGNOSTIC_RECEIPT_ERROR ' + type(receipt_error).__name__)
