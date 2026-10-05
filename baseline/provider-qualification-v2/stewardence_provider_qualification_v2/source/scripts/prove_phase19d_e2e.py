from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPOSITORY), str(REPOSITORY / "src")]
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "agentledger.settings.development")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402

from apps.assessments.snapshots import create_assessment_snapshot  # noqa: E402
from apps.inventory.discovery import ingest_bundle  # noqa: E402
from apps.inventory.models import DetectionEvidence, InventoryItem  # noqa: E402
from apps.organizations.models import Organization, OrganizationMember  # noqa: E402
from apps.policies.models import OrganizationRule  # noqa: E402
from apps.reports.context import build_report_context  # noqa: E402
from apps.reports.services import create_report  # noqa: E402
from apps.roi.engine import Assumption, AssumptionProvenance, ROIInputs  # noqa: E402
from collector.contract import validate_bundle  # noqa: E402
from renderer.render import render_pdf  # noqa: E402


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def roi_inputs() -> ROIInputs:
    declared = AssumptionProvenance.CUSTOMER_SUPPLIED
    measured = AssumptionProvenance.MEASURED
    estimated = AssumptionProvenance.ESTIMATED
    return ROIInputs(
        monthly_subscription_cost=Assumption(Decimal("0"), declared),
        implementation_cost=Assumption(Decimal("0"), declared),
        implementation_amortization_months=Assumption(12, estimated),
        hours_saved_per_month=Assumption(Decimal("0"), measured),
        loaded_hourly_rate=Assumption(Decimal("0"), declared),
        attributable_revenue=Assumption(Decimal("0"), estimated),
        avoided_monthly_cost=Assumption(Decimal("0"), measured),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--release-archive", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()

    bundle_bytes = args.bundle.read_bytes()
    bundle = validate_bundle(bundle_bytes)
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)

    proof = None
    pdf_bytes = None
    with transaction.atomic():
        user = get_user_model().objects.create_user(
            f"phase19d-{bundle['scan_id'][:12]}@example.invalid"
        )
        organization = Organization.objects.create(name="Phase 19D proof workspace")
        OrganizationMember.objects.create(
            user=user,
            organization=organization,
            role=OrganizationMember.Role.OWNER,
        )
        scan, created = ingest_bundle(
            organization_id=organization.id,
            actor_user_id=user.id,
            raw=bundle_bytes,
        )
        if not created:
            raise RuntimeError("Proof scan unexpectedly reused an existing row")

        detector_rule = (
            OrganizationRule.objects.filter(
                organization=organization,
                source_type=OrganizationRule.SourceType.DETECTOR,
            )
            .select_related("source_inventory_item")
            .first()
        )
        if detector_rule is None:
            raise RuntimeError(
                "The real scan produced no supported deterministic detector rule"
            )
        item = detector_rule.source_inventory_item
        snapshot = create_assessment_snapshot(
            organization_id=organization.id,
            created_by_id=user.id,
            assessed_item_id=item.id,
            roi_inputs=roi_inputs(),
            captured_at=datetime.now(UTC),
        )
        report = create_report(
            organization_id=organization.id,
            assessment_snapshot_id=snapshot.id,
            created_by_id=user.id,
        )
        context = build_report_context(report)
        pdf_bytes = render_pdf(context, output_directory=output / "renderer-work")
        reconciled = DetectionEvidence.objects.filter(
            organization=organization,
            reconciliation_status=DetectionEvidence.ReconciliationStatus.RECONCILED,
        )
        proof = {
            "assessment_input_sha256": snapshot.input_sha256,
            "assessment_result_sha256": snapshot.result_sha256,
            "automatic_rule_count": OrganizationRule.objects.filter(
                organization=organization,
                source_type=OrganizationRule.SourceType.DETECTOR,
            ).count(),
            "collector_version": bundle["collector_version"],
            "context_version": context["context_version"],
            "evidence_reference_count": len(context["evidence"]),
            "inventory_count": InventoryItem.objects.filter(
                organization=organization
            ).count(),
            "matched_products": sorted(
                set(reconciled.values_list("matched_product__name", flat=True))
            ),
            "observation_count": len(bundle["evidence"]),
            "pdf_sha256": sha256_bytes(pdf_bytes),
            "pdf_size": len(pdf_bytes),
            "pipeline": [
                "packaged_collector_scan",
                "validated_evidence_ingestion",
                "exact_catalog_reconciliation",
                "discovered_inventory",
                "deterministic_detector_rule",
                "immutable_assessment_snapshot",
                "canonical_report_context",
                "rendered_pdf",
            ],
            "provenance_labels": sorted(context["methodology"]["provenance_legend"]),
            "reconciled_observation_count": reconciled.count(),
            "release_archive_sha256": sha256_bytes(args.release_archive.read_bytes()),
            "report_identifier": report.report_identifier,
            "scan_id": str(scan.id),
            "source_bundle_sha256": sha256_bytes(bundle_bytes),
            "transaction_rolled_back": True,
        }
        transaction.set_rollback(True)

    if proof is None or pdf_bytes is None:
        raise RuntimeError("Phase 19D proof did not complete")
    (output / "phase19d-proof.pdf").write_bytes(pdf_bytes)
    (output / "phase19d-proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(proof, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
