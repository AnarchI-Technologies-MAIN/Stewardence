"""Owner journey route tests; SQL role authority has separate qualifications."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest
from conftest import _roi_inputs
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connections
from django.http import Http404
from django.test import Client, RequestFactory
from django.urls import resolve, reverse
from django.utils import timezone

from apps.assessments.snapshots import create_assessment_snapshot
from apps.jobs.contracts import BranchProfile, Operation, WorkflowRequest
from apps.jobs.core_models import (
    ActionCardRevision,
    DecisionDeskGate,
    DecisionEvent,
    WorkflowRun,
)
from apps.jobs.core_workflows import dispatch
from apps.organizations.models import Organization, OrganizationMember, WorkflowProfile
from apps.reviews.models import (
    ArtifactRequest,
    CaptureProposalAdmissionReceipt,
    PackIdentity,
    ReviewCycle,
    ReviewLifecycleGate,
)

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def workspace(report_context, settings, client, monkeypatch, _identity_mode=None):
    user, org, _, _, snapshot = report_context
    WorkflowProfile.objects.get_or_create(
        organization=org,
        defaults={
            "created_by": user,
            "profile": "business.v1",
            "settings": {"name": "Owner journey"},
        },
    )
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    settings.CORE_WORKFLOWS_ENABLED = True
    settings.DECISION_DESK_ENABLED = True
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = False
    DecisionDeskGate.objects.update_or_create(id=1, defaults={"enabled": True})
    from apps.reviews import views

    original = views.dispatch
    failures = []
    observations = []
    from review_identity_diagnostics import observer

    def diagnosed(*args, **kwargs):
        try:
            with connections["default"].execute_wrapper(observer(observations)):
                return original(*args, **kwargs)
        except Exception as error:
            failures.append((type(error).__name__, str(error).splitlines()[0]))
            raise

    monkeypatch.setattr(views, "dispatch", diagnosed)
    result = client.post(reverse("reviews:issue-proposals", args=[snapshot.id]))
    assert result.status_code == 302, {
        "failures": failures,
        "observations": observations,
        "issuer_mode": _identity_mode or {"mode": "canonical"},
    }
    revision = ActionCardRevision.objects.get(snapshot=snapshot)
    assert revision.cards
    return user, org, snapshot, revision


def statement(previous=None, **changes):
    values = {
        "event_kind": "disposition",
        "state": "act",
        "responsible_label": "Owner label",
        "notes": "First frozen rationale",
        "links": "https://example.invalid/evidence",
        "expected_previous_event": str(previous) if previous else "",
    }
    values.update(changes)
    return values


def decision_url(workspace):
    return reverse("reviews:decision", args=[workspace[3].id, 0])


def freeze_pack(client, workspace):
    response = client.post(
        reverse("reviews:freeze", args=[workspace[2].id]), {"cycle_id": str(uuid4())}
    )
    assert response.status_code == 302
    return PackIdentity.objects.get(cycle__input_snapshot=workspace[2])


def test_default_workspace_gate_unavailable_without_effects(
    report_context, settings, client
):
    settings.CORE_REVIEW_WORKSPACE_ENABLED = False
    response = client.get(reverse("reviews:history"))
    assert response.status_code == 503
    assert b"unavailable" in response.content
    assert response["Cache-Control"] == "private, no-store"
    assert not ReviewCycle.objects.exists()


@pytest.mark.parametrize("route", ["history", "snapshot", "decision", "comparison"])
def test_owner_only_read_surfaces_do_not_inherit_general_inventory_viewer_access(
    workspace, client, route
):
    viewer = get_user_model().objects.create_user("ui-viewer@example.invalid")
    OrganizationMember.objects.create(
        organization=workspace[1], user=viewer, role="viewer"
    )
    client.force_login(viewer)
    session = client.session
    session["active_organization_id"] = str(workspace[1].id)
    session.save()
    args = {
        "history": [],
        "snapshot": [workspace[2].id],
        "decision": [workspace[3].id, 0],
        "comparison": [],
    }[route]
    url = reverse("reviews:" + route, args=args)
    assert (
        client.get(url).status_code == 302
    )  # Billing preempts unpaid visitor before the view.
    request = RequestFactory().get(url)
    request.user = viewer
    request.organization_id = workspace[1].id
    match = resolve(url)
    with pytest.raises(PermissionDenied):
        match.func(request, **match.kwargs)
    assert not DecisionEvent.objects.exists()


def test_snapshot_get_is_dated_read_only_and_shows_unestablished_accounts(
    workspace, client
):
    before = (
        ActionCardRevision.objects.count(),
        DecisionEvent.objects.count(),
        ReviewCycle.objects.count(),
    )
    response = client.get(reverse("reviews:snapshot", args=[workspace[2].id]))
    assert response.status_code == 200
    assert (
        b"access_removal" in response.content and b"not_established" in response.content
    )
    assert b"Freeze this snapshot" in response.content
    assert response["Cache-Control"] == "private, no-store"
    assert before == (
        ActionCardRevision.objects.count(),
        DecisionEvent.objects.count(),
        ReviewCycle.objects.count(),
    )


def test_decision_post_appends_exact_binding_and_stale_retry_is_conflict(
    workspace, client
):
    url = decision_url(workspace)
    assert (
        client.post(url, statement(notes="<script>attempt()</script>")).status_code
        == 302
    )
    event = DecisionEvent.objects.get()
    assert event.revision_id == workspace[3].id and event.card_index == 0
    assert event.payload["resolution_verified"] is False
    stale = client.post(url, statement(state="decline"))
    assert stale.status_code == 409
    assert DecisionEvent.objects.count() == 1
    assert b"current evidence" in stale.content
    read = client.get(url)
    assert b"&lt;script&gt;attempt()&lt;/script&gt;" in read.content
    assert b"<script>attempt()" not in read.content


@pytest.mark.parametrize(
    "changes",
    [
        {"event_kind": "execution", "state": "act"},
        {"links": "http://example.invalid"},
        {"links": "https://user:secret@example.invalid"},
        {"state": "verified"},
        {"notes": "x" * 4097},
        {"expected_previous_event": "not-a-uuid"},
        {"responsible_label": "x" * 201},
    ],
)
def test_invalid_owner_form_never_issues(workspace, client, changes):
    response = client.post(decision_url(workspace), statement(**changes))
    assert response.status_code == 400
    assert not DecisionEvent.objects.exists()


def test_missing_decision_feature_is_explicitly_unavailable(
    workspace, client, settings
):
    settings.DECISION_DESK_ENABLED = False
    response = client.get(decision_url(workspace))
    assert (
        response.status_code == 200
        and b"Owner statement admission is unavailable" in response.content
    )
    assert client.post(decision_url(workspace), statement()).status_code == 503
    assert not DecisionEvent.objects.exists()


def test_foreign_snapshot_revision_and_pack_are_not_found(workspace, client):
    pack = freeze_pack(client, workspace)
    other = Organization.objects.create(name="Other owner workspace")
    OrganizationMember.objects.create(
        organization=other, user=workspace[0], role="owner"
    )
    session = client.session
    session["active_organization_id"] = str(other.id)
    session.save()
    for route, args in [
        ("snapshot", [workspace[2].id]),
        ("decision", [workspace[3].id, 0]),
        ("pack-detail", [pack.id]),
    ]:
        url = reverse("reviews:" + route, args=args)
        assert client.get(url).status_code in (
            302,
            404,
        )  # Middleware may preempt; neither path reveals the foreign record.
        request = RequestFactory().get(url)
        request.user = workspace[0]
        request.organization_id = other.id
        match = resolve(url)
        with pytest.raises(Http404):
            match.func(request, **match.kwargs)


def test_freeze_projects_exact_old_statement_without_requesting_pdf(workspace, client):
    assert client.post(decision_url(workspace), statement()).status_code == 302
    first = DecisionEvent.objects.get()
    pack = freeze_pack(client, workspace)
    assert not ArtifactRequest.objects.exists()
    assert (
        client.post(
            decision_url(workspace),
            statement(first.id, state="defer", notes="Later statement after freeze"),
        ).status_code
        == 302
    )
    response = client.get(reverse("reviews:pack-detail", args=[pack.id]))
    assert response.status_code == 200
    assert b"First frozen rationale" in response.content
    assert b"Later statement after freeze" not in response.content
    assert (
        str(first.id).encode() in response.content
        and pack.sha256.encode() in response.content
    )
    assert b"Private PDF preparation is unavailable" in response.content
    assert (
        client.post(reverse("reviews:request-artifact", args=[pack.id])).status_code
        == 503
    )
    assert not ArtifactRequest.objects.exists()


def test_explicit_artifact_request_queues_without_promoting_baseline_or_starting_worker(
    workspace, client, settings
):
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = True
    ReviewLifecycleGate.objects.update_or_create(id=1, defaults={"enabled": True})
    pack = freeze_pack(client, workspace)
    response = client.post(
        reverse("reviews:request-artifact", args=[pack.id]),
        {"promote_baseline": "true", "baseline_pack_id": str(uuid4())},
    )
    assert response.status_code == 302
    request = ArtifactRequest.objects.get()
    assert request.promote_baseline is False
    assert request.job.status == "queued"
    response = client.get(reverse("reviews:pack-detail", args=[pack.id]))
    assert b"Queue admission is not delivery" in response.content
    assert b"Download private frozen pack PDF" not in response.content


def test_database_denial_rolls_back_open_cycle_before_safe_response(
    workspace, client, monkeypatch
):
    def denied(**kwargs):
        raise DatabaseError("secret internal SQL detail")

    monkeypatch.setattr("apps.reviews.views.freeze_cycle", denied)
    response = client.post(
        reverse("reviews:freeze", args=[workspace[2].id]), {"cycle_id": str(uuid4())}
    )
    assert response.status_code == 409
    assert b"secret internal SQL" not in response.content
    assert not ReviewCycle.objects.exists() and not PackIdentity.objects.exists()
    assert client.get(reverse("reviews:history")).status_code == 200


@pytest.mark.parametrize(
    "method,route",
    [("get", "snapshot"), ("post", "freeze"), ("post", "issue-proposals")],
)
def test_corrupt_snapshot_is_withheld_before_any_admission(
    workspace, client, monkeypatch, method, route
):
    monkeypatch.setattr("apps.reviews.views.verify_snapshot", lambda snapshot: False)
    response = getattr(client, method)(
        reverse("reviews:" + route, args=[workspace[2].id])
    )
    assert response.status_code == 503
    assert b"withheld" in response.content
    assert not ReviewCycle.objects.exists() and not DecisionEvent.objects.exists()


def test_freeze_lost_redirect_replay_uses_one_cycle_pack_and_reservation(
    workspace, client
):
    from apps.reviews.models import CapacityReservation

    identity = str(uuid4())
    url = reverse("reviews:freeze", args=[workspace[2].id])
    first = client.post(url, {"cycle_id": identity})
    replay = client.post(url, {"cycle_id": identity})
    assert first.status_code == replay.status_code == 302
    assert first.url == replay.url
    assert (
        ReviewCycle.objects.count()
        == PackIdentity.objects.count()
        == CapacityReservation.objects.count()
        == 1
    )


def test_simultaneous_same_freeze_form_has_one_effect(workspace):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    from apps.reviews.models import CapacityReservation

    barrier = Barrier(2)
    identity = str(uuid4())
    url = reverse("reviews:freeze", args=[workspace[2].id])

    def submit(index):
        try:
            browser = Client()
            browser.force_login(workspace[0])
            session = browser.session
            session["active_organization_id"] = str(workspace[1].id)
            session.save()
            barrier.wait(timeout=20)
            response = browser.post(url, {"cycle_id": identity})
            return response.status_code, getattr(response, "url", None)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, [0, 1]))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == 302
    assert (
        ReviewCycle.objects.count()
        == PackIdentity.objects.count()
        == CapacityReservation.objects.count()
        == 1
    )


def test_reusing_freeze_identity_for_another_snapshot_is_denied(
    workspace, report_context, client
):
    identity = str(uuid4())
    original = workspace[2]
    assert (
        client.post(
            reverse("reviews:freeze", args=[original.id]), {"cycle_id": identity}
        ).status_code
        == 302
    )
    changed = create_assessment_snapshot(
        organization_id=workspace[1].id,
        created_by_id=workspace[0].id,
        assessed_item_id=report_context[3].id,
        roi_inputs=_roi_inputs(),
        captured_at=original.captured_at + timedelta(days=1),
        previous_snapshot=original,
    )
    response = client.post(
        reverse("reviews:freeze", args=[changed.id]), {"cycle_id": identity}
    )
    assert response.status_code == 409
    assert ReviewCycle.objects.count() == PackIdentity.objects.count() == 1


def test_freeze_identity_is_required_and_never_becomes_authority(workspace, client):
    url = reverse("reviews:freeze", args=[workspace[2].id])
    assert client.post(url).status_code == 400
    assert client.post(url, {"cycle_id": "not-a-uuid"}).status_code == 400
    assert not ReviewCycle.objects.exists()


def test_foreign_admitted_cycle_identity_cannot_be_replayed_into_this_workspace(
    workspace, client
):
    from conftest import grant_core_entitlement

    from apps.inventory.models import InventoryItem
    from apps.reviews.services import open_cycle

    owner = get_user_model().objects.create_user("foreign-cycle-owner@example.invalid")
    org = Organization.objects.create(name="Foreign paid owner")
    OrganizationMember.objects.create(organization=org, user=owner, role="owner")
    WorkflowProfile.objects.create(
        organization=org,
        created_by=owner,
        profile="business.v1",
        settings={"name": "Foreign owner meaning"},
    )
    grant_core_entitlement(owner, org)
    item = InventoryItem.objects.create(
        organization=org, display_name="Foreign workflow"
    )
    snapshot = create_assessment_snapshot(
        organization_id=org.id,
        created_by_id=owner.id,
        assessed_item_id=item.id,
        roi_inputs=_roi_inputs(),
        captured_at=workspace[2].captured_at,
    )
    foreign = open_cycle(
        organization_id=org.id, actor_id=owner.id, input_snapshot_id=snapshot.id
    )
    response = client.post(
        reverse("reviews:freeze", args=[workspace[2].id]), {"cycle_id": str(foreign.id)}
    )
    assert response.status_code == 409
    assert ReviewCycle.objects.count() == 1 and not PackIdentity.objects.exists()


def test_csrf_and_http_methods_preserve_no_effects(workspace):
    client = Client(enforce_csrf_checks=True)
    client.force_login(workspace[0])
    session = client.session
    session["active_organization_id"] = str(workspace[1].id)
    session.save()
    url = reverse("reviews:freeze", args=[workspace[2].id])
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 403
    assert not ReviewCycle.objects.exists()
    assert (
        client.get(reverse("reviews:snapshot", args=[workspace[2].id])).status_code
        == 200
    )
    token = client.cookies["csrftoken"].value
    assert (
        client.post(url, {"cycle_id": str(uuid4())}, HTTP_X_CSRFTOKEN=token).status_code
        == 302
    )


def test_user_selected_comparison_is_read_only_and_never_admits_a_baseline(
    workspace, report_context, client
):
    user, org, before, _ = workspace
    item = report_context[3]
    item.business_purpose = "Changed owner declaration"
    item.save(update_fields=["business_purpose"])
    after = create_assessment_snapshot(
        organization_id=org.id,
        created_by_id=user.id,
        assessed_item_id=item.id,
        roi_inputs=_roi_inputs(),
        captured_at=before.captured_at + timedelta(days=1),
        previous_snapshot=before,
    )
    response = client.get(
        reverse("reviews:comparison"),
        {"baseline": str(before.id), "current": str(after.id)},
    )
    assert response.status_code == 200
    assert (
        b"business_purpose" in response.content
        and b"not_established" in response.content
    )
    assert not ReviewCycle.objects.exists() and not PackIdentity.objects.exists()
    assert (
        client.get(
            reverse("reviews:comparison"),
            {"baseline": str(after.id), "current": str(before.id)},
        ).status_code
        == 400
    )
    other = Organization.objects.create(name="Foreign snapshot workspace")
    from apps.inventory.models import InventoryItem

    foreign_item = InventoryItem.objects.create(
        organization=other, display_name="Foreign captured tool"
    )
    foreign_snapshot = create_assessment_snapshot(
        organization_id=other.id,
        created_by_id=user.id,
        assessed_item_id=foreign_item.id,
        roi_inputs=_roi_inputs(),
        captured_at=before.captured_at,
    )
    assert (
        client.get(
            reverse("reviews:comparison"),
            {"baseline": str(foreign_snapshot.id), "current": str(after.id)},
        ).status_code
        == 400
    )


@pytest.mark.parametrize("width", [390, 1280])
def test_real_browser_owner_pages_reuse_atlas_without_overflow_or_active_evidence_links(
    workspace, client, width
):
    from pathlib import Path

    from django.conf import settings
    from playwright.sync_api import sync_playwright

    assert (
        client.post(
            decision_url(workspace),
            statement(
                notes="x" * 4096,
                responsible_label="r" * 200,
                links="https://example.invalid/" + "e" * 1500,
            ),
        ).status_code
        == 302
    )
    pack = freeze_pack(client, workspace)
    routes = [
        reverse("reviews:history"),
        reverse("reviews:snapshot", args=[workspace[2].id]),
        decision_url(workspace),
        reverse("reviews:pack-detail", args=[pack.id]),
        reverse("reviews:comparison"),
    ]
    css = "\n".join(
        (Path(settings.BASE_DIR) / "static" / name).read_text(encoding="utf-8")
        for name in ("agentledger.css", "atlas.css")
    )
    rendered = []
    for url in routes:
        response = client.get(url)
        assert response.status_code == 200
        rendered.append((url, response.content.decode("utf-8")))
    event_id = str(DecisionEvent.objects.get().id)
    with sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, chromium_sandbox=False)
        context = browser.new_context(
            viewport={"width": width, "height": 900}, reduced_motion="reduce"
        )
        context.route("**/*", lambda route: route.abort())
        page = context.new_page()
        for url, html in rendered:
            page.set_content(html, wait_until="load")
            page.add_style_tag(content=css)
            assert page.locator("main h1").count() == 1
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            ), url
            assert page.locator('a[href^="https://example.invalid"]').count() == 0
            if url == decision_url(workspace):
                page.locator("#id_responsible_label").focus()
                assert (
                    page.evaluate("document.activeElement.id") == "id_responsible_label"
                )
                assert (
                    page.locator('input[name="expected_previous_event"]').input_value()
                    == event_id
                )
        context.close()
        browser.close()


def test_repeated_synthetic_proposal_inputs_preserve_all_sql_identity_predicates(
    workspace, client, diagnostic_repeat=None
):
    from review_identity_diagnostics import observer

    url = reverse("reviews:issue-proposals", args=[workspace[2].id])
    failures = []

    def effect_counts():
        return {
            "workflow_run": WorkflowRun.objects.filter(
                organization_id=workspace[1].id,
                operation=Operation.REASSESS.value,
            ).count(),
            "revision": ActionCardRevision.objects.filter(
                snapshot_id=workspace[2].id
            ).count(),
            "proposal_receipt": CaptureProposalAdmissionReceipt.objects.filter(
                snapshot_id=workspace[2].id
            ).count(),
        }

    for index in range(128):
        observed = []
        before = effect_counts() if diagnostic_repeat is not None else None
        with connections["default"].execute_wrapper(observer(observed)):
            response = client.post(url)
        assert observed
        if diagnostic_repeat is not None:
            after = effect_counts()
            record = dict(observed[-1])
            record.update(
                diagnostic_batch=diagnostic_repeat,
                diagnostic_attempt=index,
                http_status=response.status_code,
                effects_before=before,
                effects_after=after,
                effects_delta={key: after[key] - before[key] for key in before},
                result="accepted" if response.status_code == 302 else "denied",
            )
            print(
                "SYNTHETIC_IDENTITY_TRACE " + json.dumps(record, sort_keys=True),
                flush=True,
            )
            if response.status_code != 302 or any(
                value is not False for value in record["predicates"].values()
            ):
                failures.append(record)
            continue
        assert response.status_code == 302, {
            "index": index,
            "status": response.status_code,
            "observed": observed,
        }
        assert observed
        assert all(value is False for value in observed[-1]["predicates"].values()), (
            observed
        )
    assert not failures, {
        "diagnostic_batch": diagnostic_repeat,
        "failure_count": len(failures),
        "first_failures": failures[:3],
    }


def test_explicit_future_proposal_request_remains_denied_without_new_issuance(
    workspace,
):
    count = WorkflowRun.objects.count()
    request = WorkflowRequest(
        organization_id=workspace[1].id,
        operation=Operation.REASSESS,
        receipt_ids=(workspace[2].id,),
        effective_at=timezone.now() + timedelta(days=1),
        branch_profile=BranchProfile.BUSINESS,
    )
    with pytest.raises(ValidationError, match="Future dispatch is not admitted"):
        dispatch(request, actor_id=workspace[0].id)
    assert WorkflowRun.objects.count() == count
