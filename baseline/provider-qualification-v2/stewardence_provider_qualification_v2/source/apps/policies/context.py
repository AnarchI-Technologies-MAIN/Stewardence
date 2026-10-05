from __future__ import annotations

from apps.catalog.models import Vendor


def inventory_policy_context(item) -> dict[str, object]:
    product = item.product
    vendor_review_status = "incomplete"
    if product is not None and product.vendor.status == Vendor.Status.VERIFIED:
        vendor_review_status = "complete"

    return {
        "autonomy_level": item.autonomy_level,
        "business_owner": item.business_owner,
        "catalog_product_id": str(item.product_id) if item.product_id else None,
        "capabilities": tuple(item.capabilities),
        "connected_systems": tuple(item.connected_systems),
        "data_categories": tuple(item.data_categories),
        "department": item.department,
        "human_approval": item.human_approval,
        "monthly_cost_cents": item.monthly_cost_cents,
        "permissions": tuple(item.permissions),
        "retention_status": "unknown",
        "seat_count": item.seat_count,
        "status": item.status,
        "training_behavior": "unknown",
        "user_count": item.user_count,
        "vendor_name": item.vendor_name,
        "vendor_review_status": vendor_review_status,
    }
