"""Owner HTTP proposals with real app-role RLS and strict CSRF; gates fixture-only."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client
from django.urls import reverse

from apps.assessments.models import AssessmentSnapshot
from apps.jobs.core_models import ActionCardRevision, DecisionEvent
from apps.organizations.models import Organization, OrganizationMember
from apps.reviews.models import CaptureProposalAdmissionReceipt
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_capture_decisions import (
    capture_decision_context as capture_decision_context,
)
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["capture_context", "capture_decision_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def owner_client(context, settings):
    owner, org = context[:2]
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    settings.ALLOWED_HOSTS = ["testserver"]
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    return client


def effects():
    return tuple(
        model.objects.count()
        for model in (
            AssessmentSnapshot,
            ActionCardRevision,
            CaptureProposalAdmissionReceipt,
            DecisionEvent,
        )
    )


def post(client, route, fields):
    return client.post(
        route,
        {
            **fields,
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        },
    )


def statement(**changes):
    return {
        "event_kind": "disposition",
        "state": "act",
        "responsible_label": "Owner",
        "notes": "Owner rationale",
        "links": "https://example.invalid/evidence",
        "expected_previous_event": "",
        **changes,
    }


def route(context):
    return reverse("reviews:decision", args=[context[3].id, 0])


def test_get_is_read_only_and_proposal_post_replays_one_exact_issuance(
    capture_context, settings, monkeypatch
):
    from apps.reviews.models import CoreProposalAdmissionGate

    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    snapshot = admit(capture_context, preview(capture_context))
    client = owner_client(capture_context, settings)
    before = effects()

    def legacy_forbidden(*args, **kwargs):
        pytest.fail("Capture proposal route reached legacy workflow issuer")

    monkeypatch.setattr("apps.reviews.views.dispatch", legacy_forbidden)
    get_route = reverse("reviews:snapshot", args=[snapshot.id])
    issue_route = reverse("reviews:issue-proposals", args=[snapshot.id])
    with actual_app_default():
        page = client.get(get_route)
        assert page.status_code == 200, page.content.decode()
        assert issue_route in page.content.decode()
    assert effects() == before
    with actual_app_default():
        assert post(client, issue_route, {}).status_code == 302
    revision = ActionCardRevision.objects.get(snapshot=snapshot)
    receipt = CaptureProposalAdmissionReceipt.objects.get(revision=revision)
    assert receipt.snapshot_id == receipt.capture_receipt_id == snapshot.id
    issued = effects()
    with actual_app_default():
        assert post(client, issue_route, {}).status_code == 302
        page = client.get(get_route)
    assert effects() == issued
    assert b"Selected review items and evidence requests" in page.content
    assert ActionCardRevision.objects.get(snapshot=snapshot).id == revision.id


def test_owner_statements_use_server_exact_proposal_and_keep_unknown(
    capture_decision_context, settings, monkeypatch
):
    context = capture_decision_context
    client = owner_client(context, settings)
    original_cards, original_results = context[3].cards, context[2].result_payload

    def legacy_forbidden(*args, **kwargs):
        pytest.fail("Capture owner statement reached legacy decision issuer")

    monkeypatch.setattr("apps.reviews.views.record_decision", legacy_forbidden)
    before = effects()
    with actual_app_default():
        page = client.get(route(context))
    assert page.status_code == 200
    assert effects() == before
    previous = ""
    for kind, state in (
        ("disposition", "act"),
        ("execution", "completion_recorded"),
        ("execution", "evidence_reviewed"),
    ):
        with actual_app_default():
            response = post(
                client,
                route(context),
                statement(
                    event_kind=kind,
                    state=state,
                    expected_previous_event=previous,
                    proposal_id=str(uuid4()),
                    proposal_sha256="a" * 64,
                    original_outcome="PASS",
                    resolution_verified="true",
                ),
            )
        assert response.status_code == 302, response.content.decode()
        event = DecisionEvent.objects.order_by("-sequence").first()
        assert event.payload["proposal_id"] == original_cards[0]["proposal_id"]
        assert event.payload["proposal_sha256"] == original_cards[0]["sha256"]
        assert event.payload["original_outcome"] == "UNKNOWN"
        assert event.payload["resolution_effect"] == "none"
        assert event.payload["resolution_verified"] is False
        assert event.payload["owner_statement_only"] is True
        previous = str(event.id)
    assert ActionCardRevision.objects.get(id=context[3].id).cards == original_cards
    assert (
        AssessmentSnapshot.objects.get(id=context[2].id).result_payload
        == original_results
    )
    with actual_app_default():
        history = client.get(route(context))
    assert b"original UNKNOWN" in history.content
    assert b"Resolution verification: not established" in history.content


def test_strict_csrf_and_stale_cas_never_append_extra_statement(
    capture_decision_context, settings
):
    context = capture_decision_context
    client = owner_client(context, settings)
    with actual_app_default():
        assert client.get(route(context)).status_code == 200
        assert client.post(route(context), statement()).status_code == 403
    assert not DecisionEvent.objects.exists()
    with actual_app_default():
        assert post(client, route(context), statement()).status_code == 302
        response = post(client, route(context), statement())
    assert response.status_code == 409
    assert DecisionEvent.objects.count() == 1


@pytest.mark.parametrize("gate", ["proposal", "decision", "workspace"])
def test_application_gates_close_owner_write_without_effects(
    capture_decision_context, settings, gate
):
    context = capture_decision_context
    client = owner_client(context, settings)
    with actual_app_default():
        assert client.get(route(context)).status_code == 200
    setattr(
        settings,
        {
            "proposal": "CORE_PROPOSAL_ADMISSION_ENABLED",
            "decision": "DECISION_DESK_ENABLED",
            "workspace": "CORE_REVIEW_WORKSPACE_ENABLED",
        }[gate],
        False,
    )
    before = effects()
    with actual_app_default():
        assert post(client, route(context), statement()).status_code == 503
    assert effects() == before


@pytest.mark.parametrize("target", ["snapshot", "decision"])
def test_missing_proposal_receipt_withholds_content(
    capture_decision_context, settings, target
):
    context = capture_decision_context
    client = owner_client(context, settings)
    # Privileged corruption confined to disposable qualification database.
    with connections["default"].cursor() as cursor:
        cursor.execute("TRUNCATE review_capture_proposal_receipts")
    endpoint = (
        route(context)
        if target == "decision"
        else reverse("reviews:snapshot", args=[context[2].id])
    )
    before = effects()
    with actual_app_default():
        response = client.get(endpoint)
    assert response.status_code == 503
    assert b"Content is withheld" in response.content
    assert context[3].cards[0]["proposal_text"].encode() not in response.content
    assert effects() == before


@pytest.mark.parametrize("visitor", ["viewer", "foreign_owner"])
def test_nonowner_or_foreign_tenant_cannot_read_exact_proposal(
    capture_decision_context, settings, visitor
):
    context = capture_decision_context
    if visitor == "viewer":
        user = get_user_model().objects.create_user("proposal-viewer@example.invalid")
        org = context[1]
        OrganizationMember.objects.create(organization=org, user=user, role="viewer")
    if visitor == "foreign_owner":
        user = context[0]
        org = Organization.objects.create(name="Foreign proposal workspace")
        OrganizationMember.objects.create(organization=org, user=user, role="owner")
    client = owner_client((user, org), settings)
    # Isolate the owner/tenant read guard; unpaid viewer billing redirects are
    # separate. Authentication, identity, tenancy and strict CSRF stay intact.
    settings.MIDDLEWARE = [
        entry
        for entry in settings.MIDDLEWARE
        if not entry.endswith("BillingEntitlementMiddleware")
    ]
    before = effects()
    with actual_app_default():
        response = client.get(route(context))
    assert response.status_code == (403 if visitor == "viewer" else 404)
    assert context[3].cards[0]["proposal_text"].encode() not in response.content
    assert effects() == before
