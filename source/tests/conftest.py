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

    grant_paid_test_coverage(subscription)
    return subscription


def grant_paid_test_coverage(subscription):
    """Explicit synthetic payment fixture; never used by application code.

    Tests with an uncommitted outer transaction use its administrative
    connection and an explicit local role switch. Actual-login denial and
    issuance are qualified separately; this helper is not role-login proof.
    """
    import hashlib
    import json
    from uuid import uuid4

    from django.db import connection, transaction
    from django.utils import timezone
    from psycopg import sql

    from apps.billing.entitlements import issue_paid_coverage
    from apps.billing.models import PaidCoverageAuthority

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            original_role = cursor.fetchone()[0]
        if original_role not in {"postgres", "agentledger", "agentledger_owner"}:
            raise AssertionError(
                "Synthetic coverage requires administrative fixture setup"
            )
        customer = subscription.billing_customer
        if not customer.stripe_customer_id:
            customer.stripe_customer_id = "cus_qualification_" + customer.id.hex
            customer.save(update_fields=["stripe_customer_id", "updated_at"])
        if not subscription.stripe_subscription_id:
            subscription.stripe_subscription_id = (
                "sub_qualification_" + subscription.id.hex
            )
            subscription.save(update_fields=["stripe_subscription_id", "updated_at"])
        authority, _ = PaidCoverageAuthority.objects.get_or_create(
            id=1,
            defaults={
                "stripe_account_id": "acct_qualification",
                "livemode": False,
                "contracts": {
                    "standard": {
                        "price_id": "price_qualification_core_standard",
                        "amount_cents": 9900,
                        "contract_version": "core.monthly.v1",
                    }
                },
            },
        )
        phase = "standard"
        amount = 9900
        if subscription.is_founder:
            phase = (
                "founder_intro"
                if subscription.current_price_cents == 4900
                else "founder_ongoing"
            )
            amount = 4900 if phase == "founder_intro" else 7500
        if phase not in authority.contracts:
            authority.contracts[phase] = {
                "price_id": "price_qualification_core_" + phase,
                "amount_cents": amount,
                "contract_version": "core.monthly.v1",
            }
            authority.save(update_fields=["contracts"])
        contract = authority.contracts[phase]
        now = int(timezone.now().timestamp())
        identifier = uuid4().hex
        evidence = {
            "schema": "stewardence.paid_coverage.v1",
            "subscription_id": str(subscription.id),
            "stripe_subscription_id": subscription.stripe_subscription_id,
            "stripe_customer_id": customer.stripe_customer_id,
            "stripe_account_id": authority.stripe_account_id,
            "livemode": authority.livemode,
            "stripe_invoice_id": "in_qualification_" + identifier,
            "stripe_event_id": "evt_qualification_" + identifier,
            "contract_version": "core.monthly.v1",
            "phase": phase,
            "stripe_price_id": contract["price_id"],
            "amount_cents": amount,
            "currency": "usd",
            "service_start": now - 60,
            "service_end": now + 30 * 86400,
            "paid_at": now - 30,
        }
        evidence["evidence_sha256"] = hashlib.sha256(
            json.dumps(evidence, sort_keys=True).encode()
        ).hexdigest()
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE agentledger_billing_admission")
        try:
            return issue_paid_coverage(evidence, using="default")
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(original_role))
                )


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


def grant_queue_owner(organization):
    from uuid import uuid4

    user = get_user_model().objects.create_user(str(uuid4()) + "@queue.example.invalid")
    OrganizationMember.objects.create(
        user=user, organization=organization, role="owner"
    )
    grant_core_entitlement(user, organization)
    return user
