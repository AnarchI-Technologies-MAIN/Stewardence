from types import SimpleNamespace
import pytest
from django.http import Http404
from django.test import RequestFactory
from apps.funnels.views import experience, bundle_json


def request(staff=False, superuser=False, authenticated=False, method="get"):
    result = getattr(RequestFactory(), method)("/explore/preview/tool-exposure/")
    result.user = SimpleNamespace(is_staff=staff, is_superuser=superuser, is_authenticated=authenticated)
    return result


def test_preview_closed_by_default_even_for_operator(settings):
    settings.FUNNEL_PREVIEW_ENABLED = False
    with pytest.raises(Http404):
        experience(request(True,True,True), "tool-exposure", preview=True)


@pytest.mark.parametrize("staff,superuser,authenticated", [(False,False,False),(True,False,True),(False,True,True)])
def test_preview_does_not_admit_ordinary_or_partial_operator(settings,staff,superuser,authenticated):
    settings.FUNNEL_PREVIEW_ENABLED = True
    settings.DEBUG = False
    with pytest.raises(Http404):
        experience(request(staff,superuser,authenticated), "tool-exposure", preview=True)


def test_operator_preview_explicit_proposed_no_store_and_no_price(settings):
    settings.FUNNEL_PREVIEW_ENABLED = True
    settings.DEBUG = False
    req = request(True,True,True)
    response = experience(req,"tool-exposure",preview=True)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert "noindex" in response["X-Robots-Tag"]
    assert response["Referrer-Policy"] == "no-referrer"
    assert "connect-src 'none'" in response["Content-Security-Policy"]
    assert b"proposed Core toolbelt" in response.content
    assert b"Synthetic educational sample" in response.content
    assert b"Nothing is saved or submitted" in response.content
    assert b"Checkout unavailable in this draft preview" in response.content
    assert b"/billing/portfolio/" not in response.content
    assert b'id="scenario-data"' in response.content
    data = bundle_json(req,"tool-exposure").content
    assert b"core.standard.monthly.v1" in data
    assert b"price_id" not in data


def test_draft_public_access_remains_closed_regardless_preview_flag(settings):
    settings.FUNNEL_PREVIEW_ENABLED = True
    with pytest.raises(Http404):
        experience(request(True,True,True),"tool-exposure")


def test_no_post_collection_endpoint(settings):
    settings.FUNNEL_PREVIEW_ENABLED = True
    assert experience(request(True,True,True,"post"),"tool-exposure",preview=True).status_code == 405


def test_actual_urlconf_resolves_only_get_views():
    from django.urls import resolve
    preview = resolve("/preview/tool-exposure/", urlconf="apps.funnels.urls")
    assert preview.func is experience
    assert preview.kwargs == {"scenario": "tool-exposure", "preview": True}
    assert resolve("/bundle/tool-exposure.json", urlconf="apps.funnels.urls").func is bundle_json
