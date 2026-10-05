from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.assessments.snapshots import create_assessment_snapshot
from apps.billing.models import BillingCustomer, Subscription
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.organizations.views import _create_and_bind_owned_workspace
from apps.policies.models import OrganizationRule
from apps.reports.services import create_report
from tests.conftest import _roi_inputs


pytestmark = pytest.mark.django_db


def make_subscription(
    user,
    *,
    organization=None,
    status=Subscription.Status.ACTIVE,
):
    customer = BillingCustomer.objects.create(
        user=user,
    )

    return Subscription.objects.create(
        billing_customer=customer,
        organization=organization,
        portfolio=Subscription.Portfolio.CORE,
        status=status,
        current_price_cents=9900,
    )


@pytest.fixture
def authority_context(client):
    user = get_user_model().objects.create_user(
        "billing-authority@example.com",
        "Strong!BillingAuthority98",
    )

    organization_a = Organization.objects.create(
        name="Paid Firm A",
    )

    organization_b = Organization.objects.create(
        name="Member Firm B",
    )

    OrganizationMember.objects.create(
        user=user,
        organization=organization_a,
        role=OrganizationMember.Role.OWNER,
    )

    OrganizationMember.objects.create(
        user=user,
        organization=organization_b,
        role=OrganizationMember.Role.OWNER,
    )

    subscription = make_subscription(
        user,
        organization=organization_a,
    )

    item_a = InventoryItem.objects.create(
        organization=organization_a,
        display_name="Authorized Inventory",
        vendor_name="Authorized Vendor",
    )

    item_b = InventoryItem.objects.create(
        organization=organization_b,
        display_name="Foreign Inventory",
        vendor_name="Foreign Vendor",
    )

    rule_b = OrganizationRule.objects.create(
        organization=organization_b,
        name="Foreign Rule",
        definition={
            "all": [
                {
                    "field": "status",
                    "operator": "equals",
                    "value": "active",
                }
            ],
            "effects": [
                {
                    "type": "severity_floor",
                    "value": "HIGH",
                }
            ],
        },
        result_on_match=OrganizationRule.Result.FAIL,
        severity=OrganizationRule.Severity.HIGH,
        explanation="Foreign organization rule.",
        remediation="Foreign organization remediation.",
        created_by=user,
    )

    snapshot_b = create_assessment_snapshot(
        organization_id=organization_b.id,
        created_by_id=user.id,
        assessed_item_id=item_b.id,
        roi_inputs=_roi_inputs(),
        captured_at=datetime(
            2026,
            9,
            10,
            12,
            0,
            tzinfo=UTC,
        ),
    )

    report_b = create_report(
        organization_id=organization_b.id,
        assessment_snapshot_id=snapshot_b.id,
        created_by_id=user.id,
    )

    client.force_login(user)

    session = client.session
    session["active_organization_id"] = str(
        organization_a.id
    )
    session.save()

    return {
        "user": user,
        "organization_a": organization_a,
        "organization_b": organization_b,
        "subscription": subscription,
        "item_a": item_a,
        "item_b": item_b,
        "rule_b": rule_b,
        "report_b": report_b,
    }


def test_subscription_for_a_cannot_activate_b_even_with_membership(
    client,
    authority_context,
):
    organization_b = authority_context["organization_b"]

    response = client.post(
        reverse("organizations:workspace-activate"),
        {
            "organization_id": str(
                organization_b.id
            )
        },
    )

    assert response.status_code == 403
    assert "active_organization_id" not in client.session


def test_forged_active_workspace_is_cleared_before_tenant_activation(
    client,
    authority_context,
):
    organization_b = authority_context["organization_b"]

    session = client.session
    session["active_organization_id"] = str(
        organization_b.id
    )
    session.save()

    response = client.get(
        reverse("inventory:list")
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "organizations:workspace-selection"
    )
    assert "active_organization_id" not in client.session


def test_workspace_selection_exposes_only_subscription_bound_organization(
    client,
    authority_context,
):
    response = client.get(
        reverse("organizations:workspace-selection")
    )

    assert response.status_code == 200
    assert b"Paid Firm A" in response.content
    assert b"Member Firm B" not in response.content


def test_foreign_inventory_uuid_is_not_authorized_by_membership_alone(
    client,
    authority_context,
):
    item_b = authority_context["item_b"]

    response = client.get(
        reverse(
            "inventory:detail",
            args=(item_b.id,),
        )
    )

    assert response.status_code == 404


def test_foreign_rule_uuid_is_not_authorized_by_membership_alone(
    client,
    authority_context,
):
    rule_b = authority_context["rule_b"]

    response = client.get(
        reverse(
            "policies:detail",
            args=(rule_b.id,),
        )
    )

    assert response.status_code == 404


def test_foreign_report_uuid_is_not_authorized_by_membership_alone(
    client,
    authority_context,
):
    report_b = authority_context["report_b"]

    detail = client.get(
        reverse(
            "reports:detail",
            args=(report_b.id,),
        )
    )

    download = client.get(
        reverse(
            "reports:download",
            kwargs={
                "report_id": report_b.id,
            },
        )
    )

    assert detail.status_code == 404
    assert download.status_code == 404


def test_bound_core_subscription_cannot_create_second_workspace(
    client,
    authority_context,
):
    user = authority_context["user"]

    response = client.get(
        reverse("organizations:setup")
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "organizations:workspace-selection"
    )

    before = Organization.objects.count()

    with pytest.raises(
        PermissionDenied,
        match="already assigned",
    ):
        _create_and_bind_owned_workspace(
            user=user,
            name="Forbidden Second Firm",
            industry=Organization.Industry.OTHER,
        )

    assert Organization.objects.count() == before
    assert not Organization.objects.filter(
        name="Forbidden Second Firm"
    ).exists()


def test_paid_unbound_subscription_creates_and_binds_exactly_one_workspace():
    user = get_user_model().objects.create_user(
        "unbound-paid@example.com",
        "Strong!UnboundPaid98",
    )

    subscription = make_subscription(user)

    organization_id = _create_and_bind_owned_workspace(
        user=user,
        name="First Paid Firm",
        industry=Organization.Industry.ACCOUNTING_BOOKKEEPING,
    )

    subscription.refresh_from_db()

    assert subscription.organization_id == organization_id

    membership = OrganizationMember.objects.get(
        user=user,
        organization_id=organization_id,
    )

    assert membership.role == OrganizationMember.Role.OWNER

    before = Organization.objects.count()

    with pytest.raises(
        PermissionDenied,
        match="already assigned",
    ):
        _create_and_bind_owned_workspace(
            user=user,
            name="Second Paid Firm",
            industry=Organization.Industry.OTHER,
        )

    assert Organization.objects.count() == before
    assert not Organization.objects.filter(
        name="Second Paid Firm"
    ).exists()


def test_workspace_creation_and_subscription_binding_are_one_transaction(
    monkeypatch,
):
    user = get_user_model().objects.create_user(
        "rollback-paid@example.com",
        "Strong!RollbackPaid98",
    )

    subscription = make_subscription(user)

    original_save = Subscription.save

    def fail_bound_subscription_save(self, *args, **kwargs):
        if self.organization_id is not None:
            raise RuntimeError(
                "injected subscription bind failure"
            )

        return original_save(
            self,
            *args,
            **kwargs,
        )

    monkeypatch.setattr(
        Subscription,
        "save",
        fail_bound_subscription_save,
    )

    before_organizations = Organization.objects.count()
    before_memberships = OrganizationMember.objects.count()

    with pytest.raises(
        RuntimeError,
        match="injected subscription bind failure",
    ):
        _create_and_bind_owned_workspace(
            user=user,
            name="Must Roll Back",
            industry=Organization.Industry.OTHER,
        )

    subscription.refresh_from_db()

    assert subscription.organization_id is None
    assert Organization.objects.count() == before_organizations
    assert OrganizationMember.objects.count() == before_memberships
    assert not Organization.objects.filter(
        name="Must Roll Back"
    ).exists()


def test_cancel_at_period_end_retains_only_bound_workspace_access(
    client,
    authority_context,
):
    subscription = authority_context["subscription"]
    organization_b = authority_context["organization_b"]

    subscription.status = Subscription.Status.CANCELING
    subscription.cancel_at_period_end = True
    subscription.save(
        update_fields=[
            "status",
            "cancel_at_period_end",
            "updated_at",
        ]
    )

    authorized = client.get(
        reverse("inventory:list")
    )

    assert authorized.status_code == 200

    denied = client.post(
        reverse("organizations:workspace-activate"),
        {
            "organization_id": str(
                organization_b.id
            )
        },
    )

    assert denied.status_code == 403
    assert "active_organization_id" not in client.session


def test_authenticated_unpaid_user_cannot_reach_product_routes(
    client,
):
    user = get_user_model().objects.create_user(
        "unpaid@example.com",
        "Strong!Unpaid98",
    )

    client.force_login(user)

    response = client.get(
        reverse("inventory:list")
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "billing:portfolio"
    )


def test_canceled_subscription_cannot_reach_bound_workspace(
    client,
    authority_context,
):
    subscription = authority_context["subscription"]

    subscription.status = Subscription.Status.CANCELED
    subscription.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    response = client.get(
        reverse("inventory:list")
    )

    assert response.status_code == 302
    assert response.url == reverse(
        "billing:portfolio"
    )
