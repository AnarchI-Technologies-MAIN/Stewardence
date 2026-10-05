"""Versioned customer declarations; defaults never establish knowledge."""

from django.core.exceptions import ValidationError
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction

from .provenance import DECLARED, INVENTORY_FACT_FIELDS, UNKNOWN

CONTRACT = "core.inventory.declarations.v1"
LIST_FIELDS = ("connected_systems", "data_categories", "permissions", "capabilities")
NONE = "__none__"


def normalized_explicit_inventory_record(item):
    if item.declaration_contract != CONTRACT:
        raise ValidationError("Explicit declaration record required")
    declared = set(item.declared_fields)
    values = {
        field: getattr(item, field) if field in declared else None
        for field in INVENTORY_FACT_FIELDS
    }
    return {
        "id": str(item.id),
        "product_id": None,
        **values,
        "source_type": item.source_type,
        "declaration_contract": CONTRACT,
        "declaration_as_of": item.declaration_as_of.isoformat(),
        "provenance": {
            **{
                field: DECLARED if field in declared else UNKNOWN
                for field in INVENTORY_FACT_FIELDS
            },
            "product_id": UNKNOWN,
            "source_type": DECLARED,
        },
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
    }


def write_explicit_inventory(
    *, organization_id, actor_id, item_id, form, using="default"
):
    import json

    payload = form.declaration_payload()
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
        connections[using].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.write_explicit_inventory(%s,%s,%s,%s::jsonb)",
            [item_id, organization_id, actor_id, json.dumps(payload)],
        )
        return cursor.fetchone()[0]
