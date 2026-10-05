"""Initial slice actual-role qualification, not full review artifact delivery."""
from uuid import uuid4
import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections, DatabaseError, transaction
from django.utils import timezone
from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.snapshots import canonical_sha256
from apps.billing.models import PaidCoverage, PaidCoverageAuthority, Subscription
from apps.jobs.core_workflows import configure_control
from apps.organizations.models import Organization, OrganizationMember, WorkflowProfile
from apps.reviews.models import ReviewCycle, CycleEvent, PackIdentity, CapacityReservation, ReservationEvent
from apps.reviews.services import open_cycle, freeze_cycle

pytestmark = pytest.mark.django_db(transaction=True, databases='__all__')


@pytest.fixture
def review_owner(report_context):
    user, org, _, _, snapshot = report_context
    WorkflowProfile.objects.create(organization=org, created_by=user,
                                   profile='business.v1', settings={'name':'Main'})
    return user, org, snapshot


def opened(context):
    user, org, snapshot = context
    return open_cycle(organization_id=org.id, actor_id=user.id,
                      input_snapshot_id=snapshot.id, using='app_runtime')


def frozen(context, cycle, revision=1):
    user, org, _ = context
    return freeze_cycle(cycle_id=cycle.id, organization_id=org.id,
                        actor_id=user.id, expected_revision=revision, using='app_runtime')


def persisted(cycle):
    # Administrative assertion reader; application callers must retain their
    # owner/tenant transaction when accessing lazy related event state.
    return ReviewCycle.objects.get(id=cycle.id)


def test_initial_freeze_is_atomic_immutable_and_honest_about_empty_decisions(review_owner):
    user, org, snapshot = review_owner
    cycle = opened(review_owner)
    assert persisted(cycle).state == 'OPEN' and persisted(cycle).revision == 1
    pack = frozen(review_owner, cycle)
    assert list(CycleEvent.objects.filter(cycle=cycle).order_by('revision').values_list('state',flat=True)) == ['OPEN','FINALIZATION_REQUESTED','FROZEN']
    assert pack.sha256 == canonical_sha256(pack.manifest)
    assert pack.manifest['selected_decisions'] == []
    assert pack.manifest['selection_scope'] == 'empty_initial_kernel'
    assert pack.manifest['artifact_state'] == 'not_created'
    assert pack.manifest['baseline_promotion'] == 'blocked'
    pinned = pack.manifest['snapshot']
    assert pinned['snapshot_id'] == str(snapshot.id)
    assert pinned['input_sha256'] == snapshot.input_sha256
    assert pinned['result_sha256'] == snapshot.result_sha256
    assert pinned['rules_sha256'] == canonical_sha256(snapshot.input_payload['rulesets'])
    assert pinned['configuration_sha256'] == canonical_sha256(snapshot.input_payload['risk_configuration'])
    assert pinned['workflow_profile'] == 'business.v1'
    assert pinned['workflow_settings_sha256'] == canonical_sha256({'name':'Main'})
    reservation = CapacityReservation.objects.get(cycle=cycle)
    assert reservation.paid_coverage.subscription.organization_id == org.id
    assert reservation.state == 'reserved' and reservation.reserved_bytes == 16*1048576
    event = ReservationEvent.objects.get(reservation=reservation)
    assert event.state == 'reserved' and event.sha256 == canonical_sha256(event.payload)
    assert frozen(review_owner,cycle).id == pack.id
    assert PackIdentity.objects.filter(cycle=cycle).count() == 1
    assert CapacityReservation.objects.filter(cycle=cycle).count() == 1


@pytest.mark.parametrize('table', ['review_cycles','review_cycle_events','review_pack_identities','review_capacity_reservations','review_reservation_events'])
def test_app_raw_admission_and_mutation_are_denied(review_owner,table):
    user, org, _ = review_owner
    for statement in (f'INSERT INTO {table}(id) VALUES(%s)',
                      f'UPDATE {table} SET created_by_id=%s',
                      f'DELETE FROM {table} WHERE id=%s'):
        with pytest.raises(DatabaseError,match='permission denied'):
            with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
                with connections['app_runtime'].cursor() as cursor:
                    cursor.execute(statement,[uuid4()])


@pytest.mark.parametrize('table', ['review_cycles','review_cycle_events','review_pack_identities','review_capacity_reservations','review_reservation_events'])
def test_worker_has_no_review_table_access(table):
    with pytest.raises(DatabaseError,match='permission denied'),transaction.atomic(using='worker_runtime'):
        with connections['worker_runtime'].cursor() as cursor:
            cursor.execute(f'SELECT id FROM {table}')


def test_owner_role_in_another_workspace_does_not_authorize_review_reads(review_owner):
    user, org, _ = review_owner
    cycle = opened(review_owner)
    other = Organization.objects.create(name='Other review org')
    viewer = get_user_model().objects.create_user('review-viewer@example.invalid')
    OrganizationMember.objects.create(organization=other,user=viewer,role='owner')
    OrganizationMember.objects.create(organization=org,user=viewer,role='viewer')
    with identity_transaction(viewer.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
        assert not ReviewCycle.objects.using('app_runtime').filter(id=cycle.id).exists()
    with pytest.raises(DatabaseError):
        with identity_transaction(viewer.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
            with connections['app_runtime'].cursor() as cursor:
                cursor.execute('SELECT app_private.open_review_cycle(%s,%s,%s,%s)',
                               [uuid4(),org.id,viewer.id,review_owner[2].id])


def test_unadmitted_billing_authority_blocks_freeze_without_partial_events(review_owner):
    cycle = opened(review_owner)
    PaidCoverageAuthority.objects.all().delete()
    with pytest.raises(DatabaseError,match='admission unavailable'):
        frozen(review_owner,cycle)
    assert CycleEvent.objects.filter(cycle=cycle).count() == 1
    assert not PackIdentity.objects.filter(cycle=cycle).exists()
    assert not CapacityReservation.objects.filter(cycle=cycle).exists()


def test_pause_fences_freeze_and_keeps_open_identity(review_owner):
    user, org, _ = review_owner
    cycle = opened(review_owner)
    configure_control(organization_id=org.id,actor_id=user.id,mode='paused',reason='Qualification pause')
    with pytest.raises(DatabaseError,match='admission unavailable'):
        frozen(review_owner,cycle)
    assert persisted(cycle).state == 'OPEN'


def test_one_open_and_one_frozen_pending_are_enforced(review_owner):
    first = opened(review_owner)
    with pytest.raises(DatabaseError,match='open capacity'):
        opened(review_owner)
    frozen(review_owner,first)
    second = opened(review_owner)
    with pytest.raises(DatabaseError,match='frozen pending capacity'):
        frozen(review_owner,second)
    assert persisted(second).state == 'OPEN'
    assert not CapacityReservation.objects.filter(cycle=second).exists()


@pytest.mark.parametrize('revision',[0,2,3,True,'1',None])
def test_revision_cas_rejects_aliases_and_stale_state(review_owner,revision):
    cycle = opened(review_owner)
    with pytest.raises(ValidationError):
        frozen(review_owner,cycle,revision)
    assert persisted(cycle).state == 'OPEN'


def test_baseline_promotion_is_explicitly_not_admitted(review_owner):
    user, org, snapshot = review_owner
    with pytest.raises(ValidationError,match='not qualified'):
        open_cycle(organization_id=org.id,actor_id=user.id,input_snapshot_id=snapshot.id,
                   baseline_pack_id=uuid4(),using='app_runtime')
    assert not ReviewCycle.objects.exists()


def test_server_manifest_cannot_be_supplied_by_caller(review_owner):
    cycle = opened(review_owner)
    with pytest.raises(TypeError):
        freeze_cycle(cycle_id=cycle.id,organization_id=review_owner[1].id,
                     actor_id=review_owner[0].id,expected_revision=1,
                     manifest={'selected_decisions':['forged']},using='app_runtime')


def test_reservation_has_no_timeout_or_arbitrary_release_interface(review_owner):
    cycle = opened(review_owner)
    frozen(review_owner,cycle)
    reservation = CapacityReservation.objects.get(cycle=cycle)
    with pytest.raises(DatabaseError,match='immutable'),transaction.atomic():
        CapacityReservation.objects.filter(id=reservation.id).update(state='provenunused')
    assert ReservationEvent.objects.filter(reservation=reservation).count() == 1


def test_raw_issuer_rejects_corrupt_same_tenant_snapshot(review_owner):
    user, org, snapshot = review_owner
    poisoned = uuid4()
    # Administrative negative fixture only; runtime cannot mutate snapshots.
    with connections['default'].cursor() as cursor:
        cursor.execute('INSERT INTO assessment_snapshots(id,organization_id,assessment_id,version,created_by_id,captured_at,input_payload,result_payload,input_sha256,result_sha256,created_at) SELECT %s,organization_id,%s,version,created_by_id,captured_at,input_payload,result_payload,%s,result_sha256,created_at FROM assessment_snapshots WHERE id=%s',
                       [poisoned,uuid4(),'0'*64,snapshot.id])
    with pytest.raises(DatabaseError,match='integrity invalid'):
        with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
            with connections['app_runtime'].cursor() as cursor:
                cursor.execute('SELECT app_private.open_review_cycle(%s,%s,%s,%s)',[uuid4(),org.id,user.id,poisoned])
    assert not ReviewCycle.objects.exists()


def test_quota_counts_held_reservations_against_exact_admitted_interval(review_owner):
    user, org, snapshot = review_owner
    paid = PaidCoverage.objects.get(subscription__organization=org)
    # Synthetic administrative ledger population models already held outcomes;
    # no claim these fixtures were admitted by a completed artifact workflow.
    for _ in range(12):
        prior = ReviewCycle.objects.create(organization=org,created_by=user,
            created_at=timezone.now(),input_snapshot=snapshot)
        CapacityReservation.objects.create(organization=org,created_by=user,
            created_at=timezone.now(),cycle=prior,paid_coverage=paid,
            reserved_bytes=16*1048576,state='reserved')
    cycle = opened(review_owner)
    with pytest.raises(DatabaseError,match='billing interval capacity'):
        frozen(review_owner,cycle)
    assert persisted(cycle).state == 'OPEN'
    assert not CapacityReservation.objects.filter(cycle=cycle).exists()


@pytest.mark.parametrize('over_limit',[False,True])
def test_storage_metadata_plus_reservation_has_exact_boundary(review_owner,over_limit):
    from apps.reports.models import ReportArtifact
    from apps.reports.services import create_report
    user, org, snapshot = review_owner
    report = create_report(organization_id=org.id,created_by_id=user.id,
                           assessment_snapshot_id=snapshot.id)
    ReportArtifact.objects.create(organization=org,report=report,assessment_snapshot=snapshot,
        object_key=f'organizations/{org.id}/assessments/{snapshot.id}/reports/{report.id}.pdf',
        sha256='a'*64,size_bytes=3*1024**3-16*1048576+int(over_limit))
    cycle = opened(review_owner)
    if over_limit:
        with pytest.raises(DatabaseError,match='storage reservation capacity'):
            frozen(review_owner,cycle)
        assert not CapacityReservation.objects.filter(cycle=cycle).exists()
    if not over_limit:
        frozen(review_owner,cycle)
        assert CapacityReservation.objects.get(cycle=cycle).reserved_bytes == 16*1048576


def test_concurrent_freeze_returns_one_pack_and_one_reservation(review_owner):
    import threading
    cycle = opened(review_owner)
    barrier = threading.Barrier(2)
    results, failures = [], []
    def attempt():
        try:
            barrier.wait(timeout=10)
            results.append(frozen(review_owner,cycle).id)
        except Exception as error:
            failures.append(type(error).__name__)
        finally:
            connections['app_runtime'].close()
    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not any(thread.is_alive() for thread in threads)
    assert failures == []
    assert len(results)==2 and results[0]==results[1]
    assert PackIdentity.objects.filter(cycle=cycle).count()==1
    assert CapacityReservation.objects.filter(cycle=cycle).count()==1


def test_repeatable_read_cannot_admit_cycle_from_stale_authority_snapshot(review_owner):
    user, org, snapshot = review_owner
    with pytest.raises(DatabaseError,match='read committed'):
        with transaction.atomic(using='app_runtime'):
            with connections['app_runtime'].cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            with identity_transaction(user.id,using='app_runtime'),tenant_transaction(org.id,using='app_runtime'):
                with connections['app_runtime'].cursor() as cursor:
                    cursor.execute('SELECT app_private.open_review_cycle(%s,%s,%s,%s)',
                                   [uuid4(),org.id,user.id,snapshot.id])
    assert not ReviewCycle.objects.exists()


def test_past_due_with_admitted_unexpired_service_can_freeze(review_owner):
    cycle = opened(review_owner)
    Subscription.objects.filter(organization=review_owner[1]).update(status='past_due')
    pack = frozen(review_owner,cycle)
    assert pack.manifest['artifact_state'] == 'not_created'
    assert CapacityReservation.objects.filter(cycle=cycle).count() == 1


def test_past_due_with_only_expired_admitted_service_cannot_freeze(review_owner):
    from apps.billing.entitlements import issue_paid_coverage
    import hashlib
    import json
    cycle = opened(review_owner)
    subscription = Subscription.objects.get(organization=review_owner[1])
    prior = PaidCoverage.objects.get(subscription=subscription)
    generation = 'sub_expired_qualification_'+uuid4().hex
    subscription.status = 'past_due'
    subscription.stripe_subscription_id = generation
    subscription.save(update_fields=['status','stripe_subscription_id'])
    evidence = dict(prior.admission_payload)
    now = int(timezone.now().timestamp())
    evidence.update(stripe_subscription_id=generation,
        stripe_invoice_id='in_expired_qualification_'+uuid4().hex,
        stripe_event_id='evt_expired_qualification_'+uuid4().hex,
        service_start=now-31*86400,service_end=now-86400,paid_at=now-31*86400+30)
    evidence['evidence_sha256'] = hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
    # Actual isolated billing-admission login, synthetic historic payment only.
    issue_paid_coverage(evidence,using='billing_admission')
    with pytest.raises(DatabaseError,match='admission unavailable'):
        frozen(review_owner,cycle)
    assert persisted(cycle).state == 'OPEN'
    assert not CapacityReservation.objects.filter(cycle=cycle).exists()


def test_capacity_wait_cannot_reuse_pre_revocation_paid_authority(review_owner):
    import threading
    import time
    user, org, snapshot = review_owner
    scope = f'review:{org.id}:capacity'
    outcome = []
    def attempt():
        try:
            opened(review_owner)
            outcome.append('admitted')
        except DatabaseError as error:
            outcome.append('denied' if 'paid owner admission unavailable' in str(error) else type(error).__name__)
        finally:
            connections['app_runtime'].close()
    with connections['default'].cursor() as cursor:
        cursor.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))',[scope])
    thread = threading.Thread(target=attempt)
    try:
        thread.start()
        deadline = time.monotonic()+10
        observed_wait = False
        while time.monotonic()<deadline:
            with connections['default'].cursor() as cursor:
                cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.usename='agentledger_app' AND position('app_private.open_review_cycle' in a.query)>0 AND l.locktype='advisory' AND NOT l.granted)")
                observed_wait = cursor.fetchone()[0]
            if observed_wait:
                break
            threading.Event().wait(.02)
        assert observed_wait, 'Actual app login never reached advisory-lock barrier'
        PaidCoverageAuthority.objects.all().delete()
    finally:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))',[scope])
        thread.join(timeout=15)
    assert not thread.is_alive()
    assert outcome == ['denied']
    assert not ReviewCycle.objects.exists()
