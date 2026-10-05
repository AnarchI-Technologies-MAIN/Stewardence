"""Explicit unknown semantics and narrow issuance with actual PostgreSQL roles."""

import json
from datetime import date
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections
from django.test import Client
from django.urls import reverse

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.models import AssessmentSnapshot
from apps.inventory.explicit_declarations import (
    CONTRACT,
    normalized_explicit_inventory_record,
    write_explicit_inventory,
)
from apps.inventory.explicit_forms import ExplicitInventoryForm
from apps.inventory.models import ExplicitDeclarationGate, InventoryItem
from apps.inventory.provenance import DECLARED, UNKNOWN, inventory_provenance
from apps.jobs.core_workflows import configure_control
from apps.organizations.models import Organization, OrganizationMember, WorkflowProfile

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def explicit_context(report_context, settings):
    user, org, _, _, _ = report_context
    WorkflowProfile.objects.get_or_create(
        organization=org,
        defaults={
            "created_by": user,
            "profile": "business.v1",
            "settings": {"name": "Explicit inventory"},
        },
    )
    ExplicitDeclarationGate.objects.update_or_create(id=1, defaults={"enabled": True})
    settings.CORE_EXPLICIT_INVENTORY_ENABLED = True
    return user, org


def form(**values):
    result = ExplicitInventoryForm(
        {"display_name": "Workflow helper", "declaration_as_of": "2026-01-01", **values}
    )
    assert result.is_valid(), result.errors
    return result


def issue(context, declaration=None, item_id=None):
    user, org = context
    identity = write_explicit_inventory(
        organization_id=org.id,
        actor_id=user.id,
        item_id=item_id or uuid4(),
        form=declaration or form(),
        using="app_runtime",
    )
    return InventoryItem.objects.get(id=identity)


def raw_call(context, payload, item_id=None, using="app_runtime"):
    user, org = context
    with (
        identity_transaction(user.id, using=using),
        tenant_transaction(org.id, using=using),
        connections[using].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.write_explicit_inventory(%s,%s,%s,%s::jsonb)",
            [item_id or uuid4(), org.id, user.id, json.dumps(payload)],
        )
        return cursor.fetchone()[0]


def test_omitted_fields_are_unknown_including_cost_approval_and_lists(explicit_context):
    item = issue(explicit_context)
    record = normalized_explicit_inventory_record(item)
    assert item.source_type == "manual"
    assert (
        item.monthly_cost_cents == 0
    )  # Compatibility storage, never normalized knowledge.
    for name in (
        "monthly_cost_cents",
        "user_count",
        "seat_count",
        "human_approval",
        "autonomy_level",
        "status",
        "permissions",
        "connected_systems",
        "data_categories",
        "capabilities",
    ):
        assert record[name] is None
        assert record["provenance"][name] == UNKNOWN
    assert record["display_name"] == "Workflow helper"
    assert record["product_id"] is None
    assert record["declaration_as_of"] == "2026-01-01"


def test_explicit_none_no_zero_and_selected_values_are_declared(explicit_context):
    item = issue(
        explicit_context,
        form(
            monthly_cost="0.00",
            user_count="0",
            human_approval="no",
            autonomy_level="0",
            permissions=["__none__"],
            data_categories=["financial_records"],
            connected_systems=["accounting"],
            capabilities=["__none__"],
        ),
    )
    record = normalized_explicit_inventory_record(item)
    assert record["monthly_cost_cents"] == 0
    assert record["user_count"] == 0
    assert record["human_approval"] is False
    assert record["autonomy_level"] == 0
    assert record["permissions"] == []
    assert record["data_categories"] == ["financial_records"]
    assert record["capabilities"] == []
    assert all(
        record["provenance"][key] == DECLARED
        for key in (
            "monthly_cost_cents",
            "user_count",
            "human_approval",
            "autonomy_level",
            "permissions",
            "data_categories",
            "capabilities",
        )
    )


@pytest.mark.parametrize(
    "field", ["permissions", "data_categories", "connected_systems", "capabilities"]
)
def test_none_cannot_be_combined_with_a_selected_value(field):
    example = {
        "permissions": "read",
        "data_categories": "financial_records",
        "connected_systems": "accounting",
        "capabilities": "data_analysis",
    }[field]
    submitted = ExplicitInventoryForm(
        {
            "display_name": "Tool",
            "declaration_as_of": "2026-01-01",
            field: ["__none__", example],
        }
    )
    assert not submitted.is_valid()
    assert field in submitted.errors


def test_owner_update_can_deliberately_return_a_known_detail_to_unknown(
    explicit_context,
):
    item = issue(
        explicit_context,
        form(monthly_cost="25", human_approval="yes", permissions=["read"]),
    )
    previous = normalized_explicit_inventory_record(item)
    item = issue(explicit_context, form(), item_id=item.id)
    current = normalized_explicit_inventory_record(item)
    assert previous["monthly_cost_cents"] == 2500
    assert previous["human_approval"] is True
    assert current["monthly_cost_cents"] is None
    assert current["human_approval"] is None
    assert current["permissions"] is None
    assert previous["permissions"] == [
        "read"
    ]  # Previously captured data was not mutated.


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_raw_update_and_delete_of_explicit_record_are_denied(explicit_context, using):
    item = issue(explicit_context)
    for sql in (
        (
            "UPDATE inventory_items SET declared_fields="
            '\'["display_name","human_approval"]\'::jsonb WHERE id=%s'
        ),
        "DELETE FROM inventory_items WHERE id=%s",
    ):
        with (
            pytest.raises(DatabaseError),
            identity_transaction(explicit_context[0].id, using=using),
            tenant_transaction(explicit_context[1].id, using=using),
            connections[using].cursor() as cursor,
        ):
            cursor.execute(sql, [item.id])
    item.refresh_from_db()
    assert inventory_provenance(item)["human_approval"] == UNKNOWN


def test_raw_app_cannot_spoof_explicit_contract_on_legacy_row(explicit_context):
    user, org = explicit_context
    item = InventoryItem.objects.create(
        organization=org, display_name="Legacy", vendor_name="Vendor"
    )
    with (
        pytest.raises(DatabaseError),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
        connections["app_runtime"].cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE inventory_items SET declaration_contract=%s,"
            "declaration_as_of=%s WHERE id=%s",
            [CONTRACT, date(2026, 1, 1), item.id],
        )
    item.refresh_from_db()
    assert item.declaration_contract == ""
    assert inventory_provenance(item)["human_approval"] == DECLARED


def test_worker_cannot_execute_narrow_issuer(explicit_context):
    with pytest.raises(DatabaseError):
        raw_call(explicit_context, form().declaration_payload(), using="worker_runtime")


def test_operator_gate_and_pause_deny_new_admission(explicit_context):
    ExplicitDeclarationGate.objects.filter(id=1).update(enabled=False)
    with pytest.raises(DatabaseError):
        issue(explicit_context)
    ExplicitDeclarationGate.objects.filter(id=1).update(enabled=True)
    configure_control(
        organization_id=explicit_context[1].id,
        actor_id=explicit_context[0].id,
        mode="paused",
        reason="Stop for owner review",
        using="app_runtime",
    )
    with pytest.raises(DatabaseError):
        issue(explicit_context)


def test_nonowner_and_wrong_context_cannot_issue(explicit_context):
    user, org = explicit_context
    viewer = get_user_model().objects.create_user("explicit-viewer@example.invalid")
    OrganizationMember.objects.create(organization=org, user=viewer, role="viewer")
    with pytest.raises(DatabaseError):
        raw_call((viewer, org), form().declaration_payload())
    foreign = Organization.objects.create(name="Other firm")
    with (
        pytest.raises(DatabaseError),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(foreign.id, using="app_runtime"),
        connections["app_runtime"].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.write_explicit_inventory(%s,%s,%s,%s::jsonb)",
            [uuid4(), org.id, user.id, json.dumps(form().declaration_payload())],
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_nondefault",
        "extra_key",
        "undeclared_field",
        "bool_numeric",
        "future_date",
        "unsupported_permission",
    ],
)
def test_actual_app_issuer_rejects_malformed_contract(explicit_context, mutation):
    payload = form().declaration_payload()
    if mutation == "unknown_nondefault":
        payload["values"]["monthly_cost_cents"] = 900
    if mutation == "extra_key":
        payload["observation_verified"] = True
    if mutation == "undeclared_field":
        payload["declared_fields"].append("offboarding_verified")
    if mutation == "bool_numeric":
        payload["values"]["user_count"] = False
    if mutation == "future_date":
        payload["as_of"] = "9999-01-01"
    if mutation == "unsupported_permission":
        payload["declared_fields"].append("permissions")
        payload["values"]["permissions"] = ["root"]
    with pytest.raises(DatabaseError):
        raw_call(explicit_context, payload)


def test_legacy_target_cannot_be_silently_upgraded(explicit_context):
    item = InventoryItem.objects.create(
        organization=explicit_context[1], display_name="Legacy", vendor_name="Vendor"
    )
    with pytest.raises(DatabaseError):
        issue(explicit_context, item_id=item.id)
    item.refresh_from_db()
    assert item.declaration_contract == ""


def test_ui_closed_flag_and_plain_unknown_path(explicit_context, client, settings):
    settings.CORE_EXPLICIT_INVENTORY_ENABLED = False
    url = reverse("inventory:explicit-create")
    assert client.get(url).status_code == 503
    assert (
        client.post(
            url, {"display_name": "Tool", "declaration_as_of": "2026-01-01"}
        ).status_code
        == 503
    )
    settings.CORE_EXPLICIT_INVENTORY_ENABLED = True
    response = client.post(
        url, {"display_name": "Tool", "declaration_as_of": "2026-01-01"}
    )
    assert response.status_code == 302
    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"Unknown" in detail.content
    assert b"Risk:" not in detail.content
    item = InventoryItem.objects.get(display_name="Tool")
    assert client.get(reverse("inventory:roi", args=[item.id])).status_code == 503
    assert client.post(reverse("inventory:archive", args=[item.id])).status_code == 503


def test_legacy_form_post_cannot_promote_defaults_on_explicit_item(
    explicit_context, client
):
    item = issue(explicit_context)
    response = client.post(
        reverse("inventory:edit", args=[item.id]),
        {"display_name": "Tool", "monthly_cost": "0.00", "human_approval": "on"},
    )
    assert response.status_code == 200
    item.refresh_from_db()
    assert item.display_name == "Workflow helper"
    assert inventory_provenance(item)["human_approval"] == UNKNOWN


def test_new_owner_add_path_uses_explicit_questions(explicit_context, client):
    response = client.get(reverse("inventory:create"))
    assert response.status_code == 200
    assert b"Record what you know" in response.content
    assert b"declaration_as_of" in response.content
    response = client.post(
        reverse("inventory:create"), {"display_name": "New owner tool"}
    )
    assert response.status_code == 200
    assert not InventoryItem.objects.filter(display_name="New owner tool").exists()


def test_explicit_route_post_requires_csrf(explicit_context, client):
    strict = Client(enforce_csrf_checks=True)
    strict.cookies = client.cookies
    response = strict.post(
        reverse("inventory:explicit-create"),
        {"display_name": "CSRF tool", "declaration_as_of": "2026-01-01"},
    )
    assert response.status_code == 403
    assert not InventoryItem.objects.filter(display_name="CSRF tool").exists()


def test_raw_app_insert_cannot_bypass_narrow_issuer(explicit_context):
    user, org = explicit_context
    with (
        pytest.raises(DatabaseError),
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        InventoryItem.objects.using("app_runtime").create(
            organization_id=org.id,
            display_name="Forged explicit",
            vendor_name="",
            declaration_contract=CONTRACT,
            declaration_as_of=date(2026, 1, 1),
            declared_fields=["display_name"],
        )
    assert not InventoryItem.objects.filter(display_name="Forged explicit").exists()


def test_inventory_list_does_not_present_compatibility_defaults_as_knowledge(
    explicit_context, client
):
    issue(explicit_context)
    response = client.get(reverse("inventory:list"))
    assert response.status_code == 200
    assert b"Current use unknown" in response.content
    assert b"People using it unknown" in response.content
    assert b"Independent actions unknown" in response.content
    filtered = client.get(reverse("inventory:list"), {"status": "reviewing"})
    assert b"Workflow helper" not in filtered.content


def test_legacy_roi_save_with_explicit_firm_records_returns_bounded_review_message(
    explicit_context, client
):
    issue(explicit_context)
    legacy = InventoryItem.objects.create(
        organization=explicit_context[1],
        display_name="Existing legacy tool",
        vendor_name="Vendor",
    )
    count = AssessmentSnapshot.objects.count()
    payload = {
        "action": "save_snapshot",
        "implementation_amortization_months": "12",
        "implementation_amortization_months_provenance": "Estimated",
    }
    for key in (
        "monthly_subscription_cost",
        "implementation_cost",
        "hours_saved_per_month",
        "loaded_hourly_rate",
        "attributable_revenue",
        "avoided_monthly_cost",
    ):
        payload[key] = "0.00"
        payload[key + "_provenance"] = "Unknown"
    response = client.post(reverse("inventory:roi", args=[legacy.id]), payload)
    assert response.status_code == 409
    assert b"deliberate evidence review" in response.content
    assert AssessmentSnapshot.objects.count() == count
