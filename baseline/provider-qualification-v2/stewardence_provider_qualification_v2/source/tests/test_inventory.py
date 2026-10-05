from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse

from apps.assessments.models import AssessmentSnapshot
from apps.audit.models import AuditEvent
from apps.inventory.forms import DATA_CATEGORY_CHOICES, InventoryItemForm
from apps.inventory.models import InventoryItem
from apps.jobs.models import BackgroundJob
from apps.organizations.models import Organization, OrganizationMember
from apps.policies.models import OrganizationRule
from apps.reports.models import Report
from tests.conftest import grant_core_entitlement

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory_context(client):
    user = get_user_model().objects.create_user("inventory@example.com")
    organization = Organization.objects.create(name="Inventory Firm")
    membership = OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )
    grant_core_entitlement(user, organization)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    return user, organization, membership


def inventory_payload(**overrides):
    payload = {
        "display_name": "Ledger Assistant",
        "vendor_name": "Example Vendor",
        "business_owner": "Jordan Lee",
        "department": "Bookkeeping",
        "user_count": "7",
        "business_purpose": "Help prepare monthly reconciliations",
        "monthly_cost": "49.95",
        "seat_count": "5",
        "connected_systems": ["accounting", "document_storage"],
        "data_categories": ["client_information", "financial_records"],
        "permissions": ["read", "write"],
        "capabilities": ["data_analysis", "record_modification"],
        "autonomy_level": str(InventoryItem.Autonomy.AFTER_APPROVAL),
        "human_approval": "on",
        "status": InventoryItem.Status.ACTIVE,
    }
    payload.update(overrides)
    return payload


def test_required_data_categories_are_available():
    assert [label for _value, label in DATA_CATEGORY_CHOICES] == [
        "Public information",
        "Internal business information",
        "Client information",
        "Financial records",
        "Banking information",
        "Payroll",
        "Tax records",
        "Health information",
        "Legal information",
        "Authentication credentials",
        "Personally identifiable information",
    ]


def test_form_uses_business_language_and_exact_currency_conversion():
    form = InventoryItemForm(data=inventory_payload())

    assert form.is_valid(), form.errors
    item = form.save(commit=False)
    assert form.fields["autonomy_level"].label == "What can this AI do on its own?"
    assert item.monthly_cost_cents == 4995
    assert item.connected_systems == ["accounting", "document_storage"]
    assert item.data_categories == ["client_information", "financial_records"]


def test_owner_can_add_and_view_inventory(client, inventory_context):
    user, organization, _membership = inventory_context

    response = client.post(reverse("inventory:create"), inventory_payload())

    assert response.status_code == 302
    item = InventoryItem.objects.get()
    assert item.organization == organization
    assert item.source_type == InventoryItem.SourceType.MANUAL
    assert item.monthly_cost_cents == 4995
    event = AuditEvent.objects.get()
    assert event.organization == organization
    assert event.actor_user_id == user.id
    assert event.event_type == "inventory.created"
    assert event.entity_id == item.id
    assert event.data == {"source_type": "manual"}
    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"Ledger Assistant" in detail.content
    assert b"$49.95" in detail.content


def test_inventory_detail_explains_risk_score_and_each_contribution(
    client, inventory_context
):
    _user, organization, _membership = inventory_context
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Payroll Messenger",
        vendor_name="Example Vendor",
        data_categories=["payroll"],
        capabilities=["external_transfer"],
        human_approval=False,
    )

    response = client.get(reverse("inventory:detail", args=(item.id,)))

    assert response.status_code == 200
    assert b"Risk: 75" in response.content
    assert b"Critical" in response.content
    assert b"Why did this receive this score?" in response.content
    assert b"Payroll information can leave the firm" in response.content
    assert b"Show the arithmetic" in response.content
    assert b"Data Sensitivity: 25" in response.content
    assert b"Weighted total before required minimums" in response.content


def test_roi_page_displays_all_arithmetic_and_assumption_sources(
    client, inventory_context
):
    _user, organization, _membership = inventory_context
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Time Saver",
        vendor_name="Example Vendor",
        monthly_cost_cents=10000,
    )
    payload = {
        "monthly_subscription_cost": "100.00",
        "monthly_subscription_cost_provenance": "Customer supplied",
        "implementation_cost": "1200.00",
        "implementation_cost_provenance": "Customer supplied",
        "implementation_amortization_months": "12",
        "implementation_amortization_months_provenance": "Estimated",
        "hours_saved_per_month": "10.00",
        "hours_saved_per_month_provenance": "Measured",
        "loaded_hourly_rate": "50.00",
        "loaded_hourly_rate_provenance": "Customer supplied",
        "attributable_revenue": "200.00",
        "attributable_revenue_provenance": "Estimated",
        "avoided_monthly_cost": "100.00",
        "avoided_monthly_cost_provenance": "Measured",
    }

    response = client.post(reverse("inventory:roi", args=(item.id,)), payload)

    assert response.status_code == 200
    assert b"Monthly net value: $600.00" in response.content
    assert b"300.00%" in response.content
    assert b"Monthly labor value: 10.00 hours" in response.content
    assert b"Monthly implementation cost: $1200.00" in response.content
    assert b"Assumption sources" in response.content
    assert response.content.count(b"Measured") >= 2
    assert response.content.count(b"Customer supplied") >= 2
    assert response.content.count(b"Estimated") >= 2


def test_roi_page_handles_zero_cost_and_rejects_unknown_nonzero_values(
    client, inventory_context
):
    _user, organization, _membership = inventory_context
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="No-cost Trial",
        vendor_name="Example Vendor",
    )
    zero_payload = {
        "monthly_subscription_cost": "0.00",
        "monthly_subscription_cost_provenance": "Unknown",
        "implementation_cost": "0.00",
        "implementation_cost_provenance": "Unknown",
        "implementation_amortization_months": "12",
        "implementation_amortization_months_provenance": "Estimated",
        "hours_saved_per_month": "0.00",
        "hours_saved_per_month_provenance": "Unknown",
        "loaded_hourly_rate": "0.00",
        "loaded_hourly_rate_provenance": "Unknown",
        "attributable_revenue": "0.00",
        "attributable_revenue_provenance": "Unknown",
        "avoided_monthly_cost": "0.00",
        "avoided_monthly_cost_provenance": "Unknown",
    }

    response = client.post(reverse("inventory:roi", args=(item.id,)), zero_payload)
    assert b"Not available because monthly total cost is $0.00" in response.content
    assert b"Infinity" not in response.content

    zero_payload["hours_saved_per_month"] = "2.00"
    invalid = client.post(reverse("inventory:roi", args=(item.id,)), zero_payload)
    assert b"Use 0 when this amount is unknown." in invalid.content
    assert invalid.context["roi_result"] is None


def test_viewer_cannot_create_or_edit_inventory(client, inventory_context):
    _user, organization, membership = inventory_context
    membership.role = OrganizationMember.Role.VIEWER
    membership.save(update_fields=("role",))
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Read only item",
        vendor_name="Vendor",
    )

    assert (
        client.post(reverse("inventory:create"), inventory_payload()).status_code == 403
    )
    assert (
        client.post(
            reverse("inventory:edit", args=(item.id,)), inventory_payload()
        ).status_code
        == 403
    )


def test_item_lookup_is_scoped_to_the_active_organization(client, inventory_context):
    _user, _organization, _membership = inventory_context
    other_organization = Organization.objects.create(name="Other Firm")
    other_item = InventoryItem.objects.create(
        organization=other_organization,
        display_name="Other tenant item",
        vendor_name="Other vendor",
    )

    response = client.get(reverse("inventory:detail", args=(other_item.id,)))

    assert response.status_code == 404
    assert (
        client.get(reverse("inventory:roi", args=(other_item.id,))).status_code == 404
    )


def test_owner_can_edit_inventory_without_changing_source(client, inventory_context):
    _user, organization, _membership = inventory_context
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Before",
        vendor_name="Vendor",
        source_type=InventoryItem.SourceType.DISCOVERED,
        discovery_fingerprint="a" * 64,
    )

    response = client.post(
        reverse("inventory:edit", args=(item.id,)),
        inventory_payload(display_name="After"),
    )

    assert response.status_code == 302
    item.refresh_from_db()
    assert item.display_name == "After"
    assert item.source_type == InventoryItem.SourceType.DISCOVERED
    event = AuditEvent.objects.get()
    assert event.event_type == "inventory.changed"
    assert event.entity_id == item.id
    assert event.data["change"] == "edited"
    assert "display_name" in event.data["fields"]


def test_archive_is_post_only_and_removes_item_from_current_list(
    client, inventory_context
):
    _user, organization, _membership = inventory_context
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Archive me",
        vendor_name="Vendor",
    )
    archive_url = reverse("inventory:archive", args=(item.id,))

    assert client.get(archive_url).status_code == 405
    assert client.post(archive_url).status_code == 302
    item.refresh_from_db()
    assert item.archived_at is not None
    event = AuditEvent.objects.get()
    assert event.event_type == "inventory.changed"
    assert event.entity_id == item.id
    assert event.data == {"change": "archived"}
    list_response = client.get(reverse("inventory:list"))
    assert list(list_response.context["items"]) == []


def test_inventory_and_audit_append_are_atomic(
    client,
    inventory_context,
    monkeypatch,
):
    def fail_append(**_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(
        "apps.inventory.views.append_audit_event",
        fail_append,
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        client.post(
            reverse("inventory:create"),
            inventory_payload(),
        )

    assert InventoryItem.objects.count() == 0
    assert AuditEvent.objects.count() == 0


def test_inventory_search_and_status_filter(client, inventory_context):
    _user, organization, _membership = inventory_context
    InventoryItem.objects.create(
        organization=organization,
        display_name="Payroll Helper",
        vendor_name="Alpha",
        status=InventoryItem.Status.ACTIVE,
    )
    InventoryItem.objects.create(
        organization=organization,
        display_name="Tax Reviewer",
        vendor_name="Beta",
        status=InventoryItem.Status.TRIAL,
    )

    search = client.get(reverse("inventory:list"), {"q": "payroll"})
    assert b"Payroll Helper" in search.content
    assert b"Tax Reviewer" not in search.content

    filtered = client.get(
        reverse("inventory:list"),
        {"status": InventoryItem.Status.TRIAL},
    )
    assert b"Tax Reviewer" in filtered.content
    assert b"Payroll Helper" not in filtered.content


def test_demo_command_creates_exactly_ten_manual_items_and_refuses_overwrite():
    organization = Organization.objects.create(name="Demo Bookkeeping Firm")

    call_command("seed_demo_inventory", str(organization.id), verbosity=0)

    items = InventoryItem.objects.filter(organization=organization)
    assert items.count() == 10
    assert set(items.values_list("source_type", flat=True)) == {"manual"}
    assert set(items.values_list("display_name", flat=True)) == {
        "ChatGPT",
        "Microsoft Copilot",
        "Google Gemini",
        "QuickBooks",
        "Grammarly",
        "Canva",
        "Otter",
        "Zapier",
        "LedgerWise AI Bookkeeping Assistant",
        "Unknown AI Tool",
    }
    assert items.filter(product__isnull=True).count() == 10
    assert sum(items.values_list("monthly_cost_cents", flat=True)) > 0
    assert items.filter(
        data_categories__contains=["payroll"],
        capabilities__contains=["external_transfer"],
        human_approval=False,
    ).exists()
    assert items.filter(
        connected_systems__contains=["banking"],
        permissions__contains=["write"],
    ).exists()
    with pytest.raises(CommandError, match="no items"):
        call_command("seed_demo_inventory", str(organization.id), verbosity=0)


def test_demo_company_builds_four_band_report_and_two_roi_scenarios():
    user = get_user_model().objects.create_user("demo-builder@example.com")
    organization = Organization.objects.create(name="Demo Bookkeeping Company")
    OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )

    call_command(
        "seed_demo_company",
        str(organization.id),
        str(user.id),
        verbosity=0,
    )

    assert InventoryItem.objects.filter(organization=organization).count() == 10
    assert OrganizationRule.objects.filter(organization=organization).count() == 2
    snapshots = list(
        AssessmentSnapshot.objects.filter(organization=organization).order_by(
            "captured_at"
        )
    )
    assert len(snapshots) == 2
    assert Decimal(snapshots[0].result_payload["roi"]["roi_percent"]) < 0
    assert Decimal(snapshots[1].result_payload["roi"]["roi_percent"]) > 0

    inventory_results = snapshots[1].result_payload["inventory_results"]
    assert {result["risk"]["band"] for result in inventory_results} == {
        "Low",
        "Moderate",
        "High",
        "Critical",
    }
    assert {
        finding["severity"]
        for result in inventory_results
        for finding in result["policy_results"]
        if finding["result"] in {"FAIL", "WARNING"}
    } == {"LOW", "MODERATE", "HIGH", "CRITICAL"}

    report = Report.objects.get(organization=organization)
    job = BackgroundJob.objects.get(
        organization=organization,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
    )
    assert job.payload == {"report_id": str(report.id)}
    assert job.status == BackgroundJob.Status.QUEUED


def test_monthly_cost_display_is_decimal_safe():
    item = InventoryItem(monthly_cost_cents=4001)
    assert Decimal(item.monthly_cost_display) == Decimal("40.01")
