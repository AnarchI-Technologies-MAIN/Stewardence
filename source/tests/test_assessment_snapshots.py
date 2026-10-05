from __future__ import annotations

import copy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.urls import reverse

from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import (
    canonical_bytes,
    canonical_sha256,
    create_assessment_snapshot,
    verify_snapshot,
)
from apps.audit.models import AuditEvent
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.policies.models import OrganizationRule
from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs
from tests.conftest import grant_core_entitlement

pytestmark = pytest.mark.django_db


def assumption(value, provenance=AssumptionProvenance.CUSTOMER_SUPPLIED):
    return Assumption(Decimal(str(value)), provenance)


def roi_inputs(hours="10.00"):
    return ROIInputs(
        monthly_subscription_cost=assumption("100.00"),
        implementation_cost=assumption("1200.00"),
        implementation_amortization_months=Assumption(
            12, AssumptionProvenance.ESTIMATED
        ),
        hours_saved_per_month=assumption(hours, AssumptionProvenance.MEASURED),
        loaded_hourly_rate=assumption("50.00"),
        attributable_revenue=assumption("200.00", AssumptionProvenance.ESTIMATED),
        avoided_monthly_cost=assumption("100.00", AssumptionProvenance.MEASURED),
    )


@pytest.fixture
def assessment_context():
    user = get_user_model().objects.create_user("assessment@example.com")
    organization = Organization.objects.create(name="Snapshot Firm")
    OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )
    item = InventoryItem.objects.create(
        organization=organization,
        display_name="Payroll Assistant",
        vendor_name="Example Vendor",
        monthly_cost_cents=10000,
        data_categories=["payroll"],
        capabilities=["external_transfer"],
        human_approval=False,
    )
    return user, organization, item


def create_snapshot(user, organization, item, **overrides):
    values = {
        "organization_id": organization.id,
        "created_by_id": user.id,
        "assessed_item_id": item.id,
        "roi_inputs": roi_inputs(),
        "captured_at": datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        "evidence_references": (
            {"reference": "EVIDENCE-1", "type": "customer_statement"},
        ),
    }
    values.update(overrides)
    return create_assessment_snapshot(**values)


def test_rfc8785_hash_is_independent_of_mapping_key_order():
    first = {"b": 2, "a": {"second": 2, "first": 1}}
    second = {"a": {"first": 1, "second": 2}, "b": 2}

    assert canonical_bytes(first) == canonical_bytes(second)
    assert canonical_sha256(first) == canonical_sha256(second)


def test_snapshot_captures_complete_versioned_input_results_and_hashes(
    assessment_context,
):
    user, organization, item = assessment_context

    snapshot = create_snapshot(user, organization, item)

    assert snapshot.version == 1
    assert snapshot.input_payload["assessment"] == {
        "id": str(snapshot.assessment_id),
        "version": 1,
    }
    assert snapshot.input_payload["captured_at"] == "2026-09-03T12:00:00Z"
    assert snapshot.input_payload["inventory"][0]["display_name"] == (
        "Payroll Assistant"
    )
    assert snapshot.input_payload["evidence_references"] == [
        {"reference": "EVIDENCE-1", "type": "customer_statement"}
    ]
    assert snapshot.input_payload["rulesets"] == {
        "platform": "not_published",
        "industry": {"name": "accounting_and_bookkeeping", "version": "1.1.0"},
        "organization": [],
    }
    assert snapshot.input_payload["risk_configuration"]["version"] == "AL-RISK-1"
    assert len(snapshot.input_payload["risk_configuration"]["weights"]) == 8
    assert snapshot.input_payload["roi"]["assumptions"]["hours_saved_per_month"] == {
        "value": "10.00",
        "provenance": "Measured",
    }
    assert snapshot.input_payload["engine_versions"] == {
        "policy": "AL-POLICY-1",
        "risk": "AL-RISK-1",
        "roi": "AL-ROI-1",
    }
    assert snapshot.result_payload["inventory_results"][0]["risk"]["score"] == 75
    assert snapshot.result_payload["roi"]["roi_percent"] == "300.00"
    assert len(snapshot.input_sha256) == 64
    assert len(snapshot.result_sha256) == 64
    assert verify_snapshot(snapshot)


def test_model_and_database_reject_snapshot_mutation_or_deletion(assessment_context):
    user, organization, item = assessment_context
    snapshot = create_snapshot(user, organization, item)

    snapshot.version = 2
    with pytest.raises(ValidationError, match="immutable"):
        snapshot.save()
    with pytest.raises(ValidationError, match="immutable"):
        snapshot.delete()
    with pytest.raises(DatabaseError, match="immutable"):
        with transaction.atomic():
            AssessmentSnapshot.objects.filter(pk=snapshot.pk).update(version=2)
    with pytest.raises(DatabaseError, match="immutable"):
        with transaction.atomic():
            AssessmentSnapshot.objects.filter(pk=snapshot.pk).delete()


def test_bad_payload_hash_is_rejected_before_insert(assessment_context):
    user, organization, _item = assessment_context

    with pytest.raises(ValidationError, match="input hash"):
        AssessmentSnapshot.objects.create(
            organization=organization,
            created_by=user,
            captured_at=datetime(2026, 9, 3, tzinfo=UTC),
            input_payload={"value": 1},
            result_payload={"value": 2},
            input_sha256="0" * 64,
            result_sha256=canonical_sha256({"value": 2}),
        )


def test_yesterdays_snapshot_remains_identical_after_todays_changes(
    assessment_context,
):
    user, organization, item = assessment_context
    organization_rule = OrganizationRule.objects.create(
        organization=organization,
        name="Firm payroll review",
        definition={
            "all": [
                {
                    "field": "data_categories",
                    "operator": "contains",
                    "value": "payroll",
                },
                {
                    "field": "capabilities",
                    "operator": "contains",
                    "value": "external_transfer",
                },
            ],
            "effects": [{"type": "require_control", "control": "human_approval"}],
        },
        result_on_match=OrganizationRule.Result.FAIL,
        severity=OrganizationRule.Severity.HIGH,
        explanation="The firm requires a payroll transfer review.",
        remediation="Record the reviewer before information is sent.",
        created_by=user,
    )
    yesterday = create_snapshot(user, organization, item)
    original_input = copy.deepcopy(yesterday.input_payload)
    original_result = copy.deepcopy(yesterday.result_payload)
    original_hashes = (yesterday.input_sha256, yesterday.result_sha256)

    item.vendor_name = "Changed Vendor"
    item.capabilities = ["data_analysis"]
    item.human_approval = True
    item.save(update_fields=("vendor_name", "capabilities", "human_approval"))
    organization_rule.version = 2
    organization_rule.explanation = "The firm's review wording changed today."
    organization_rule.save(update_fields=("version", "explanation", "updated_at"))
    today = create_snapshot(
        user,
        organization,
        item,
        previous_snapshot=yesterday,
        roi_inputs=roi_inputs(hours="12.00"),
        captured_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )

    yesterday.refresh_from_db()
    assert yesterday.input_payload == original_input
    assert yesterday.result_payload == original_result
    assert (yesterday.input_sha256, yesterday.result_sha256) == original_hashes
    assert verify_snapshot(yesterday)
    assert today.assessment_id == yesterday.assessment_id
    assert today.version == 2
    assert today.input_sha256 != yesterday.input_sha256
    assert today.result_sha256 != yesterday.result_sha256
    assert yesterday.input_payload["rulesets"]["organization"][0]["version"] == 1
    assert today.input_payload["rulesets"]["organization"][0]["version"] == 2
    with pytest.raises(ValueError, match="latest version"):
        create_snapshot(
            user,
            organization,
            item,
            previous_snapshot=yesterday,
            captured_at=datetime(2026, 9, 4, 13, 0, tzinfo=UTC),
        )


def test_snapshot_requires_timezone_and_same_tenant_revision(assessment_context):
    user, organization, item = assessment_context
    with pytest.raises(ValueError, match="timezone"):
        create_snapshot(
            user,
            organization,
            item,
            captured_at=datetime(2026, 9, 3),
        )

    other_organization = Organization.objects.create(name="Other Snapshot Firm")
    other_item = InventoryItem.objects.create(
        organization=other_organization,
        display_name="Other Item",
        vendor_name="Other Vendor",
    )
    first = create_snapshot(user, organization, item)
    with pytest.raises(ValueError, match="same organization"):
        create_snapshot(
            user,
            other_organization,
            other_item,
            previous_snapshot=first,
        )


def test_roi_workflow_can_save_and_open_tenant_scoped_snapshot(
    client, assessment_context
):
    user, organization, item = assessment_context
    grant_core_entitlement(user, organization)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    payload = {
        "action": "save_snapshot",
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

    assert response.status_code == 302
    detail = client.get(response.url)
    assert detail.status_code == 200
    assert b"Immutable assessment" in detail.content
    assert b"Hashes match the stored snapshot" in detail.content
    assert b"AL-POLICY-1" in detail.content
    event = AuditEvent.objects.get()
    snapshot = AssessmentSnapshot.objects.get()
    assert event.event_type == "assessment.completed"
    assert event.entity_type == "assessment_snapshot"
    assert event.entity_id == snapshot.id
    assert event.actor_user_id == user.id
    assert event.data == {
        "assessment_id": str(snapshot.assessment_id),
        "input_sha256": snapshot.input_sha256,
        "result_sha256": snapshot.result_sha256,
        "version": "1",
    }


def test_viewer_cannot_save_snapshot(client, assessment_context):
    user, organization, item = assessment_context
    membership = OrganizationMember.objects.get(user=user, organization=organization)
    membership.role = OrganizationMember.Role.VIEWER
    membership.save(update_fields=("role",))
    grant_core_entitlement(user, organization)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()

    response = client.post(
        reverse("inventory:roi", args=(item.id,)),
        {
            "action": "save_snapshot",
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
        },
    )

    assert response.status_code == 403
    assert AssessmentSnapshot.objects.count() == 0
