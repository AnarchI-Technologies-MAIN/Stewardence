from __future__ import annotations

import hashlib
from dataclasses import dataclass

import rfc8785

from .models import OrganizationRule

MAPPING_REGISTRY_VERSION = "1"


@dataclass(frozen=True)
class DetectorRuleMapping:
    mapping_id: str
    mapping_version: str
    detector_id: str
    detector_version: str
    vendor_name: str
    product_name: str


SUPPORTED_AI_PRODUCT_MAPPINGS = tuple(
    DetectorRuleMapping(
        mapping_id=f"catalog-product-review.{slug}",
        mapping_version=MAPPING_REGISTRY_VERSION,
        detector_id="windows.installed_programs",
        detector_version="1",
        vendor_name=vendor,
        product_name=product,
    )
    for slug, vendor, product in (
        ("openai-chatgpt", "OpenAI", "ChatGPT"),
        ("anthropic-claude", "Anthropic", "Claude"),
        ("google-gemini", "Google", "Gemini"),
        ("microsoft-365-copilot", "Microsoft", "Microsoft 365 Copilot"),
        ("github-copilot", "GitHub", "GitHub Copilot"),
    )
)


def applicable_mappings(*, detector_id, detector_version, product):
    return tuple(
        mapping
        for mapping in SUPPORTED_AI_PRODUCT_MAPPINGS
        if mapping.detector_id == detector_id
        and mapping.detector_version == detector_version
        and mapping.vendor_name == product.vendor.name
        and mapping.product_name == product.name
    )


def generation_fingerprint(*, mapping, organization_id, product_id) -> str:
    material = {
        "registry_version": MAPPING_REGISTRY_VERSION,
        "mapping_id": mapping.mapping_id,
        "mapping_version": mapping.mapping_version,
        "detector_id": mapping.detector_id,
        "detector_version": mapping.detector_version,
        "organization_id": str(organization_id),
        "product_id": str(product_id),
    }
    return hashlib.sha256(rfc8785.dumps(material)).hexdigest()


def instantiate_detector_rules(
    *, organization_id, inventory_item, detector_id, detector_version, created_by_id
):
    """Create supported advisory rules once; never update any existing rule."""
    product = inventory_item.product
    if product is None:
        return ()
    created_rules = []
    for mapping in applicable_mappings(
        detector_id=detector_id,
        detector_version=detector_version,
        product=product,
    ):
        rule_fingerprint = generation_fingerprint(
            mapping=mapping,
            organization_id=organization_id,
            product_id=product.id,
        )
        rule, created = OrganizationRule.objects.get_or_create(
            organization_id=organization_id,
            generation_fingerprint=rule_fingerprint,
            defaults={
                "name": f"Review detected {product.name}",
                "definition": {
                    "all": [
                        {
                            "field": "catalog_product_id",
                            "operator": "equals",
                            "value": str(product.id),
                        }
                    ],
                    "effects": [
                        {
                            "type": "recommend_review",
                            "message": (
                                "Confirm business use, data access, permissions, "
                                "and any paid subscription with a responsible person."
                            ),
                        }
                    ],
                },
                "result_on_match": OrganizationRule.Result.WARNING,
                "severity": OrganizationRule.Severity.MODERATE,
                "explanation": (
                    f"The Collector observed installed software that exactly matches "
                    f"the verified catalog entry for {product.name}. Installation "
                    "alone "
                    "does not prove use, permissions, or a paid subscription."
                ),
                "remediation": (
                    "Have a person confirm how the software is used and complete the "
                    "unknown inventory fields before relying on the assessment."
                ),
                "source_type": OrganizationRule.SourceType.DETECTOR,
                "source_inventory_item": inventory_item,
                "detector_id": detector_id,
                "detector_version": detector_version,
                "mapping_id": mapping.mapping_id,
                "mapping_version": mapping.mapping_version,
                "created_by_id": created_by_id,
            },
        )
        if created:
            created_rules.append(rule)
    return tuple(created_rules)
