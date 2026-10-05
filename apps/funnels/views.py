from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .contracts import REGISTRY, admission, audience_choice, scenario_sample, AUDIENCE_CONTEXT


def _resolve(request, scenario, preview):
    bundle = REGISTRY.get(scenario)
    if bundle is None or request.GET.get("locale", "en") != "en":
        raise Http404
    if preview:
        user = request.user
        developer = settings.DEBUG and getattr(settings, "FUNNEL_DEVELOPMENT_PREVIEW", False)
        operator = user.is_authenticated and user.is_staff and user.is_superuser
        if not getattr(settings, "FUNNEL_PREVIEW_ENABLED", False) or not (developer or operator):
            raise Http404
    elif not getattr(settings, "FUNNEL_PUBLIC_ENABLED", False) or not admission(bundle,
        qualified_capabilities=getattr(settings, "FUNNEL_QUALIFIED_CAPABILITIES", ()),
        approved_digests=getattr(settings, "FUNNEL_APPROVED_DIGESTS", ())):
        raise Http404
    return bundle


def _private(response):
    response["Cache-Control"] = "private, no-store"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Referrer-Policy"] = "no-referrer"
    response["Content-Security-Policy"] = "default-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    return response


@require_GET
def experience(request, scenario, preview=False):
    bundle = _resolve(request, scenario, preview)
    audience = audience_choice(request.GET.get("audience"), request.GET.get("campaign_audience"))
    return _private(render(request, "funnels/experience.html", {
        "bundle": bundle, "preview": preview,
        "audience": audience, "audience_context": AUDIENCE_CONTEXT[audience],
        "sample": scenario_sample(bundle),
    }))


@require_GET
def bundle_json(request, scenario):
    bundle = _resolve(request, scenario, True)
    return _private(JsonResponse({"bundle": bundle.payload(), "sha256": bundle.digest}))
