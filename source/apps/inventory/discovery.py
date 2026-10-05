from __future__ import annotations

from django.db import transaction

from apps.audit.append import append_audit_event
from apps.audit.events import (
    EVENT_DISCOVERY_COMPLETED,
    EVENT_RECONCILIATION_ACCEPTED,
)
from apps.catalog.matching import CandidateIdentifier, match_product
from apps.catalog.models import Product, ProductIdentifier
from apps.policies.detector_mappings import instantiate_detector_rules
from collector.contract import digest, fingerprint, timestamp, validate_bundle

from .models import DetectionEvidence, DiscoveryScan, InventoryItem


def _inventory_fingerprint(product_id) -> str:
    return digest(
        {
            "reconciliation_registry_version": "1",
            "product_id": str(product_id),
        }
    )


def _reconcile_record(*, organization_id, record, created_by_id):
    match = match_product(
        [
            CandidateIdentifier(
                identifier_type=ProductIdentifier.Type.PRODUCT_NAME,
                raw_value=record["raw_identifier"],
            )
        ]
    )
    if match.status != "known":
        return {
            "status": match.status,
            "reason": match.reason,
            "identifier_type": "",
            "product": None,
            "inventory_item": None,
            "created_rules": (),
        }

    product = Product.objects.select_related("vendor").get(id=match.product_id)
    item = (
        InventoryItem.objects.filter(
            organization_id=organization_id,
            product=product,
            archived_at__isnull=True,
        )
        .order_by("source_type", "id")
        .first()
    )
    if item is None:
        item, _created = InventoryItem.objects.get_or_create(
            organization_id=organization_id,
            discovery_fingerprint=_inventory_fingerprint(product.id),
            defaults={
                "product": product,
                "display_name": product.name,
                "vendor_name": product.vendor.name,
                "status": InventoryItem.Status.REVIEWING,
                "source_type": InventoryItem.SourceType.DISCOVERED,
            },
        )
    created_rules = instantiate_detector_rules(
        organization_id=organization_id,
        inventory_item=item,
        detector_id=record["detector_id"],
        detector_version=record["detector_version"],
        created_by_id=created_by_id,
    )
    return {
        "status": DetectionEvidence.ReconciliationStatus.RECONCILED,
        "reason": match.reason,
        "identifier_type": match.identifier_type,
        "product": product,
        "inventory_item": item,
        "created_rules": created_rules,
    }


def ingest_bundle(*, organization_id, raw: bytes, actor_user_id=None):
    """Persist evidence, exact catalog reconciliation, and advisory rule provenance."""
    bundle = validate_bundle(raw)
    with transaction.atomic():
        scan, created = DiscoveryScan.objects.get_or_create(
            organization_id=organization_id,
            scan_hash=bundle["scan_id"],
            defaults={
                "device_id": bundle["device_id"],
                "observed_at": timestamp(bundle["observed_at"]),
                "bundle": bundle,
            },
        )
        if created:
            reconciled_items = set()
            created_rule_ids = set()
            status_counts = {
                DetectionEvidence.ReconciliationStatus.RECONCILED: 0,
                DetectionEvidence.ReconciliationStatus.REVIEW: 0,
                DetectionEvidence.ReconciliationStatus.UNKNOWN: 0,
            }
            evidence_rows = []
            for record in bundle["evidence"]:
                outcome = _reconcile_record(
                    organization_id=organization_id,
                    record=record,
                    created_by_id=actor_user_id,
                )
                status_counts[outcome["status"]] += 1
                if outcome["inventory_item"] is not None:
                    reconciled_items.add(str(outcome["inventory_item"].id))
                created_rule_ids.update(
                    str(rule.id) for rule in outcome["created_rules"]
                )
                evidence_rows.append(
                    DetectionEvidence(
                        organization_id=organization_id,
                        scan=scan,
                        fingerprint=fingerprint(record),
                        evidence_hash=record["evidence_hash"],
                        record=record,
                        reconciliation_status=outcome["status"],
                        reconciliation_reason=outcome["reason"],
                        matched_identifier_type=outcome["identifier_type"] or "",
                        matched_product=outcome["product"],
                        inventory_item=outcome["inventory_item"],
                    )
                )
            DetectionEvidence.objects.bulk_create(evidence_rows)
            append_audit_event(
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                event_type=EVENT_DISCOVERY_COMPLETED,
                entity_type="discovery_scan",
                entity_id=scan.id,
                data={
                    "collector_version": bundle["collector_version"],
                    "coverage": bundle["coverage"],
                    "observation_count": len(evidence_rows),
                    "reconciled_count": status_counts["reconciled"],
                    "review_count": status_counts["review"],
                    "unknown_count": status_counts["unknown"],
                },
            )
            if reconciled_items:
                append_audit_event(
                    organization_id=organization_id,
                    actor_user_id=actor_user_id,
                    event_type=EVENT_RECONCILIATION_ACCEPTED,
                    entity_type="discovery_scan",
                    entity_id=scan.id,
                    data={
                        "inventory_item_ids": sorted(reconciled_items),
                        "created_rule_ids": sorted(created_rule_ids),
                        "method": "exact_verified_identifier",
                    },
                )
    return scan, created
