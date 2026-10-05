"""Core access requires a paid, owner-bound monthly price contract."""
import copy
import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
import stripe
from types import SimpleNamespace

from apps.billing.models import BillingCustomer, Subscription, StripeWebhookEvent
from apps.billing.views import _handle_checkout_completed, _retrieve_core_subscription
from stripe_fixtures import attach_paid_invoice

pytestmark = pytest.mark.django_db


def test_current_sdk_subscription_gateway_normalizes_nested_resources(checkout_evidence, settings, monkeypatch):
    from apps.billing.pricing import subscription_price_contract
    customer, session, authoritative = checkout_evidence
    settings.STRIPE_SECRET_KEY = 'rk_test_offline_qualification_only'
    resource = stripe.Subscription.construct_from(authoritative, settings.STRIPE_SECRET_KEY)
    calls = []

    def retrieve(external_id, params=None):
        assert params == {'expand': ['latest_invoice']}
        calls.append(external_id)
        return resource

    monkeypatch.setattr(stripe, 'StripeClient', lambda key: SimpleNamespace(
        v1=SimpleNamespace(subscriptions=SimpleNamespace(retrieve=retrieve))))
    result = _retrieve_core_subscription(session['subscription'])
    assert type(result) is dict
    assert type(result['items']['data'][0]['price']) is dict
    assert calls == [session['subscription']]
    assert subscription_price_contract(resource).cents == 9900


@pytest.fixture
def checkout_evidence(settings, monkeypatch):
    user = get_user_model().objects.create_user('core-admission@example.invalid','test-password')
    customer = BillingCustomer.objects.create(user=user,stripe_customer_id='cus_core_admission')
    settings.STRIPE_CORE_STANDARD_PRICE_ID = 'price_core_99'
    settings.FOUNDER_OFFER_ENABLED = False
    session = {'id':'cs_core_admission','client_reference_id':str(user.id),
        'mode':'subscription','status':'complete','payment_status':'paid',
        'customer':customer.stripe_customer_id,'subscription':'sub_core_admission',
        'metadata':{'portfolio':'core','stewardence_user_id':str(user.id)}}
    authoritative = {'id':'sub_core_admission','customer':customer.stripe_customer_id,
        'status':'active','metadata':dict(session['metadata']),
        'items':{'data':[{'quantity':1,'current_period_end':int((timezone.now()+timedelta(days=30)).timestamp()),
            'price':{'id':'price_core_99','active':True,'currency':'usd','unit_amount':9900,
                     'recurring':{'interval':'month','interval_count':1,'usage_type':'licensed'}}}]}}
    attach_paid_invoice(session, authoritative)
    # The existing Core path makes no authoritative retrieval; the successor
    # gateway is mocked when present. This never authorizes provider calls.
    monkeypatch.setattr('apps.billing.views._retrieve_core_subscription',
                        lambda external_id:copy.deepcopy(authoritative),raising=False)
    return customer,session,authoritative


@pytest.mark.parametrize('mutation',[
    'old_paid_current_unpaid','foreign_invoice_customer','foreign_invoice_subscription',
    'foreign_line_subscription','foreign_line_price','uncovered_period',
    'partial_payment','missing_invoice','unbound_session_invoice','truncated_lines',
    'future_paid_at','proration','boolean_paid_amount',
])
def test_checkout_payment_must_cover_current_period(checkout_evidence, mutation):
    customer, session, authoritative = checkout_evidence
    invoice = authoritative['latest_invoice']
    line = invoice['lines']['data'][0]
    if mutation == 'old_paid_current_unpaid':
        session['created'] -= 60*86400
        invoice.update(status='open',amount_paid=0,amount_remaining=9900)
    if mutation == 'foreign_invoice_customer': invoice['customer'] = 'cus_foreign'
    if mutation == 'foreign_invoice_subscription': invoice['parent']['subscription_details']['subscription'] = 'sub_foreign'
    if mutation == 'foreign_line_subscription': line['parent']['subscription_item_details']['subscription'] = 'sub_foreign'
    if mutation == 'foreign_line_price': line['pricing']['price_details']['price'] = 'price_foreign'
    if mutation == 'uncovered_period': line['period']['end'] -= 86400
    if mutation == 'partial_payment': invoice.update(amount_paid=4900,amount_remaining=5000)
    if mutation == 'missing_invoice': authoritative['latest_invoice'] = None
    if mutation == 'unbound_session_invoice': session['invoice'] = 'in_previous_paid_period'
    if mutation == 'truncated_lines': invoice['lines']['has_more'] = True
    if mutation == 'future_paid_at': invoice['status_transitions']['paid_at'] += 86400
    if mutation == 'proration': line['parent']['subscription_item_details']['proration'] = True
    if mutation == 'boolean_paid_amount': invoice['amount_paid'] = True
    with pytest.raises(RuntimeError):
        _handle_checkout_completed(session)
    assert not Subscription.objects.filter(billing_customer=customer).exists()


@pytest.mark.parametrize('field,value',[
    ('payment_status',None),('payment_status','no_payment_required'),
    ('customer','cus_other_owner'),('mode','payment'),('status','open'),
    ('subscription',None),
])
def test_invalid_session_cannot_issue_core_access(checkout_evidence,field,value):
    customer,session,authoritative = checkout_evidence
    session[field] = value
    with pytest.raises(RuntimeError):
        _handle_checkout_completed(session)
    assert not Subscription.objects.filter(billing_customer=customer).exists()


@pytest.mark.parametrize('mutation',[
    'foreign_customer','foreign_owner','unregistered_price','wrong_amount',
    'annual_price','inactive_subscription','missing_period','expired_period',
])
def test_invalid_subscription_cannot_issue_core_access(checkout_evidence,mutation):
    customer,session,authoritative = checkout_evidence
    item = authoritative['items']['data'][0]
    if mutation == 'foreign_customer': authoritative['customer'] = 'cus_other_owner'
    if mutation == 'foreign_owner': authoritative['metadata']['stewardence_user_id'] = 'other-owner'
    if mutation == 'unregistered_price': item['price']['id'] = 'price_unregistered'
    if mutation == 'wrong_amount': item['price']['unit_amount'] = 4900
    if mutation == 'annual_price': item['price']['recurring']['interval'] = 'year'
    if mutation == 'inactive_subscription': authoritative['status'] = 'incomplete'
    if mutation == 'missing_period': item.pop('current_period_end')
    if mutation == 'expired_period': item['current_period_end'] = 1
    with pytest.raises(RuntimeError):
        _handle_checkout_completed(session)
    assert not Subscription.objects.filter(billing_customer=customer).exists()


def test_paid_core_contract_records_its_verified_period(checkout_evidence):
    customer,session,authoritative = checkout_evidence
    _handle_checkout_completed(session)
    subscription = Subscription.objects.get(billing_customer=customer)
    assert subscription.current_price_cents == 9900
    assert subscription.current_period_end is not None
    assert int(subscription.current_period_end.timestamp()) == authoritative['items']['data'][0]['current_period_end']


def signed_fixture_request(client,settings,session,*,fault=None):
    # Locally generated fixture secret; this is actual SDK signature checking,
    # not an event delivered by Stripe and not a production credential.
    settings.STRIPE_SECRET_KEY = 'rk_test_offline_qualification_only'
    settings.STRIPE_WEBHOOK_SECRET = 'whsec_offline_qualification_only'
    event = {'id':'evt_core_offline','type':'checkout.session.completed',
             'livemode':False,'data':{'object':session}}
    body = json.dumps(event,separators=(',',':')).encode()
    timestamp = int(time.time())-600 if fault == 'expired' else int(time.time())
    secret = 'wrong_fixture_secret' if fault == 'wrong_signature' else settings.STRIPE_WEBHOOK_SECRET
    digest = hmac.new(secret.encode(),str(timestamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
    signature = 't='+str(timestamp)+',v1='+digest
    if fault == 'tampered_body': body += b' '
    if fault == 'missing_signature': signature = ''
    return client.post(reverse('billing:stripe-webhook'),data=body,content_type='application/json',
                       HTTP_STRIPE_SIGNATURE=signature)


@pytest.mark.parametrize('fault',['tampered_body','expired','wrong_signature','missing_signature'])
def test_actual_sdk_signature_rejects_invalid_envelopes(client,settings,checkout_evidence,fault):
    customer,session,authoritative = checkout_evidence
    response = signed_fixture_request(client,settings,session,fault=fault)
    assert response.status_code == 400
    assert not Subscription.objects.filter(billing_customer=customer).exists()
    assert not StripeWebhookEvent.objects.exists()


def test_signed_fixture_requires_admitted_price_before_receipt_commit(client,settings,checkout_evidence):
    customer,session,authoritative = checkout_evidence
    authoritative['items']['data'][0]['price']['unit_amount'] = 4900
    with pytest.raises(RuntimeError):
        signed_fixture_request(client,settings,session)
    assert not Subscription.objects.filter(billing_customer=customer).exists()
    assert not StripeWebhookEvent.objects.exists()


def test_signed_paid_fixture_fulfills_once(client,settings,checkout_evidence):
    customer,session,authoritative = checkout_evidence
    first = signed_fixture_request(client,settings,session)
    second = signed_fixture_request(client,settings,session)
    assert first.status_code == second.status_code == 200
    assert Subscription.objects.filter(billing_customer=customer).count() == 1
    assert StripeWebhookEvent.objects.count() == 1


@pytest.mark.parametrize('fault',['unpaid_current_invoice','different_invoice','uncovered_period'])
def test_signed_coverage_failure_rolls_back_and_same_event_can_recover(client,settings,checkout_evidence,fault):
    customer,session,authoritative = checkout_evidence
    healthy = copy.deepcopy(authoritative['latest_invoice'])
    original_invoice = session['invoice']
    if fault == 'unpaid_current_invoice':
        session['created'] -= 60*86400
        authoritative['latest_invoice'].update(status='open',amount_paid=0,amount_remaining=9900)
    if fault == 'different_invoice': session['invoice'] = 'in_old_paid_checkout'
    if fault == 'uncovered_period': authoritative['latest_invoice']['lines']['data'][0]['period']['end'] -= 86400
    with pytest.raises(RuntimeError):
        signed_fixture_request(client,settings,session)
    assert not Subscription.objects.filter(billing_customer=customer).exists()
    assert not StripeWebhookEvent.objects.exists()
    authoritative['latest_invoice'] = healthy
    session['invoice'] = original_invoice
    response = signed_fixture_request(client,settings,session)
    assert response.status_code == 200
    assert Subscription.objects.filter(billing_customer=customer).count() == 1
    assert StripeWebhookEvent.objects.count() == 1


@pytest.mark.parametrize('fault',['boolean_item','dictionary_item','float_root_start',
    'wrong_line_invoice','wrong_line_kind','null_line_kind'])
def test_signed_unsupported_coverage_shape_cannot_commit(client,settings,checkout_evidence,fault):
    customer,session,authoritative = checkout_evidence
    item = authoritative['items']['data'][0]
    line = authoritative['latest_invoice']['lines']['data'][0]
    if fault == 'boolean_item':
        item['id'] = True
        line['parent']['subscription_item_details']['subscription_item'] = 1
    if fault == 'dictionary_item':
        item['id'] = {'id':'si_fabricated'}
        line['parent']['subscription_item_details']['subscription_item'] = dict(item['id'])
    if fault == 'float_root_start': authoritative['current_period_start'] = float(item['current_period_start'])
    if fault == 'wrong_line_invoice': line['invoice'] = 'in_different'
    if fault == 'wrong_line_kind': line['object'] = 'customer'
    if fault == 'null_line_kind': line['object'] = None
    with pytest.raises(RuntimeError):
        signed_fixture_request(client,settings,session)
    assert not Subscription.objects.filter(billing_customer=customer).exists()
    assert not StripeWebhookEvent.objects.exists()


@pytest.mark.parametrize('projection',['absent','nullable_invoice','explicit_consistent'])
def test_supported_line_identity_projection_can_fulfill(client,settings,checkout_evidence,projection):
    customer,session,authoritative = checkout_evidence
    line = authoritative['latest_invoice']['lines']['data'][0]
    if projection == 'nullable_invoice': line['invoice'] = None
    if projection == 'explicit_consistent':
        line.update(invoice=authoritative['latest_invoice']['id'],object='line_item')
    response = signed_fixture_request(client,settings,session)
    assert response.status_code == 200
    assert Subscription.objects.filter(billing_customer=customer).count() == 1
    assert StripeWebhookEvent.objects.count() == 1


@pytest.mark.parametrize('secret',['','   ','whsec_'])
def test_unconfigured_webhook_secret_fails_closed_before_admission(client,settings,secret):
    settings.STRIPE_SECRET_KEY = 'rk_test_offline_qualification_only'
    settings.STRIPE_WEBHOOK_SECRET = secret
    body = json.dumps({'id':'evt_unconfigured_auth_fixture','type':'unhandled.fixture',
                       'data':{'object':{}}},separators=(',',':')).encode()
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode(),timestamp.encode()+b'.'+body,hashlib.sha256).hexdigest()
    response = client.post(reverse('billing:stripe-webhook'),data=body,content_type='application/json',
                           HTTP_STRIPE_SIGNATURE='t='+timestamp+',v1='+digest)
    assert response.status_code == 503
    assert not StripeWebhookEvent.objects.exists()
    assert not Subscription.objects.exists()
