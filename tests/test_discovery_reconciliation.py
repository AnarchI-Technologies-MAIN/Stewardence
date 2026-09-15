from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.assessments.snapshots import create_assessment_snapshot
from apps.audit.models import AuditEvent
from apps.catalog.matching import CatalogMatch
from apps.catalog.models import Product, ProductIdentifier, Vendor
from apps.inventory.discovery import ingest_bundle
from apps.inventory.models import DetectionEvidence, DiscoveryScan, InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.policies.context import inventory_policy_context
from apps.policies.detector_mappings import (
    MAPPING_REGISTRY_VERSION,
    SUPPORTED_AI_PRODUCT_MAPPINGS,
)
from apps.policies.engine import PolicyResult, evaluate_rule
from apps.policies.models import OrganizationRule
from apps.policies.organization_rules import compile_organization_rule
from apps.reports.context import build_report_context
from apps.reports.services import create_report
from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs
from collector.contract import digest
from tests.conftest import grant_core_entitlement
from tests.test_collector import encoded, example_bundle

pytestmark = pytest.mark.django_db


@pytest.fixture
def reconciliation_context(django_user_model):
    user = django_user_model.objects.create_user("collector-owner@example.com")
    organization = Organization.objects.create(name="Collector firm")
    OrganizationMember.objects.create(
        user=user,
        organization=organization,
        role=OrganizationMember.Role.OWNER,
    )
    vendor = Vendor.objects.create(name="OpenAI")
    product = Product.objects.create(
        vendor=vendor,
        name="ChatGPT",
        category="General assistant",
    )
    ProductIdentifier.objects.create(
        product=product,
        identifier_type=ProductIdentifier.Type.PRODUCT_NAME,
        raw_value="ChatGPT",
        verified=True,
    )
    return user, organization, product


def later_bundle(*, include_record=True):
    bundle = deepcopy(example_bundle())
    observed_at = "2026-09-05T01:00:00+00:00"
    bundle["observed_at"] = observed_at
    if include_record:
        record = bundle["evidence"][0]
        record["observed_at"] = observed_at
        record["evidence_hash"] = digest(
            {key: value for key, value in record.items() if key != "evidence_hash"}
        )
    else:
        bundle["evidence"] = []
    bundle["scan_id"] = digest(
        {key: value for key, value in bundle.items() if key != "scan_id"}
    )
    return bundle


def activate_client(client, user, organization):
    grant_core_entitlement(user, organization)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()


def test_exact_match_creates_discovered_inventory_rule_and_audit_once(
    reconciliation_context,
):
    user, organization, product = reconciliation_context
    first, created = ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    second, repeated = ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )

    assert created and not repeated and second.id == first.id
    evidence = DetectionEvidence.objects.get()
    item = InventoryItem.objects.get()
    rule = OrganizationRule.objects.get()
    assert evidence.reconciliation_status == "reconciled"
    assert evidence.reconciliation_reason == "exact_verified_identifier"
    assert evidence.matched_product == product
    assert evidence.inventory_item == item
    assert item.source_type == "discovered"
    assert item.discovery_fingerprint and item.product == product
    assert item.monthly_cost_cents == 0 and item.permissions == []
    assert rule.source_type == "detector"
    assert rule.source_inventory_item == item
    assert rule.detector_id == "windows.installed_programs"
    assert rule.detector_version == "1"
    assert rule.mapping_version == MAPPING_REGISTRY_VERSION
    assert rule.generation_fingerprint
    evaluation = evaluate_rule(
        compile_organization_rule(rule), inventory_policy_context(item)
    )
    assert evaluation.result is PolicyResult.WARNING
    assert set(AuditEvent.objects.values_list("event_type", flat=True)) == {
        "discovery.completed",
        "reconciliation.accepted",
    }


def test_later_scan_does_not_duplicate_inventory_or_detector_rule(
    reconciliation_context,
):
    user, organization, _product = reconciliation_context
    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(later_bundle()),
    )
    assert DiscoveryScan.objects.count() == 2
    assert DetectionEvidence.objects.count() == 2
    assert InventoryItem.objects.count() == 1
    assert OrganizationRule.objects.count() == 1


def test_manual_inventory_and_rule_are_reused_or_left_unchanged(
    reconciliation_context,
):
    user, organization, product = reconciliation_context
    item = InventoryItem.objects.create(
        organization=organization,
        product=product,
        display_name="Our approved ChatGPT workspace",
        vendor_name="OpenAI",
        business_owner="Firm owner",
        source_type=InventoryItem.SourceType.MANUAL,
    )
    manual = OrganizationRule.objects.create(
        organization=organization,
        name="Review detected ChatGPT",
        definition={
            "all": [{"field": "department", "operator": "equals", "value": "Tax"}],
            "effects": [{"type": "recommend_review", "message": "Human rule."}],
        },
        explanation="A person created this rule.",
        remediation="Keep the human wording.",
        created_by=user,
    )

    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    manual.refresh_from_db()
    assert InventoryItem.objects.count() == 1
    assert DetectionEvidence.objects.get().inventory_item == item
    assert manual.source_type == "manual"
    assert manual.explanation == "A person created this rule."
    assert OrganizationRule.objects.filter(source_type="detector").count() == 1


@pytest.mark.parametrize(
    ("catalog_match", "expected_status"),
    [
        (
            CatalogMatch(status="unknown", reason="no_exact_verified_identifier"),
            "unknown",
        ),
        (
            CatalogMatch(status="review", reason="conflicting_exact_identifiers"),
            "review",
        ),
    ],
)
def test_unknown_and_conflicting_evidence_are_not_classified(
    monkeypatch,
    reconciliation_context,
    catalog_match,
    expected_status,
):
    user, organization, _product = reconciliation_context
    monkeypatch.setattr(
        "apps.inventory.discovery.match_product", lambda _candidates: catalog_match
    )
    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    evidence = DetectionEvidence.objects.get()
    assert evidence.reconciliation_status == expected_status
    assert evidence.matched_product_id is None
    assert evidence.inventory_item_id is None
    assert not InventoryItem.objects.exists()
    assert not OrganizationRule.objects.exists()
    assert list(AuditEvent.objects.values_list("event_type", flat=True)) == [
        "discovery.completed"
    ]


def test_latest_complete_scan_represents_disappearance_without_erasing_history(
    client,
    reconciliation_context,
):
    user, organization, _product = reconciliation_context
    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(later_bundle(include_record=False)),
    )
    activate_client(client, user, organization)

    page = client.get(reverse("inventory:discovery"))

    assert page.status_code == 200
    assert b"Not observed in this device's latest complete scan" in page.content
    assert b"Historical evidence is retained" in page.content
    assert DiscoveryScan.objects.count() == 2
    assert DetectionEvidence.objects.count() == 1


def test_detector_rule_ui_preserves_provenance_and_disallows_rewrite(
    client,
    reconciliation_context,
):
    user, organization, _product = reconciliation_context
    ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    rule = OrganizationRule.objects.get()
    activate_client(client, user, organization)

    page = client.get(reverse("policies:detail", args=(rule.id,)))
    assert page.status_code == 200
    assert (
        b"Collector evidence matched a verified catalog product exactly" in page.content
    )
    assert rule.mapping_id.encode() in page.content
    assert rule.generation_fingerprint.encode() in page.content
    assert client.get(reverse("policies:edit", args=(rule.id,))).status_code == 403
    assert client.post(reverse("policies:delete", args=(rule.id,))).status_code == 403
    assert OrganizationRule.objects.filter(id=rule.id).exists()


def test_mapping_registry_is_versioned_and_immutable():
    assert MAPPING_REGISTRY_VERSION == "1"
    assert isinstance(SUPPORTED_AI_PRODUCT_MAPPINGS, tuple)
    assert len(
        {mapping.mapping_id for mapping in SUPPORTED_AI_PRODUCT_MAPPINGS}
    ) == len(SUPPORTED_AI_PRODUCT_MAPPINGS)


def test_reconciled_evidence_rule_and_calculation_lineage_reaches_report(
    reconciliation_context,
):
    user, organization, _product = reconciliation_context
    scan, _created = ingest_bundle(
        organization_id=organization.id,
        actor_user_id=user.id,
        raw=encoded(example_bundle()),
    )
    item = InventoryItem.objects.get()
    roi_inputs = ROIInputs(
        monthly_subscription_cost=Assumption(
            Decimal("0"), AssumptionProvenance.CUSTOMER_SUPPLIED
        ),
        implementation_cost=Assumption(
            Decimal("0"), AssumptionProvenance.CUSTOMER_SUPPLIED
        ),
        implementation_amortization_months=Assumption(
            12, AssumptionProvenance.ESTIMATED
        ),
        hours_saved_per_month=Assumption(Decimal("0"), AssumptionProvenance.MEASURED),
        loaded_hourly_rate=Assumption(
            Decimal("0"), AssumptionProvenance.CUSTOMER_SUPPLIED
        ),
        attributable_revenue=Assumption(Decimal("0"), AssumptionProvenance.ESTIMATED),
        avoided_monthly_cost=Assumption(Decimal("0"), AssumptionProvenance.MEASURED),
    )
    snapshot = create_assessment_snapshot(
        organization_id=organization.id,
        created_by_id=user.id,
        assessed_item_id=item.id,
        roi_inputs=roi_inputs,
        captured_at=scan.received_at + timedelta(microseconds=1),
    )
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    context = build_report_context(report)

    snapshot_item = snapshot.input_payload["inventory"][0]
    assert snapshot_item["provenance"] == {
        "autonomy_level": "Unknown",
        "business_owner": "Unknown",
        "business_purpose": "Unknown",
        "capabilities": "Unknown",
        "connected_systems": "Unknown",
        "data_categories": "Unknown",
        "department": "Unknown",
        "display_name": "Catalog-derived",
        "human_approval": "Unknown",
        "monthly_cost_cents": "Unknown",
        "permissions": "Unknown",
        "product_id": "Catalog-derived",
        "seat_count": "Unknown",
        "source_type": "Observed",
        "status": "Unknown",
        "user_count": "Unknown",
        "vendor_name": "Catalog-derived",
    }
    evidence = snapshot.input_payload["evidence_references"][0]
    assert evidence["provenance"] == "Observed"
    assert evidence["reconciliation_provenance"] == "Catalog-derived"
    assert evidence["reference"] == DetectionEvidence.objects.get().evidence_hash

    rule = snapshot.input_payload["rulesets"]["organization"][0]
    assert rule["source_type"] == "detector"
    assert rule["source_inventory_item_id"] == str(item.id)
    assert rule["generation_fingerprint"]
    assert rule["detector_id"] == "windows.installed_programs"
    assert rule["mapping_version"] == MAPPING_REGISTRY_VERSION

    assert context["inventory"][0]["monthly_cost_display"] == "Unknown"
    assert context["ai_expenditure"]["monthly_total_display"] == (
        "$0.00 known + 1 unknown tool"
    )
    assert context["risk_overview"]["highest_individual_risk"]
    assert context["individual_risk_findings"][0]["provenance"] == "Calculated"
    assert context["roi"]["result"]["provenance"] == "Calculated"
    assert context["evidence"][0]["reference"] == evidence["reference"]
    assert "paid subscription" in context["methodology"]["evidence_boundary"]
    assert "observed permissions" in context["methodology"]["evidence_boundary"]
    assert set(context["methodology"]["provenance_legend"]) == {
        "Observed",
        "Declared",
        "Catalog-derived",
        "Calculated",
        "Unknown",
    }
