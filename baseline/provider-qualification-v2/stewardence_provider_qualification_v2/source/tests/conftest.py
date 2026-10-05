from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.assessments.snapshots import create_assessment_snapshot
from apps.billing.models import BillingCustomer, Subscription
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs


def _assumption(
    value,
    provenance=AssumptionProvenance.CUSTOMER_SUPPLIED,
):
    return Assumption(Decimal(str(value)), provenance)


def grant_core_entitlement(user, organization):
    billing_customer, _ = BillingCustomer.objects.get_or_create(
        user=user,
    )

    subscription, _ = Subscription.objects.get_or_create(
        billing_customer=billing_customer,
        defaults={
            "organization": organization,
            "portfolio": Subscription.Portfolio.CORE,
            "status": Subscription.Status.ACTIVE,
            "current_price_cents": 9900,
        },
    )

    changed = []

    if subscription.organization_id != organization.id:
        subscription.organization = organization
        changed.append("organization")

    if subscription.portfolio != Subscription.Portfolio.CORE:
        subscription.portfolio = Subscription.Portfolio.CORE
        changed.append("portfolio")

    if subscription.status != Subscription.Status.ACTIVE:
        subscription.status = Subscription.Status.ACTIVE
        changed.append("status")

    if subscription.current_price_cents != 9900:
        subscription.current_price_cents = 9900
        changed.append("current_price_cents")

    if changed:
        changed.append("updated_at")
        subscription.save(update_fields=changed)

    return subscription


def _roi_inputs():
    return ROIInputs(
        monthly_subscription_cost=_assumption("100.00"),
        implementation_cost=_assumption("1200.00"),
        implementation_amortization_months=Assumption(
            12,
            AssumptionProvenance.ESTIMATED,
        ),
        hours_saved_per_month=_assumption(
            "10.00",
            AssumptionProvenance.MEASURED,
        ),
        loaded_hourly_rate=_assumption("50.00"),
        attributable_revenue=_assumption(
            "200.00",
            AssumptionProvenance.ESTIMATED,
        ),
        avoided_monthly_cost=_assumption(
            "100.00",
            AssumptionProvenance.MEASURED,
        ),
    )


@pytest.fixture
def report_context(client):
    user = get_user_model().objects.create_user("reports@example.com")
    organization = Organization.objects.create(name="Report Firm")
    membership = OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Payroll Assistant",
        vendor_name="Example Vendor",
        department="Bookkeeping",
        monthly_cost_cents=10000,
        data_categories=["payroll"],
        capabilities=["external_transfer"],
        human_approval=False,
    )
    snapshot = create_assessment_snapshot(
        organization_id=organization.id,
        created_by_id=user.id,
        assessed_item_id=item.id,
        roi_inputs=_roi_inputs(),
        captured_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        evidence_references=(
            {
                "reference": "EVIDENCE-1",
                "type": "customer_statement",
            },
        ),
    )

    grant_core_entitlement(user, organization)

    client.force_login(user)

    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()

    return user, organization, membership, item, snapshot


@pytest.fixture
def shared_roi_inputs():
    return _roi_inputs
