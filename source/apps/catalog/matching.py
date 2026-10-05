from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .models import ProductIdentifier
from .normalization import IdentifierNormalizationError, canonicalize

MATCH_PRIORITY = {
    ProductIdentifier.Type.MICROSOFT_APP_ID: 1,
    ProductIdentifier.Type.GOOGLE_CLIENT_ID: 1,
    ProductIdentifier.Type.HOSTNAME: 2,
    ProductIdentifier.Type.DOMAIN: 2,
    ProductIdentifier.Type.ORIGIN: 2,
    ProductIdentifier.Type.OAUTH_CLIENT_ID: 3,
    ProductIdentifier.Type.REDIRECT_URI: 3,
    ProductIdentifier.Type.PRODUCT_NAME: 4,
}


@dataclass(frozen=True)
class CandidateIdentifier:
    identifier_type: str
    raw_value: str
    provider_scope: str | None = None


@dataclass(frozen=True)
class CatalogMatch:
    status: str
    product_id: UUID | None = None
    identifier_type: str | None = None
    reason: str = ""


def match_product(candidates: list[CandidateIdentifier]) -> CatalogMatch:
    normalized: list[tuple[int, CandidateIdentifier, str]] = []
    for candidate in candidates:
        try:
            priority = MATCH_PRIORITY[candidate.identifier_type]
            canonical = canonicalize(candidate.identifier_type, candidate.raw_value)
        except (KeyError, IdentifierNormalizationError):
            continue
        normalized.append((priority, candidate, canonical))

    for priority in sorted(set(item[0] for item in normalized)):
        matches: list[tuple[UUID, str]] = []
        for _rank, candidate, canonical in (
            item for item in normalized if item[0] == priority
        ):
            identifiers = ProductIdentifier.objects.filter(
                identifier_type=candidate.identifier_type,
                canonical_value=canonical,
                provider_scope=candidate.provider_scope,
                verified=True,
            ).values_list("product_id", "identifier_type")
            matches.extend(identifiers)

        product_ids = {product_id for product_id, _kind in matches}
        if len(product_ids) == 1:
            product_id = next(iter(product_ids))
            matched_type = next(kind for found, kind in matches if found == product_id)
            return CatalogMatch(
                status="known",
                product_id=product_id,
                identifier_type=matched_type,
                reason="exact_verified_identifier",
            )
        if len(product_ids) > 1:
            return CatalogMatch(
                status="review",
                reason="conflicting_exact_identifiers",
            )

    return CatalogMatch(status="unknown", reason="no_exact_verified_identifier")
