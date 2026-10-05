"""Explicit synthetic paid-contract evidence for legacy lifecycle tests."""
from datetime import timedelta
from django.utils import timezone


def attach_paid_invoice(session, authoritative):
    """Explicit current-period payment coverage, synthetic and never provider data."""
    now = int(timezone.now().timestamp())
    item = authoritative['items']['data'][0]
    item.update({'id':'si_fixture_core','current_period_start':now-60})
    invoice_id = 'in_fixture_'+authoritative['id']
    session['invoice'] = invoice_id
    session['created'] = now-120
    price = item['price']
    authoritative['latest_invoice'] = {'id':invoice_id,'object':'invoice',
        'status':'paid','customer':authoritative['customer'],'currency':'usd',
        'amount_due':price['unit_amount'],'amount_paid':price['unit_amount'],'amount_remaining':0,
        'status_transitions':{'paid_at':now-30},
        'parent':{'type':'subscription_details','subscription_details':{'subscription':authoritative['id']}},
        'lines':{'has_more':False,'data':[{'amount':price['unit_amount'],'currency':'usd','quantity':1,
            'parent':{'type':'subscription_item_details','subscription_item_details':{
                'subscription':authoritative['id'],'subscription_item':item['id'],'proration':False}},
            'pricing':{'type':'price_details','price_details':{'price':price['id']}},
            'period':{'start':item['current_period_start'],'end':item['current_period_end']}}]}}


def configure_paid_core_checkout(monkeypatch,settings,customer,session):
    if not customer.stripe_customer_id:
        customer.stripe_customer_id = 'cus_fixture_'+str(customer.user_id)
        customer.save(update_fields=['stripe_customer_id','updated_at'])
    founder = bool(session.get('metadata',{}).get('founder_slot_sequence'))
    price_id = 'price_fixture_core_founder' if founder else 'price_fixture_core_standard'
    if founder:
        settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = price_id
    if not founder:
        settings.STRIPE_CORE_STANDARD_PRICE_ID = price_id
    session.update({'mode':'subscription','status':'complete','payment_status':'paid',
                    'customer':customer.stripe_customer_id})
    session.setdefault('metadata',{}).update({'portfolio':'core','stewardence_user_id':str(customer.user_id)})
    authoritative = {'id':session['subscription'],'customer':customer.stripe_customer_id,
        'status':'active','metadata':dict(session['metadata']),
        'items':{'data':[{'quantity':1,'current_period_end':int((timezone.now()+timedelta(days=30)).timestamp()),
            'price':{'id':price_id,'active':True,'currency':'usd','unit_amount':4900 if founder else 9900,
                     'recurring':{'interval':'month','interval_count':1,'usage_type':'licensed'}}}]}}
    attach_paid_invoice(session, authoritative)
    monkeypatch.setattr('apps.billing.views._retrieve_core_subscription',lambda external_id:authoritative)
    return authoritative
