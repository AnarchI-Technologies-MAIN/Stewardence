"""Actual-role durable standard requests; no Stripe calls or real payments."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from django.contrib.auth import get_user_model
from django.db import connections,transaction,DatabaseError
from django.utils import timezone
from agentledger.tenancy.context import identity_transaction
from apps.billing.models import BillingCustomer,PaidCoverageAuthority,CheckoutIntent,Subscription
from apps.billing.checkout_intents import reserve_standard_checkout,checkout_create_allowed,record_checkout_observation,admit_checkout_outcome,customer_creation_idempotency_key

pytestmark=pytest.mark.django_db(transaction=True,databases='__all__')

@pytest.fixture
def owner():
    user=get_user_model().objects.create_user(email='intent-owner@example.invalid')
    customer=BillingCustomer.objects.create(user=user,stripe_customer_id='cus_intent')
    PaidCoverageAuthority.objects.create(stripe_account_id='acct_intent',livemode=False,contracts={
        'standard':{'price_id':'price_core','amount_cents':9900,'contract_version':'core.monthly.v1'}})
    return user,customer

def reserve(owner,**extra):
    user,customer=owner
    return reserve_standard_checkout(customer_id=customer.id,actor_id=user.id,
        success_url=extra.get('success_url','https://stewardence.example.invalid/billing/success/'),
        cancel_url='https://stewardence.example.invalid/billing/cancel/',using='app_runtime')

def outcome(intent,status='open',**changes):
    params=dict(generation=intent.generation,session_id='cs_authoritative',status=status,
        customer_id=intent.stripe_customer_id,account_id=intent.stripe_account_id,livemode=intent.livemode,
        expires_at=int(intent.expires_at.timestamp()))
    return admit_checkout_outcome(intent.id,**{**params,**changes})

def test_retry_freezes_every_parameter_and_idempotency_key(owner):
    first=reserve(owner)
    second=reserve(owner,success_url='https://changed.example.invalid/')
    assert first.id==second.id and first.params==second.params and first.idempotency_key==second.idempotency_key
    assert first.params['line_items']==[{'price':'price_core','quantity':1}]
    assert first.params['subscription_data']['metadata']['checkout_generation']==str(first.generation)
    assert first.params['expires_at']==int(first.expires_at.timestamp())
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert checkout_create_allowed(first.id,using='app_runtime')
    assert customer_creation_idempotency_key(owner[1].id)==customer_creation_idempotency_key(str(owner[1].id))

def test_eight_concurrent_reservations_share_one_generation(owner):
    barrier=Barrier(8)
    def call():
        try:
            barrier.wait(timeout=10)
            intent=reserve(owner)
            return intent.id,intent.idempotency_key,intent.params_sha256
        finally:connections['app_runtime'].close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=[future.result(timeout=20) for future in [pool.submit(call) for _ in range(8)]]
    assert len(set(results))==1
    assert CheckoutIntent.objects.count()==1

def test_observation_does_not_authorize_payment_or_expiry(owner):
    intent=reserve(owner)
    observed=record_checkout_observation(intent.id,actor_id=owner[0].id,generation=intent.generation,
        session_id='cs_observed',url='https://checkout.stripe.com/c/pay/synthetic',using='app_runtime')
    assert observed.state=='pending' and observed.stripe_session_id is None
    assert observed.observed_session_id=='cs_observed'
    assert outcome(intent)=='attached'
    intent.refresh_from_db(using='default')
    assert intent.stripe_session_id=='cs_authoritative'
    assert reserve(owner).id==intent.id

@pytest.mark.parametrize('changes',[{'generation':uuid4()},{'customer_id':'cus_other'},
    {'account_id':'acct_other'},{'livemode':True},{'expires_at':1}])
def test_admission_rejects_changed_generation_binding(owner,changes):
    intent=reserve(owner)
    with pytest.raises(DatabaseError),transaction.atomic(using='billing_admission'):outcome(intent,**changes)
    intent.refresh_from_db(using='default')
    assert intent.state=='pending' and intent.stripe_session_id is None

def test_app_cannot_assert_expiry_and_admission_cannot_expire_early(owner):
    intent=reserve(owner)
    with pytest.raises(DatabaseError) as denied,transaction.atomic(using='app_runtime'):
        outcome(intent,using='app_runtime')
    assert denied.value.__cause__.sqlstate=='42501'
    with pytest.raises(DatabaseError),transaction.atomic(using='billing_admission'):outcome(intent,status='expired')
    assert reserve(owner).id==intent.id

def test_expired_ambiguous_fixture_is_held_until_authoritative_expiry(owner):
    # Explicit synthetic administrative fixture; not an admitted provider result.
    user,customer=owner
    expiry=(timezone.now()-timezone.timedelta(hours=1)).replace(microsecond=0)
    intent=CheckoutIntent(id=uuid4(),generation=uuid4(),billing_customer=customer,owner=user,
        stripe_customer_id='cus_intent',stripe_account_id='acct_intent',livemode=False,stripe_price_id='price_core',
        contract_version='core.monthly.v1',params={'synthetic_fixture':True},params_sha256='a'*64,
        idempotency_key='synthetic-expired-key',expires_at=expiry,created_at=expiry-timezone.timedelta(hours=1),state='pending')
    CheckoutIntent.objects.bulk_create([intent])
    assert reserve(owner).id==intent.id
    with identity_transaction(user.id,using='app_runtime'):
        assert not checkout_create_allowed(intent.id,using='app_runtime')
    assert outcome(intent,status='expired')=='expired'
    replacement=reserve(owner)
    assert replacement.id!=intent.id and replacement.idempotency_key!=intent.idempotency_key

def test_other_owner_cannot_read_or_observe_intent(owner):
    intent=reserve(owner)
    other=get_user_model().objects.create_user(email='other-intent@example.invalid')
    with identity_transaction(other.id,using='app_runtime'):
        assert not CheckoutIntent.objects.using('app_runtime').filter(pk=intent.id).exists()
    with pytest.raises(DatabaseError):
        record_checkout_observation(intent.id,actor_id=other.id,generation=intent.generation,
            session_id='cs_other',url='https://checkout.stripe.com/c/pay/synthetic',using='app_runtime')

def test_raw_role_writes_and_request_mutation_are_denied(owner):
    intent=reserve(owner)
    for alias in ('app_runtime','worker_runtime','billing_admission'):
        with pytest.raises(DatabaseError) as denied,transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:cursor.execute('UPDATE billing_checkout_intents SET state=%s WHERE id=%s',['expired',intent.id])
        assert denied.value.__cause__.sqlstate=='42501'
    with pytest.raises(DatabaseError),transaction.atomic():CheckoutIntent.objects.filter(pk=intent.id).update(params={})

def test_unresolved_external_subscription_blocks_another_checkout(owner):
    Subscription.objects.create(billing_customer=owner[1],stripe_subscription_id='sub_existing',status='past_due')
    with pytest.raises(DatabaseError,match='billing recovery'):reserve(owner)
    assert not CheckoutIntent.objects.exists()

def test_changed_price_pin_holds_original_request_instead_of_creating_new(owner):
    intent=reserve(owner)
    authority=PaidCoverageAuthority.objects.get(pk=1)
    authority.contracts['standard']['price_id']='price_replacement'
    authority.save(update_fields=['contracts'])
    assert reserve(owner).id==intent.id
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert not checkout_create_allowed(intent.id,using='app_runtime')

def test_completed_session_is_held_without_paid_generation_adjudication(owner):
    intent=reserve(owner)
    assert outcome(intent,status='complete')=='complete'
    assert reserve(owner).id==intent.id
    assert CheckoutIntent.objects.count()==1
    with identity_transaction(owner[0].id,using='app_runtime'):
        assert not checkout_create_allowed(intent.id,using='app_runtime')
