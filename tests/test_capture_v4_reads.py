"""Owner v4 reads bind frozen selections to actual immutable issuance rows."""

from copy import copy, deepcopy
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import connections
from django.urls import reverse

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.jobs.core_models import DecisionEvent
from apps.organizations.models import Organization, OrganizationMember
from apps.reviews.capture_context import digest
from apps.reviews.capture_pack_reads import read_frozen_capture_entries
from tests.test_capture_admission import capture_context as capture_context
from tests.test_capture_decisions import (
    capture_decision_context as capture_decision_context,
)
from tests.test_capture_decisions import decide
from tests.test_capture_proposal_ui import effects, owner_client
from tests.test_capture_v4_packs import frozen
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["capture_context", "capture_decision_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def selected_pack(capture_decision_context):
    context = capture_decision_context
    first = decide(
        context,
        event_kind="disposition",
        state="defer",
        notes="Frozen disposition before later history",
    )
    second = decide(
        context,
        expected_previous_event=str(first),
        notes="Frozen completion is an unverified owner statement",
    )
    pack_context = frozen(context)
    return context, pack_context, first, second


def pack_route(pack_context):
    return reverse("reviews:pack-detail", args=[pack_context[3].id])


def test_owner_reads_all_proposals_and_exact_frozen_events_after_later_history(
    selected_pack, settings
):
    context, pack_context, first, second = selected_pack
    later = decide(
        context,
        event_kind="disposition",
        state="act",
        expected_previous_event=str(second),
        notes="Later live-only note",
    )
    client = owner_client(context, settings)
    before = effects()
    with (
        actual_app_default(),
        identity_transaction(context[0].id, using="app_runtime"),
        tenant_transaction(context[1].id, using="app_runtime"),
    ):
        assert len(read_frozen_capture_entries(pack_context[3], context[2])) == 2
    with actual_app_default():
        response = client.get(pack_route(pack_context))
    assert response.status_code == 200, response.content.decode()
    assert response["Cache-Control"] == "private, no-store"
    assert effects() == before
    assert {entry["event"].id for entry in response.context["entries"]} == {
        first,
        second,
    }
    assert later not in {entry["event"].id for entry in response.context["entries"]}
    assert [
        entry["proposal"] for entry in response.context["frozen_proposals"]
    ] == context[3].cards
    text = response.content.decode()
    assert "All frozen proposals" in text
    assert "Frozen disposition before later history" in text
    assert "Frozen completion is an unverified owner statement" in text
    assert "Later live-only note" not in text
    assert "Verified resolution is not established" in text
    assert "UNKNOWN" in text


@pytest.mark.parametrize("visitor", ["viewer", "assessor", "foreign_owner"])
def test_viewer_and_foreign_owner_cannot_read_frozen_capture_content(
    selected_pack, settings, visitor
):
    context, pack_context, _, _ = selected_pack
    if visitor in {"viewer", "assessor"}:
        user = get_user_model().objects.create_user(f"v4-{visitor}@example.invalid")
        org = context[1]
        OrganizationMember.objects.create(organization=org, user=user, role=visitor)
    if visitor == "foreign_owner":
        user = context[0]
        org = Organization.objects.create(name="Other frozen-pack workspace")
        OrganizationMember.objects.create(organization=org, user=user, role="owner")
    client = owner_client((user, org), settings)
    # Keep actual identity/tenant/authentication middleware. Billing redirect
    # is a separate guard; isolate the owner-only read boundary here.
    settings.MIDDLEWARE = [
        entry
        for entry in settings.MIDDLEWARE
        if not entry.endswith("BillingEntitlementMiddleware")
    ]
    before = effects()
    with actual_app_default():
        response = client.get(pack_route(pack_context))
    assert response.status_code == (404 if visitor == "foreign_owner" else 403)
    assert b"Frozen disposition before later history" not in response.content
    assert effects() == before


@pytest.mark.parametrize("missing", ["proposal_receipt", "events"])
def test_real_missing_issuance_rows_withhold_frozen_pack(
    selected_pack, settings, missing
):
    context, pack_context, _, _ = selected_pack
    client = owner_client(context, settings)
    # Privileged disposable fixture corruption; ordinary app has no CRUD grant.
    with connections["default"].cursor() as cursor:
        table = {
            "proposal_receipt": "review_capture_proposal_receipts",
            "events": "core_decision_events",
        }[missing]
        cursor.execute(f"TRUNCATE {table}")
    before = effects()
    with actual_app_default():
        response = client.get(pack_route(pack_context))
    assert response.status_code == 503
    assert b"Content is withheld" in response.content
    assert b"Frozen disposition before later history" not in response.content
    assert effects() == before


@pytest.mark.parametrize(
    "field", ["proposal_receipt_id", "revision_id", "qualification_sha256"]
)
def test_self_consistent_manifest_metadata_does_not_replace_actual_issuance(
    capture_decision_context, field
):
    user, org, snapshot, pack = frozen(capture_decision_context)
    # In-memory adversarial object only; no immutable-row trigger is disabled.
    forged = copy(pack)
    forged.manifest = deepcopy(pack.manifest)
    replacement = "a" * 64 if field == "qualification_sha256" else str(uuid4())
    for selected in forged.manifest["selected_proposals"]:
        selected[field] = replacement
    forged.sha256 = digest(forged.manifest)
    with (
        actual_app_default(),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
        pytest.raises(ValueError),
    ):
        read_frozen_capture_entries(forged, snapshot)


def test_real_row_selection_checks_are_actual_app_owner_role(selected_pack):
    context, pack_context, first, second = selected_pack
    user, org, snapshot, pack = pack_context
    with (
        actual_app_default(),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT current_user")
            assert cursor.fetchone()[0] == "agentledger_app"
        entries = read_frozen_capture_entries(pack, snapshot)
    assert {entry["event"].id for entry in entries} == {first, second}
    assert all(
        entry["event"].payload["resolution_verified"] is False for entry in entries
    )


@pytest.mark.parametrize("bad_index", [-1, 9999, True, None])
def test_malformed_persisted_event_index_is_bounded_before_card_access(
    selected_pack, monkeypatch, bad_index
):
    _, pack_context, _, _ = selected_pack
    user, org, snapshot, pack = pack_context
    manager = DecisionEvent.objects
    original = manager.filter

    def corrupted_row(**filters):
        # In-memory corruption of actual queried immutable rows, not a grant
        # expansion or disabled database trigger. Payload and manifest stay
        # unchanged so row-bound validation must reject the malformed index.
        rows = [copy(row) for row in original(**filters)]
        rows[0].card_index = bad_index
        return rows

    monkeypatch.setattr(manager, "filter", corrupted_row)
    with (
        actual_app_default(),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
        pytest.raises(ValueError),
    ):
        read_frozen_capture_entries(pack, snapshot)


@pytest.mark.parametrize(
    "field", ["revision_sha256", "snapshot_result_sha256", "card_sha256"]
)
def test_event_row_digest_pins_cannot_disagree_with_frozen_payload(
    selected_pack, monkeypatch, field
):
    _, pack_context, _, _ = selected_pack
    user, org, snapshot, pack = pack_context
    manager = DecisionEvent.objects
    original = manager.filter

    def corrupted_row(**filters):
        rows = [copy(row) for row in original(**filters)]
        setattr(rows[0], field, "a" * 64)
        return rows

    monkeypatch.setattr(manager, "filter", corrupted_row)
    with (
        actual_app_default(),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
        pytest.raises(ValueError),
    ):
        read_frozen_capture_entries(pack, snapshot)
