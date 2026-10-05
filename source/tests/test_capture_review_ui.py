"""Owner-visible reviewed capture, separately from SQL-role qualifications."""

import time
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.test import Client, RequestFactory
from django.urls import resolve, reverse

from apps.assessments.models import (
    AssessmentSnapshot,
    CaptureAdmissionGate,
    SnapshotCaptureReceipt,
)
from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryItem
from apps.jobs.core_models import ActionCardRevision, DecisionEvent
from apps.jobs.models import BackgroundJob
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.models import Report
from apps.reviews.capture_views import PREVIEW_MAX_AGE, PREVIEW_SALT
from apps.reviews.models import ArtifactRequest, PackIdentity, ReviewCycle
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_explicit_inventory import form, issue

__all__ = ["explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def capture_ui(explicit_context, settings):
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    settings.DELIBERATE_CAPTURE_ENABLED = True
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = False
    CaptureAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    item = issue(explicit_context)
    return (*explicit_context, item)


def effects():
    return {
        model.__name__: model.objects.count()
        for model in (
            AssessmentSnapshot,
            SnapshotCaptureReceipt,
            InventoryItem,
            ActionCardRevision,
            DecisionEvent,
            BackgroundJob,
            Report,
            ReviewCycle,
            PackIdentity,
            ArtifactRequest,
            AuditEvent,
        )
    }


def preview(client):
    response = client.get(reverse("reviews:capture"))
    assert response.status_code == 200, response.content.decode()
    token = response.context["form"].initial["preview_token"]
    frame = signing.loads(token, salt=PREVIEW_SALT, max_age=PREVIEW_MAX_AGE)
    return response, token, frame


def confirm(client, token, **changes):
    return client.post(
        reverse("reviews:capture"), {"preview_token": token, "confirm": "on", **changes}
    )


def test_owner_preview_is_private_read_only_and_explicitly_not_a_benefit_model(
    capture_ui, client
):
    before = effects()
    response, _, frame = preview(client)
    assert effects() == before
    assert response["Cache-Control"] == "private, no-store"
    assert frame["organization_id"] == str(capture_ui[1].id)
    assert frame["actor_id"] == str(capture_ui[0].id)
    assert len(frame["inventory_records"]) == 1
    assert frame["inventory_records"][0]["id"] == str(capture_ui[2].id)
    assert frame["legacy_active_count"] >= 1
    assert b"No benefit model is supplied" in response.content
    assert (
        b"does not verify controls, measure benefits or generate a PDF"
        in response.content
    )
    assert b"not silently promoted" in response.content


def test_signed_owner_confirmation_admits_schema_two_without_roi_or_downstream_work(
    capture_ui, client, monkeypatch
):
    def no_roi(*args, **kwargs):
        raise AssertionError("Deliberate capture must not run a benefit calculator")

    monkeypatch.setattr("apps.roi.engine_v2.calculate_roi", no_roi)
    before = effects()
    _, token, frame = preview(client)
    response = confirm(client, token)
    assert response.status_code == 302, response.content.decode()
    snapshot = AssessmentSnapshot.objects.get(id=UUID(frame["capture_id"]))
    assert response.url == reverse("reviews:snapshot", args=[snapshot.id])
    assert snapshot.organization_id == capture_ui[1].id
    assert snapshot.created_by_id == capture_ui[0].id
    assert snapshot.input_payload["snapshot_schema_version"] == 2
    assert snapshot.result_payload["snapshot_schema_version"] == 2
    assert snapshot.input_payload["benefit_model"] == {"state": "not_supplied"}
    assert snapshot.result_payload["benefit_model"] == {"state": "not_supplied"}
    assert "roi" not in snapshot.input_payload and "roi" not in snapshot.result_payload
    receipt = SnapshotCaptureReceipt.objects.get(snapshot=snapshot)
    assert receipt.reviewed_frame == frame
    after = effects()
    assert after["AssessmentSnapshot"] == before["AssessmentSnapshot"] + 1
    assert after["SnapshotCaptureReceipt"] == before["SnapshotCaptureReceipt"] + 1
    for model in set(before) - {"AssessmentSnapshot", "SnapshotCaptureReceipt"}:
        assert after[model] == before[model], model
    shown = client.get(response.url)
    assert shown.status_code == 200
    assert b"Review captured exposure" in shown.content
    assert b"UNKNOWN" in shown.content
    assert (
        b"Freezing and PDF delivery for this capture format are unavailable"
        in shown.content
    )
    assert reverse("reviews:freeze", args=[snapshot.id]).encode() not in shown.content
    assert (
        reverse("reviews:issue-proposals", args=[snapshot.id]).encode()
        not in shown.content
    )
    assert b"Monthly net value" not in shown.content and b"ROI:" not in shown.content
    assert effects() == after


def test_same_signed_retry_returns_exact_committed_capture_after_inventory_changes(
    capture_ui, client
):
    _, token, frame = preview(client)
    first = confirm(client, token)
    assert first.status_code == 302
    original = AssessmentSnapshot.objects.get(id=UUID(frame["capture_id"]))
    original_inputs, original_results = (
        deepcopy(original.input_payload),
        deepcopy(original.result_payload),
    )
    issue(
        capture_ui[:2],
        form(display_name="Changed after committed capture"),
        item_id=capture_ui[2].id,
    )
    before_retry = effects()
    retry = confirm(client, token)
    assert retry.status_code == 302 and retry.url == first.url
    assert effects() == before_retry
    original.refresh_from_db()
    assert (
        original.input_payload == original_inputs
        and original.result_payload == original_results
    )
    assert SnapshotCaptureReceipt.objects.filter(snapshot=original).count() == 1


def test_changed_inventory_before_confirmation_is_conflict_with_no_capture(
    capture_ui, client
):
    _, token, _ = preview(client)
    issue(
        capture_ui[:2],
        form(display_name="Changed before confirmation"),
        item_id=capture_ui[2].id,
    )
    before = effects()
    response = confirm(client, token)
    assert response.status_code == 409
    assert b"could not be admitted" in response.content
    assert effects() == before
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(
    "variant",
    ["tampered", "foreign_org", "foreign_actor", "expired", "malformed_signed"],
)
def test_bad_preview_tokens_have_no_domain_effects(
    capture_ui, client, monkeypatch, variant
):
    _, token, frame = preview(client)
    if variant == "tampered":
        token = token[:-1] + ("A" if token[-1] != "A" else "B")
    if variant == "foreign_org":
        foreign = Organization.objects.create(name="Foreign capture firm")
        frame["organization_id"] = str(foreign.id)
        token = signing.dumps(frame, salt=PREVIEW_SALT, compress=True)
    if variant == "foreign_actor":
        frame["actor_id"] = str(uuid4())
        token = signing.dumps(frame, salt=PREVIEW_SALT, compress=True)
    if variant == "expired":
        with monkeypatch.context() as patch:
            patch.setattr(
                signing.TimestampSigner,
                "timestamp",
                lambda self: signing.b62_encode(
                    int(time.time()) - PREVIEW_MAX_AGE - 60
                ),
            )
            token = signing.dumps(frame, salt=PREVIEW_SALT, compress=True)
    if variant == "malformed_signed":
        del frame["inventory_records"]
        token = signing.dumps(frame, salt=PREVIEW_SALT, compress=True)
    before = effects()
    response = confirm(client, token)
    assert response.status_code == (409 if variant == "malformed_signed" else 400)
    assert effects() == before
    assert response["Cache-Control"] == "private, no-store"


def test_confirmation_requires_deliberate_checkbox_and_csrf(capture_ui, client):
    _, token, _ = preview(client)
    before = effects()
    response = confirm(client, token, confirm="")
    assert response.status_code == 400
    assert effects() == before
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(capture_ui[0])
    session = strict.session
    session["active_organization_id"] = str(capture_ui[1].id)
    session.save()
    response = confirm(strict, token)
    assert response.status_code == 403
    assert effects() == before
    page = strict.get(reverse("reviews:capture"))
    assert page.status_code == 200
    fresh_token = page.context["form"].initial["preview_token"]
    response = strict.post(
        reverse("reviews:capture"),
        {"preview_token": fresh_token, "confirm": "on"},
        HTTP_X_CSRFTOKEN=strict.cookies["csrftoken"].value,
    )
    assert response.status_code == 302


def test_preview_and_snapshot_distinguish_unknown_none_no_and_zero(capture_ui, client):
    known = issue(
        capture_ui[:2],
        form(
            display_name="Deliberately answered tool",
            monthly_cost="0.00",
            user_count="0",
            human_approval="no",
            permissions=["__none__"],
            capabilities=["__none__"],
        ),
    )
    response, token, frame = preview(client)
    rows = {
        record["name"]: {field["label"]: field for field in record["fields"]}
        for record in response.context["records"]
    }
    assert rows["Workflow helper"]["Monthly cost cents"]["display"] == "Unknown"
    assert rows["Workflow helper"]["Human approval"]["display"] == "Unknown"
    assert rows[known.display_name]["Monthly cost cents"]["display"] == "0"
    assert rows[known.display_name]["Human approval"]["display"] == "No"
    assert rows[known.display_name]["Permissions"]["display"] == "None declared"
    saved = confirm(client, token)
    assert saved.status_code == 302
    snapshot = AssessmentSnapshot.objects.get(id=UUID(frame["capture_id"]))
    records = {record["id"]: record for record in snapshot.input_payload["inventory"]}
    unknown = records[str(capture_ui[2].id)]
    declared = records[str(known.id)]
    assert (
        unknown["monthly_cost_cents"] is None
        and unknown["permissions"] is None
        and unknown["human_approval"] is None
    )
    assert (
        declared["monthly_cost_cents"] == 0
        and declared["permissions"] == []
        and declared["human_approval"] is False
    )
    assert unknown["provenance"]["permissions"] == "Unknown"
    assert declared["provenance"]["permissions"] == "Declared"


@pytest.mark.parametrize("gate", ["workspace", "application", "operator"])
def test_closed_gates_deny_preview_and_confirmation_without_effects(
    capture_ui, client, settings, gate
):
    _, token, _ = preview(client)
    if gate == "workspace":
        settings.CORE_REVIEW_WORKSPACE_ENABLED = False
    if gate == "application":
        settings.DELIBERATE_CAPTURE_ENABLED = False
    if gate == "operator":
        CaptureAdmissionGate.objects.filter(id=1).update(enabled=False)
    before = effects()
    expected = 409 if gate == "operator" else 503
    assert client.get(reverse("reviews:capture")).status_code == expected
    assert confirm(client, token).status_code == expected
    assert effects() == before


def test_same_tenant_viewer_cannot_preview_or_confirm_capture(capture_ui, client):
    _, token, _ = preview(client)
    viewer = get_user_model().objects.create_user("capture-viewer@example.invalid")
    OrganizationMember.objects.create(
        organization=capture_ui[1], user=viewer, role="viewer"
    )
    client.force_login(viewer)
    session = client.session
    session["active_organization_id"] = str(capture_ui[1].id)
    session.save()
    before = effects()
    url = reverse("reviews:capture")
    assert client.get(url).status_code in (302, 403)
    assert confirm(client, token).status_code in (302, 403)
    request = RequestFactory().get(url)
    request.user, request.organization_id = viewer, capture_ui[1].id
    with pytest.raises(PermissionDenied):
        resolve(url).func(request)
    assert effects() == before


@pytest.mark.parametrize("width", [390, 1280])
def test_real_browser_preview_is_readable_keyboard_confirmable_and_network_quiet(
    capture_ui, client, width
):
    from playwright.sync_api import sync_playwright

    issue(
        capture_ui[:2],
        form(
            display_name="<script>untrusted label</script>",
            business_purpose="x" * 4096,
            permissions=["__none__"],
        ),
    )
    before = effects()
    response, token, _ = preview(client)
    html = response.content.decode()
    css = "\n".join(
        (Path(django_settings.BASE_DIR) / "static" / name).read_text(encoding="utf-8")
        for name in ("agentledger.css", "atlas.css")
    )
    assert effects() == before
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        context = browser.new_context(
            viewport={"width": width, "height": 900}, reduced_motion="reduce"
        )
        page = context.new_page()
        requests = []
        page.on("request", lambda request: requests.append(request.url))
        page.route("**/*", lambda route: route.abort())
        page.set_content(html, wait_until="load")
        page.add_style_tag(content=css)
        assert page.locator("main h1").inner_text() == "Review before saving"
        assert page.locator("main script").count() == 0
        assert (
            page.locator("main h2")
            .filter(has_text="<script>untrusted label</script>")
            .count()
            == 1
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator('input[name="preview_token"]').input_value() == token
        checkbox = page.locator('input[name="confirm"]')
        assert not checkbox.is_checked()
        checkbox.focus()
        page.keyboard.press("Space")
        assert checkbox.is_checked()
        assert not requests
        context.close()
        browser.close()
    assert effects() == before


def test_missing_issuance_receipt_withholds_saved_capture_content(capture_ui, client):
    _, token, _ = preview(client)
    saved = confirm(client, token)
    assert saved.status_code == 302
    # Privileged disposable-fixture corruption, not an application-role exploit.
    # TRUNCATE leaves every immutable trigger and grant intact.
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "TRUNCATE review_capture_proposal_receipts, assessment_capture_receipts"
        )
    assert SnapshotCaptureReceipt.objects.count() == 0
    before = effects()
    shown = client.get(saved.url)
    assert shown.status_code == 503
    assert b"Content is withheld" in shown.content
    assert b"Workflow helper" not in shown.content
    assert effects() == before


def test_schema_two_legacy_assessment_link_returns_to_qualified_owner_review(
    capture_ui, client
):
    _, token, frame = preview(client)
    saved = confirm(client, token)
    assert saved.status_code == 302
    before = effects()
    legacy = client.get(reverse("assessments:detail", args=[frame["capture_id"]]))
    assert legacy.status_code == 302
    assert legacy.url == saved.url
    shown = client.get(legacy.url)
    assert shown.status_code == 200
    assert b"Open browser report" not in shown.content
    assert effects() == before


def test_direct_legacy_report_post_cannot_stage_schema_two_report_or_job(
    capture_ui, client
):
    _, token, frame = preview(client)
    assert confirm(client, token).status_code == 302
    before = effects()
    response = client.post(reverse("reports:generate", args=[frame["capture_id"]]))
    assert response.status_code == 409
    assert response["Cache-Control"] == "private, no-store"
    assert effects() == before


def test_direct_schema_two_proposals_stay_closed_with_legacy_flag_enabled(
    capture_ui, client, settings, monkeypatch
):
    _, token, frame = preview(client)
    assert confirm(client, token).status_code == 302
    settings.CORE_WORKFLOWS_ENABLED = True
    called = []

    def forbidden_dispatch(*args, **kwargs):
        called.append(True)
        raise AssertionError("Schema-two proposal adapter is not qualified")

    monkeypatch.setattr("apps.reviews.views.dispatch", forbidden_dispatch)
    before = effects()
    response = client.post(
        reverse("reviews:issue-proposals", args=[frame["capture_id"]])
    )
    assert response.status_code == 503
    assert response["Cache-Control"] == "private, no-store"
    assert not called
    assert effects() == before
