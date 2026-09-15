from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts.models import User
from apps.inventory.discovery import ingest_bundle
from apps.inventory.models import DetectionEvidence, DiscoveryScan, InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from collector.contract import digest
from tests.conftest import grant_core_entitlement
from tests.test_collector import encoded, example_bundle

pytestmark = pytest.mark.django_db


def test_ingestion_is_idempotent_and_preserves_previous_observations():
    org = Organization.objects.create(name="Evidence firm")
    raw = encoded(example_bundle())
    first, created = ingest_bundle(organization_id=org.id, raw=raw)
    assert created
    second, created = ingest_bundle(organization_id=org.id, raw=raw)
    assert not created and first.id == second.id
    later = example_bundle()
    later["evidence"] = []
    later["observed_at"] = "2026-09-05T01:00:00Z"
    later["scan_id"] = digest({k: v for k, v in later.items() if k != "scan_id"})
    ingest_bundle(organization_id=org.id, raw=encoded(later))
    assert DiscoveryScan.objects.count() == 2
    assert DetectionEvidence.objects.count() == 1
    assert InventoryItem.objects.count() == 0


def test_evidence_upload_requires_membership_and_writer_role(client):
    assert client.get(reverse("inventory:discovery")).status_code == 302
    user = User.objects.create_user("viewer@example.com", "Strong!Password98")
    org = Organization.objects.create(name="View only")
    OrganizationMember.objects.create(user=user, organization=org, role="viewer")
    grant_core_entitlement(user, org)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    response = client.post(
        reverse("inventory:discovery"),
        {
            "bundle": SimpleUploadedFile("scan.json", encoded(example_bundle())),
        },
    )
    assert response.status_code == 403
    assert DiscoveryScan.objects.count() == 0


def test_valid_upload_records_only_current_tenant(client):
    user = User.objects.create_user("owner-discovery@example.com", "Strong!Password98")
    org = Organization.objects.create(name="Own firm")
    OrganizationMember.objects.create(user=user, organization=org, role="owner")
    grant_core_entitlement(user, org)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    response = client.post(
        reverse("inventory:discovery"),
        {
            "bundle": SimpleUploadedFile("scan.json", encoded(example_bundle())),
        },
    )
    assert response.status_code == 200
    assert DiscoveryScan.objects.get().organization_id == org.id
