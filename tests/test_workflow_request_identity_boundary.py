"""Workflow identity boundary probes; no relaxed database admission."""
from datetime import UTC, datetime, timedelta, timezone as datetime_timezone
import json
from uuid import uuid4

import pytest
from django.db import connections, DatabaseError
from django.utils import timezone

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.jobs.contracts import BranchProfile, Operation, WorkflowRequest
from apps.jobs.core_models import WorkflowRun
from apps.jobs.core_workflows import dispatch
from tests.test_core_authority_successor import configured, issue


def test_equal_instants_have_identical_request_bytes_and_hash():
    organization, receipt = uuid4(), uuid4()
    utc = datetime(2026, 10, 4, 3, 49, 0, 582133, tzinfo=UTC)
    offset = utc.astimezone(datetime_timezone(timedelta(hours=-5)))
    requests = [WorkflowRequest(organization, Operation.REASSESS, (receipt,),
                                stamp, BranchProfile.BUSINESS)
                for stamp in (utc, offset)]
    assert requests[0].envelope() == requests[1].envelope()
    assert requests[0].input_sha256 == requests[1].input_sha256
    assert requests[0].envelope()['effective_at'] == '2026-10-04T03:49:00.582133+00:00'


@pytest.mark.django_db(transaction=True, databases='__all__')
@pytest.mark.parametrize('microseconds', [0, 1, 582133, 999999])
@pytest.mark.parametrize('offset_hours', [0, -5, 5.5])
def test_actual_driver_preserves_timestamp_precision_and_envelope_identity(microseconds, offset_hours):
    utc = datetime(2026, 10, 4, 3, 49, 0, microseconds, tzinfo=UTC)
    stamp = utc.astimezone(datetime_timezone(timedelta(hours=offset_hours)))
    request = WorkflowRequest(uuid4(), Operation.HEALTH, (), stamp,
                              BranchProfile.BUSINESS)
    with connections['app_runtime'].cursor() as cursor:
        cursor.execute('SELECT %s::timestamptz, %s::timestamptz=%s::timestamptz',
                       [stamp, request.envelope()['effective_at'], stamp])
        returned, same_instant = cursor.fetchone()
    assert returned == utc
    assert returned.microsecond == microseconds
    assert same_instant is True


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_application_clock_ahead_does_not_override_database_time_admission(configured, monkeypatch):
    user, org, *_ = configured
    with connections['app_runtime'].cursor() as cursor:
        cursor.execute('SELECT clock_timestamp()')
        database_now = cursor.fetchone()[0]
    future = database_now + timedelta(hours=1)
    request = WorkflowRequest(org.id, Operation.HEALTH, (), future,
                              BranchProfile.BUSINESS)
    # Deliberate clock-skew model, not evidence this caused the prior failure.
    monkeypatch.setattr('apps.jobs.core_workflows.timezone.now',
                        lambda: future + timedelta(seconds=1))
    with pytest.raises(DatabaseError, match='Workflow request identity invalid'):
        dispatch(request, actor_id=user.id, using='app_runtime')
    assert not WorkflowRun.objects.filter(input_sha256=request.input_sha256).exists()


@pytest.mark.django_db(transaction=True, databases='__all__')
def test_sql_identity_discriminants_survive_denied_reassessment_and_honest_retry(configured):
    user, org, _, _, snapshot = configured
    request = WorkflowRequest(org.id, Operation.REASSESS, (snapshot.id,),
                              timezone.now(), BranchProfile.BUSINESS)
    # Invalid result shape must neither consume identity nor alter its request.
    invalid = {'schema': 'stewardence.workflow_receipt.v1',
               'authority': 'proposal_only', 'request': request.envelope(),
               'revision_id': str(uuid4()), 'proposal_count': '0',
               'state': 'reassessed'}
    with pytest.raises(DatabaseError):
        with identity_transaction(user.id, using='app_runtime'), tenant_transaction(org.id, using='app_runtime'):
            issue(request, invalid, user)
    assert not WorkflowRun.objects.filter(input_sha256=request.input_sha256).exists()

    observed = []
    def inspect_identity(execute, sql, params, many, context):
        if 'SELECT app_private.issue_workflow_run(' in sql:
            req = json.loads(params[6])['request']
            # Run independently on the same actual-role connection. Record each
            # source guard rather than assuming the timestamp caused a denial.
            with context['connection'].cursor() as cursor:
                cursor.execute("SELECT %s::timestamptz=%s::timestamptz, "
                               "%s::timestamptz<=clock_timestamp(), "
                               "%s::text ~ '[+]00:00$', "
                               "(SELECT profile FROM organization_workflow_profiles WHERE organization_id=%s)",
                               [req['effective_at'], params[5], params[5],
                                req['effective_at'], org.id])
                equal, not_future, utc_suffix, profile = cursor.fetchone()
            facts = {'time_equal': equal, 'not_future': not_future,
                     'utc_suffix': utc_suffix, 'profile_equal': profile == req['branch_profile'],
                     'organization_equal': req['organization_id'] == str(params[1]),
                     'operation_equal': req['operation'] == params[3],
                     'request_field_count': len(req)}
            observed.append(facts)
            assert facts == {'time_equal': True, 'not_future': True,
                             'utc_suffix': True, 'profile_equal': True,
                             'organization_equal': True, 'operation_equal': True,
                             'request_field_count': 6}, facts
        return execute(sql, params, many, context)

    with connections['app_runtime'].execute_wrapper(inspect_identity):
        issued = dispatch(request, actor_id=user.id, using='app_runtime')
    assert observed
    assert issued.payload['request'] == request.envelope()
    assert dispatch(request, actor_id=user.id, using='app_runtime').id == issued.id
