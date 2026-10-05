from __future__ import annotations

import os

import pytest
from django.db import DatabaseError, transaction

from agentledger.tenancy.context import tenant_transaction
from apps.accounts.models import User
from apps.catalog.models import Product, Vendor
from apps.inventory.models import DetectionEvidence, DiscoveryScan, InventoryItem
from apps.organizations.models import Organization
from apps.policies.models import OrganizationRule
from collector.contract import fingerprint
from tests.test_collector import example_bundle

pytestmark = [
    pytest.mark.rls,
    pytest.mark.skipif(
        os.getenv("AGENTLEDGER_RLS_TESTS") != "1",
        reason="restricted-role harness required",
    ),
    pytest.mark.django_db(
        transaction=True, databases={"default", "app_runtime", "worker_runtime"}
    ),
]


@pytest.fixture
def evidence_fixture():
    org_a = Organization.objects.create(name="Evidence A")
    org_b = Organization.objects.create(name="Evidence B")
    bundle = example_bundle()
    with tenant_transaction(org_a.id, using="app_runtime"):
        scan = DiscoveryScan.objects.using("app_runtime").create(
            organization_id=org_a.id,
            scan_hash=bundle["scan_id"],
            device_id=bundle["device_id"],
            observed_at=bundle["observed_at"],
            bundle=bundle,
        )
        record = bundle["evidence"][0]
        evidence = DetectionEvidence.objects.using("app_runtime").create(
            organization_id=org_a.id,
            scan_id=scan.id,
            fingerprint=fingerprint(record),
            evidence_hash=record["evidence_hash"],
            record=record,
        )
    return org_a, org_b, scan, evidence


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_evidence_and_scan_are_tenant_isolated(evidence_fixture, using):
    org_a, org_b, scan, evidence = evidence_fixture
    with tenant_transaction(org_a.id, using=using):
        assert list(
            DiscoveryScan.objects.using(using).values_list("id", flat=True)
        ) == [scan.id]
        assert list(
            DetectionEvidence.objects.using(using).values_list("id", flat=True)
        ) == [evidence.id]
    with tenant_transaction(org_b.id, using=using):
        assert not DiscoveryScan.objects.using(using).exists()
        assert not DetectionEvidence.objects.using(using).exists()


def test_evidence_cannot_reference_another_tenants_scan(evidence_fixture):
    _a, org_b, scan, evidence = evidence_fixture
    with pytest.raises(DatabaseError):
        with tenant_transaction(org_b.id, using="app_runtime"):
            DetectionEvidence.objects.using("app_runtime").create(
                organization_id=org_b.id,
                scan_id=scan.id,
                fingerprint=evidence.fingerprint,
                evidence_hash=evidence.evidence_hash,
                record=evidence.record,
            )


@pytest.mark.parametrize("model", [DiscoveryScan, DetectionEvidence])
def test_runtime_cannot_rewrite_or_delete_historical_evidence(evidence_fixture, model):
    org_a, *_ = evidence_fixture
    with pytest.raises(DatabaseError):
        with tenant_transaction(org_a.id, using="app_runtime"):
            model.objects.using("app_runtime").all().delete()
    with pytest.raises(DatabaseError):
        with tenant_transaction(org_a.id, using="app_runtime"):
            model.objects.using("app_runtime").all().update(organization_id=org_a.id)


def test_worker_cannot_insert_a_scan(evidence_fixture):
    org_a, _b, scan, _evidence = evidence_fixture
    with pytest.raises(DatabaseError):
        with transaction.atomic(using="worker_runtime"):
            with tenant_transaction(org_a.id, using="worker_runtime"):
                DiscoveryScan.objects.using("worker_runtime").create(
                    organization_id=org_a.id,
                    scan_hash="f" * 64,
                    device_id=scan.device_id,
                    observed_at=scan.observed_at,
                    bundle=scan.bundle,
                )


def test_reconciliation_cannot_reference_another_tenants_inventory(
    evidence_fixture,
):
    org_a, org_b, _scan, _evidence = evidence_fixture
    vendor = Vendor.objects.create(name="Cross-tenant vendor")
    product = Product.objects.create(
        vendor=vendor,
        name="Cross-tenant product",
        category="Test",
    )
    foreign_item = InventoryItem.objects.create(
        organization=org_a,
        product=product,
        display_name=product.name,
        vendor_name=vendor.name,
    )
    bundle = example_bundle()
    with tenant_transaction(org_b.id, using="app_runtime"):
        own_scan = DiscoveryScan.objects.using("app_runtime").create(
            organization_id=org_b.id,
            scan_hash="a" * 64,
            device_id=bundle["device_id"],
            observed_at=bundle["observed_at"],
            bundle=bundle,
        )
    record = bundle["evidence"][0]
    with pytest.raises(DatabaseError):
        with tenant_transaction(org_b.id, using="app_runtime"):
            DetectionEvidence.objects.using("app_runtime").create(
                organization_id=org_b.id,
                scan_id=own_scan.id,
                fingerprint=fingerprint(record),
                evidence_hash=record["evidence_hash"],
                record=record,
                reconciliation_status="reconciled",
                reconciliation_reason="exact_verified_identifier",
                matched_identifier_type="product_name",
                matched_product_id=product.id,
                inventory_item_id=foreign_item.id,
            )


def test_detector_rule_cannot_reference_another_tenants_inventory(
    evidence_fixture,
):
    org_a, org_b, _scan, _evidence = evidence_fixture
    user = User.objects.create_user("cross-tenant-rule@example.com")
    foreign_item = InventoryItem.objects.create(
        organization=org_a,
        display_name="Foreign inventory",
        vendor_name="Foreign vendor",
    )
    with pytest.raises(DatabaseError):
        with tenant_transaction(org_b.id, using="app_runtime"):
            OrganizationRule.objects.using("app_runtime").create(
                organization_id=org_b.id,
                name="Cross-tenant detector rule",
                definition={
                    "all": [
                        {"field": "department", "operator": "equals", "value": "Tax"}
                    ],
                    "effects": [{"type": "recommend_review", "message": "Review it."}],
                },
                explanation="Must fail.",
                remediation="Must fail.",
                source_type="detector",
                generation_fingerprint="b" * 64,
                source_inventory_item_id=foreign_item.id,
                detector_id="windows.installed_programs",
                detector_version="1",
                mapping_id="test.mapping",
                mapping_version="1",
                created_by_id=user.id,
            )
