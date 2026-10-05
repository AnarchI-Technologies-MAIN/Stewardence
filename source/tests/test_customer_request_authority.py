"""Actual-role synthetic Customer create request protocol; no provider calls."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import hashlib
import pytest
import rfc8785
from django.contrib.auth import get_user_model
from django.db import connections,transaction,DatabaseError
from django.utils import timezone
from agentledger.tenancy.context import identity_transaction
from apps.billing.models import BillingCustomer,BillingCustomerRequest,PaidCoverageAuthority
from apps.billing.customer_requests import reserve_customer_request,customer_create_allowed,record_customer_observation

pytestmark=pytest.mark.django_db(transaction=True,databases='__all__')

@pytest.fixture
def owner():
    user=get_user_model().objects.create_user(email='customer-request@example.invalid')
    customer=BillingCustomer.objects.create(user=user)
    PaidCoverageAuthority.objects.create(stripe_account_id='acct_customerrequest',livemode=False,contracts={})
    return user,customer

def reserve(owner,**changes):
    return reserve_customer_request(customer_id=owner[1].id,actor_id=owner[0].id,
        email=changes.get('email',owner[0].email),name=changes.get('name','Original Name'),using='app_runtime')

def observe(owner,request,customer='cus_observed',**changes):
    return record_customer_observation(request.id,actor_id=changes.get('actor_id',owner[0].id),
        generation=changes.get('generation',request.generation),external_customer_id=customer,using='app_runtime')

def test_profile_changes_do_not_change_frozen_customer_body(owner):
    first=reserve(owner)
    second=reserve(owner,email='changed@example.invalid',name='Changed Name')
    assert first.id==second.id and first.generation==second.generation
    assert second.params=={'email':owner[0].email,'name':'Original Name','metadata':{'stewardence_user_id':str(owner[0].id)}}
    assert first.idempotency_key==second.idempotency_key=='stewardence-customer-v1:'+str(owner[1].id)
    assert second.params_sha256==hashlib.sha256(rfc8785.dumps(second.params)).hexdigest()
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert customer_create_allowed(first.id,using='app_runtime')

def test_eight_concurrent_reservations_converge(owner):
    barrier=Barrier(8)
    def call():
        try:
            barrier.wait(timeout=10)
            request=reserve(owner)
            return request.id,request.generation,request.params_sha256,request.idempotency_key
        finally:connections['app_runtime'].close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        result=[future.result(timeout=20) for future in [pool.submit(call) for _ in range(8)]]
    assert len(set(result))==1 and BillingCustomerRequest.objects.count()==1

def test_observed_customer_binding_is_exact_cas_and_stops_create(owner):
    request=reserve(owner)
    assert observe(owner,request).observed_customer_id=='cus_observed'
    assert observe(owner,request).observed_customer_id=='cus_observed'
    with pytest.raises(DatabaseError):observe(owner,request,customer='cus_replacement')
    owner[1].refresh_from_db()
    assert owner[1].stripe_customer_id=='cus_observed'
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert not customer_create_allowed(request.id,using='app_runtime')

@pytest.mark.parametrize('change',['owner','generation'])
def test_observation_rejects_wrong_owner_or_generation(owner,change):
    request=reserve(owner)
    changes={'generation':uuid4()}
    if change=='owner':
        other=get_user_model().objects.create_user(email='other-request@example.invalid')
        changes={'actor_id':other.id}
    with pytest.raises(DatabaseError):observe(owner,request,**changes)
    owner[1].refresh_from_db()
    assert owner[1].stripe_customer_id is None

@pytest.mark.parametrize('age_hours,allowed',[(22,True),(23,False),(25,False)])
def test_ambiguous_customer_request_holds_after_23_hours(owner,age_hours,allowed):
    # Administrative fixture models a pre-existing durable request; no admission bypass.
    params={'email':owner[0].email,'name':None,'metadata':{'stewardence_user_id':str(owner[0].id)}}
    request=BillingCustomerRequest(id=uuid4(),billing_customer=owner[1],owner=owner[0],generation=uuid4(),
        stripe_account_id='acct_customerrequest',livemode=False,params=params,
        params_sha256=hashlib.sha256(rfc8785.dumps(params)).hexdigest(),
        idempotency_key='stewardence-customer-v1:'+str(owner[1].id),created_at=timezone.now()-timezone.timedelta(hours=age_hours))
    BillingCustomerRequest.objects.bulk_create([request])
    assert reserve(owner,email='new@example.invalid').id==request.id
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert customer_create_allowed(request.id,using='app_runtime') is allowed
    assert BillingCustomerRequest.objects.count()==1

def test_raw_roles_cannot_rewrite_request_or_override_bound_customer(owner):
    request=reserve(owner)
    observe(owner,request)
    for alias in ('app_runtime','worker_runtime','billing_admission'):
        with pytest.raises(DatabaseError) as denied,transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:cursor.execute('UPDATE billing_customer_requests SET params=%s::jsonb WHERE id=%s',['{}',request.id])
        assert denied.value.__cause__.sqlstate=='42501'
    with pytest.raises(DatabaseError),identity_transaction(owner[0].id,using='app_runtime'):
        BillingCustomer.objects.using('app_runtime').filter(pk=owner[1].id).update(stripe_customer_id='cus_other')
    with pytest.raises(DatabaseError),transaction.atomic():
        BillingCustomerRequest.objects.filter(pk=request.id).update(created_at=timezone.now())

def test_other_owner_cannot_read_customer_create_body(owner):
    reserve(owner)
    other=get_user_model().objects.create_user(email='other-body@example.invalid')
    with identity_transaction(other.id,using='app_runtime'):
        assert not BillingCustomerRequest.objects.using('app_runtime').exists()

def test_account_pin_change_holds_original_customer_request(owner):
    request=reserve(owner)
    PaidCoverageAuthority.objects.filter(pk=1).update(stripe_account_id='acct_new')
    assert reserve(owner).id==request.id
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert not customer_create_allowed(request.id,using='app_runtime')

def test_concurrent_conflicting_observations_bind_only_one_external_identity(owner):
    request=reserve(owner)
    barrier=Barrier(8)
    def call(index):
        try:
            barrier.wait(timeout=10)
            try:return observe(owner,request,customer=f'cus_contender_{index}').observed_customer_id
            except DatabaseError:return None
        finally:connections['app_runtime'].close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=[future.result(timeout=20) for future in [pool.submit(call,i) for i in range(8)]]
    successes=[value for value in results if value is not None]
    assert len(successes)==1
    owner[1].refresh_from_db()
    assert owner[1].stripe_customer_id==successes[0]
