"""CORE-CHECKOUT-COVERAGE-1: narrow current Stripe invoice read-shape admission.

Provider-observed invoice settlement state, not proof of bank finality. Unknown
shapes, prorations, multiple lines and incomplete pagination require review.
"""
from django.utils import timezone


def require_checkout_coverage(session, subscription, contract):
    def denied():
        raise RuntimeError('Core checkout payment does not cover the admitted service period.')

    item = subscription['items']['data'][0]
    invoice = subscription.get('latest_invoice')
    if not isinstance(invoice, dict):
        denied()
    lines = invoice.get('lines')
    parent = invoice.get('parent')
    transitions = invoice.get('status_transitions')
    if not all(isinstance(value, dict) for value in [lines, parent, transitions]):
        denied()
    data = lines.get('data')
    details = parent.get('subscription_details')
    if (parent.get('type') != 'subscription_details' or not isinstance(details, dict)
            or type(data) is not list or len(data) != 1 or lines.get('has_more') is not False):
        denied()
    line = data[0]
    if not isinstance(line, dict):
        denied()
    line_parent, pricing, period = (line.get(key) for key in ['parent', 'pricing', 'period'])
    if not all(isinstance(value, dict) for value in [line_parent, pricing, period]):
        denied()
    line_details = line_parent.get('subscription_item_details')
    price_details = pricing.get('price_details')
    if not isinstance(line_details, dict) or not isinstance(price_details, dict):
        denied()
    item_id = item.get('id')
    line_item_id = line_details.get('subscription_item')
    if (type(item_id) is not str or not item_id
            or type(line_item_id) is not str or not line_item_id):
        denied()
    # Current line projections may omit these fields; invoice is nullable.
    # A supplied non-null identity must agree, and an explicit object kind
    # must be the supported discriminator. No identity coercion is admitted.
    line_invoice = line.get('invoice')
    if (line_invoice is not None and (type(line_invoice) is not str
                                     or line_invoice != invoice.get('id'))):
        denied()
    if 'object' in line and line['object'] != 'line_item':
        denied()
    for alias in ['current_period_start', 'current_period_end']:
        value = subscription.get(alias)
        if value is not None and type(value) is not int:
            denied()
    now = int(timezone.now().timestamp())
    start = item.get('current_period_start', subscription.get('current_period_start'))
    end = item.get('current_period_end', subscription.get('current_period_end'))
    paid_at = transitions.get('paid_at')
    created = session.get('created')
    numeric = [start, end, paid_at, created, invoice.get('amount_due'),
               invoice.get('amount_paid'), invoice.get('amount_remaining'),
               line.get('amount'), line.get('quantity')]
    if not all(type(value) is int for value in numeric):
        denied()
    if (not isinstance(invoice.get('id'), str) or not invoice['id']
            or session.get('invoice') != invoice['id'] or invoice.get('object') != 'invoice'
            or invoice.get('status') != 'paid' or invoice.get('currency') != 'usd'
            or invoice.get('customer') != subscription['customer']
            or details.get('subscription') != subscription['id']
            or invoice['amount_due'] < contract.cents
            or invoice['amount_paid'] != invoice['amount_due'] or invoice['amount_remaining'] != 0
            or line_parent.get('type') != 'subscription_item_details'
            or line_details.get('subscription') != subscription['id']
            or line_item_id != item_id
            or line_details.get('proration') is not False
            or pricing.get('type') != 'price_details'
            or price_details.get('price') != item['price']['id']
            or line.get('currency') != 'usd' or line['amount'] != contract.cents
            or line['quantity'] != 1 or period.get('start') != start or period.get('end') != end
            or type(period.get('start')) is not int or type(period.get('end')) is not int
            or not (0 < start <= paid_at <= now < end) or not (0 < created <= paid_at)
            or end-start > 32*86400
            or (subscription.get('current_period_start') is not None
                and subscription['current_period_start'] != start)):
        denied()
