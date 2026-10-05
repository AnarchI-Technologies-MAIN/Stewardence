from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.assessments.snapshots import create_assessment_snapshot
from apps.inventory.models import InventoryItem
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.artifact_services import (
    ReportArtifactError,
    persist_pdf_artifact,
    read_verified_pdf_artifact,
)
from apps.reports.services import create_report
from apps.reports.storage import (
    PDF_CONTENT_TYPE,
    LocalPrivateReportStorage,
    ReportStorageError,
    build_pdf_object_key,
    sha256_hex,
)
from tests.conftest import _roi_inputs

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def artifact_report_context(report_context):
    user, organization, membership, item, snapshot = report_context

    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )

    return {
        "user": user,
        "organization": organization,
        "membership": membership,
        "item": item,
        "snapshot": snapshot,
        "report": report,
    }


def test_object_key_is_deterministically_tenant_snapshot_report_scoped():
    organization_id = uuid4()
    snapshot_id = uuid4()
    report_id = uuid4()

    assert build_pdf_object_key(
        organization_id=organization_id,
        assessment_snapshot_id=snapshot_id,
        report_id=report_id,
    ) == (
        f"organizations/{organization_id}/"
        f"assessments/{snapshot_id}/"
        f"reports/{report_id}.pdf"
    )


def test_local_private_storage_rejects_traversal(tmp_path):
    storage = LocalPrivateReportStorage(tmp_path)

    with pytest.raises(ReportStorageError):
        storage.put(
            key="../escape.pdf",
            content=b"%PDF-test",
            content_type=PDF_CONTENT_TYPE,
        )


def test_local_private_storage_rejects_non_pdf(tmp_path):
    storage = LocalPrivateReportStorage(tmp_path)

    with pytest.raises(ReportStorageError):
        storage.put(
            key="organizations/test/report.pdf",
            content=b"not-a-pdf",
            content_type=PDF_CONTENT_TYPE,
        )


def test_persisted_artifact_records_required_metadata(
    artifact_report_context, tmp_path
):
    report = artifact_report_context["report"]
    storage = LocalPrivateReportStorage(tmp_path)
    pdf = b"%PDF-1.7\nAgentLedger\n%%EOF\n"

    artifact = persist_pdf_artifact(
        report=report,
        pdf_bytes=pdf,
        storage=storage,
    )

    assert artifact.organization_id == report.organization_id
    assert artifact.report_id == report.id
    assert artifact.assessment_snapshot_id == report.assessment_snapshot_id
    assert artifact.content_type == PDF_CONTENT_TYPE
    assert artifact.sha256 == sha256_hex(pdf)
    assert artifact.size_bytes == len(pdf)
    assert artifact.object_key == (
        f"organizations/{report.organization_id}/"
        f"assessments/{report.assessment_snapshot_id}/"
        f"reports/{report.id}.pdf"
    )


def test_artifact_persistence_is_idempotent_for_identical_bytes(
    artifact_report_context,
    tmp_path,
):
    report = artifact_report_context["report"]
    storage = LocalPrivateReportStorage(tmp_path)
    pdf = b"%PDF-1.7\nsame\n%%EOF\n"

    first = persist_pdf_artifact(
        report=report,
        pdf_bytes=pdf,
        storage=storage,
    )
    second = persist_pdf_artifact(
        report=report,
        pdf_bytes=pdf,
        storage=storage,
    )

    assert second.id == first.id


def test_existing_artifact_rejects_different_bytes(artifact_report_context, tmp_path):
    report = artifact_report_context["report"]
    storage = LocalPrivateReportStorage(tmp_path)

    persist_pdf_artifact(
        report=report,
        pdf_bytes=b"%PDF-1.7\nfirst\n%%EOF\n",
        storage=storage,
    )

    with pytest.raises(ReportArtifactError):
        persist_pdf_artifact(
            report=report,
            pdf_bytes=b"%PDF-1.7\nsecond\n%%EOF\n",
            storage=storage,
        )


def test_read_verifies_hash_and_size(artifact_report_context, tmp_path):
    report = artifact_report_context["report"]
    storage = LocalPrivateReportStorage(tmp_path)
    pdf = b"%PDF-1.7\nverified\n%%EOF\n"

    artifact = persist_pdf_artifact(
        report=report,
        pdf_bytes=pdf,
        storage=storage,
    )

    assert (
        read_verified_pdf_artifact(
            artifact=artifact,
            storage=storage,
        )
        == pdf
    )

    path = Path(tmp_path) / artifact.object_key
    path.write_bytes(b"%PDF-1.7\ntampered\n%%EOF\n")

    with pytest.raises(ReportStorageError):
        read_verified_pdf_artifact(
            artifact=artifact,
            storage=storage,
        )


def test_authenticated_download_returns_verified_pdf(
    artifact_report_context,
    client,
    settings,
    tmp_path,
):
    report = artifact_report_context["report"]
    pdf = b"%PDF-1.7\nAgentLedger download\n%%EOF\n"

    settings.REPORTS_LOCAL_STORAGE_ROOT = tmp_path

    artifact = persist_pdf_artifact(
        report=report,
        pdf_bytes=pdf,
        storage=LocalPrivateReportStorage(tmp_path),
    )

    response = client.get(
        reverse(
            "reports:download",
            kwargs={"report_id": report.id},
        )
    )

    assert response.status_code == 200
    assert response.content == pdf
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Length"] == str(artifact.size_bytes)
    assert response["Cache-Control"] == "private, no-store"


def test_download_denies_other_tenant_report_even_with_report_uuid(
    artifact_report_context,
    client,
    settings,
    tmp_path,
):
    user = artifact_report_context["user"]
    organization_a = artifact_report_context["organization"]

    other_organization = Organization.objects.create(name="Other Firm")
    other_item = InventoryItem.objects.create(
        organization=other_organization,
        display_name="Other Tool",
        vendor_name="Other Vendor",
    )

    OrganizationMember.objects.create(
        user=user,
        organization=other_organization,
        role=OrganizationMember.Role.OWNER,
    )

    other_snapshot = create_assessment_snapshot(
        organization_id=other_organization.id,
        created_by_id=user.id,
        assessed_item_id=other_item.id,
        roi_inputs=_roi_inputs(),
        captured_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
    )

    other_report = create_report(
        organization_id=other_organization.id,
        assessment_snapshot_id=other_snapshot.id,
        created_by_id=user.id,
    )

    settings.REPORTS_LOCAL_STORAGE_ROOT = tmp_path

    other_artifact = persist_pdf_artifact(
        report=other_report,
        pdf_bytes=b"%PDF-1.7\nother tenant\n%%EOF\n",
        storage=LocalPrivateReportStorage(tmp_path),
    )

    session = client.session
    session["active_organization_id"] = str(organization_a.id)
    session.save()

    response = client.get(
        reverse(
            "reports:download",
            kwargs={"report_id": other_report.id},
        )
    )

    assert response.status_code == 404

    assert other_artifact.object_key.endswith(f"/reports/{other_report.id}.pdf")


def test_download_requires_current_membership(
    artifact_report_context,
    client,
    settings,
    tmp_path,
):
    report = artifact_report_context["report"]
    membership = artifact_report_context["membership"]

    settings.REPORTS_LOCAL_STORAGE_ROOT = tmp_path

    persist_pdf_artifact(
        report=report,
        pdf_bytes=b"%PDF-1.7\nmembership\n%%EOF\n",
        storage=LocalPrivateReportStorage(tmp_path),
    )

    membership.delete()

    response = client.get(
        reverse(
            "reports:download",
            kwargs={"report_id": report.id},
        )
    )

    assert response.status_code == 403


def test_download_returns_503_when_artifact_bytes_fail_integrity(
    artifact_report_context,
    client,
    settings,
    tmp_path,
):
    report = artifact_report_context["report"]
    pdf = b"%PDF-1.7\noriginal\n%%EOF\n"

    settings.REPORTS_LOCAL_STORAGE_ROOT = tmp_path

    artifact = persist_pdf_artifact(
        report=report,
        pdf_bytes=pdf,
        storage=LocalPrivateReportStorage(tmp_path),
    )

    path = Path(tmp_path) / artifact.object_key
    path.write_bytes(b"%PDF-1.7\ntampered\n%%EOF\n")

    response = client.get(
        reverse(
            "reports:download",
            kwargs={"report_id": report.id},
        )
    )

    assert response.status_code == 503
