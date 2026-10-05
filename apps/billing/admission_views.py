import stripe
from django.http import HttpResponse
from django.db import DatabaseError
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .admission import AdmissionConfigurationError, configuration, ingest_verified_event
from .paid_evidence import UnsupportedPaidEvidence


@csrf_exempt
@require_POST
def paid_webhook(request):
    try:
        secret, key, account, mode = configuration()
    except AdmissionConfigurationError:
        return HttpResponse(status=503)
    body = request.body
    if len(body) > 512 * 1024:
        return HttpResponse(status=413)
    try:
        event = stripe.Webhook.construct_event(
            body, request.headers.get("Stripe-Signature", ""), secret
        )
        if isinstance(event, stripe.StripeObject):
            event = event.to_dict()
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)
    try:
        ingest_verified_event(event, body, key=key, account_id=account, livemode=mode)
    except AdmissionConfigurationError:
        return HttpResponse(status=503)
    except (UnsupportedPaidEvidence, ValueError):
        return HttpResponse(status=422)
    except (stripe.StripeError, DatabaseError):
        return HttpResponse(status=503)
    return HttpResponse(status=200)
