from __future__ import annotations

OBSERVED = "Observed"
DECLARED = "Declared"
CATALOG_DERIVED = "Catalog-derived"
CALCULATED = "Calculated"
UNKNOWN = "Unknown"

INVENTORY_FACT_FIELDS = (
    "display_name",
    "vendor_name",
    "business_owner",
    "department",
    "user_count",
    "business_purpose",
    "monthly_cost_cents",
    "seat_count",
    "connected_systems",
    "data_categories",
    "permissions",
    "capabilities",
    "autonomy_level",
    "human_approval",
    "status",
)

FORM_FIELD_TO_MODEL_FIELD = {
    "monthly_cost": "monthly_cost_cents",
}


def normalized_declared_fields(field_names) -> list[str]:
    return sorted(
        {
            FORM_FIELD_TO_MODEL_FIELD.get(field_name, field_name)
            for field_name in field_names
            if FORM_FIELD_TO_MODEL_FIELD.get(field_name, field_name)
            in INVENTORY_FACT_FIELDS
        }
    )


def inventory_provenance(item) -> dict[str, str]:
    if item.source_type != "discovered":
        facts = {field: DECLARED for field in INVENTORY_FACT_FIELDS}
        facts["product_id"] = CATALOG_DERIVED if item.product_id else UNKNOWN
        facts["source_type"] = DECLARED
        return facts

    declared = set(item.declared_fields)
    facts = {
        field: DECLARED if field in declared else UNKNOWN
        for field in INVENTORY_FACT_FIELDS
    }
    facts["display_name"] = DECLARED if "display_name" in declared else CATALOG_DERIVED
    facts["vendor_name"] = DECLARED if "vendor_name" in declared else CATALOG_DERIVED
    facts["product_id"] = CATALOG_DERIVED
    facts["source_type"] = OBSERVED
    return facts
