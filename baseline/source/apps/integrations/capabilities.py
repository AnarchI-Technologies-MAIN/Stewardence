"""Provider capability declarations. A declaration does not mean connected."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorCapability:
    provider: str
    financial_observations: bool
    permission_grants: bool
    scope_boundary: str
    status: str = "implementation_pending"


CONNECTORS = {
    "quickbooks_online": ConnectorCapability(
        "quickbooks_online",
        True,
        False,
        "Accounting OAuth scope can permit writes; Stewardence collection "
        "must enforce read-only API operations.",
    ),
    "xero": ConnectorCapability(
        "xero",
        True,
        False,
        "Use current granular read scopes for selected financial entities and reports.",
    ),
    "microsoft_365": ConnectorCapability(
        "microsoft_365",
        False,
        True,
        "Directory integration discovery requires appropriate tenant permissions; "
        "workbook data requires separately authorized files.",
    ),
}


def classify_ai_connection(*, application_id, observed_grant, reviewed_ai_catalog):
    """An exact grant shows authorization, not AI execution or realized benefit."""
    entry = reviewed_ai_catalog.get(application_id)
    return {
        "application_id": application_id,
        "connection_status": "permission_grant_observed"
        if observed_grant
        else "not_established",
        "ai_capability_status": "catalog_match" if entry else "unknown",
        "product_id": entry["product_id"] if entry else None,
        "catalog_reference": entry["reference"] if entry else None,
        "ai_feature_enabled": "unknown",
        "actual_usage": "unknown",
        "realized_roi": "not_established",
    }
