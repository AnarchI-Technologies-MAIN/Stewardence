from __future__ import annotations

from uuid import UUID

import pytest
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.catalog.management.commands.seed_product_catalog import CATALOG_PRODUCTS
from apps.catalog.matching import CandidateIdentifier, match_product
from apps.catalog.models import Product, ProductIdentifier, Vendor
from apps.catalog.normalization import (
    IdentifierNormalizationError,
    canonicalize,
    normalize_hostname,
    normalize_microsoft_app_id,
    normalize_opaque_identifier,
    normalize_origin,
    normalize_redirect_uri,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog_products():
    vendor = Vendor.objects.create(
        name="Verified Vendor", status=Vendor.Status.VERIFIED
    )
    provider_product = Product.objects.create(
        vendor=vendor,
        name="Provider Match",
        category="Test",
    )
    name_product = Product.objects.create(
        vendor=vendor,
        name="Name Match",
        category="Test",
    )
    ProductIdentifier.objects.create(
        product=provider_product,
        identifier_type=ProductIdentifier.Type.MICROSOFT_APP_ID,
        raw_value="A8098C1A-F86E-11DA-BD1A-00112444BE1E",
        verified=True,
    )
    ProductIdentifier.objects.create(
        product=name_product,
        identifier_type=ProductIdentifier.Type.PRODUCT_NAME,
        raw_value="Name Match",
        verified=True,
    )
    return provider_product, name_product


def test_opaque_oauth_identifier_preserves_mixed_case():
    assert normalize_opaque_identifier(" \tAbC-xYz_123\r\n") == "AbC-xYz_123"
    assert canonicalize(
        "google_client_id", " MixedCase.apps.googleusercontent.com "
    ) == ("MixedCase.apps.googleusercontent.com")


def test_microsoft_uuid_is_canonicalized():
    assert normalize_microsoft_app_id(" A8098C1A-F86E-11DA-BD1A-00112444BE1E ") == (
        "a8098c1a-f86e-11da-bd1a-00112444be1e"
    )


def test_unicode_hostname_and_trailing_dot_are_canonicalized():
    assert normalize_hostname("BÜCHER.example.") == "xn--bcher-kva.example"
    assert normalize_hostname("Example.COM.") == "example.com"


def test_ipv6_origin_with_port_is_parsed_without_string_splitting():
    assert normalize_hostname("https://[2001:db8::1]:8443/path") == "2001:db8::1"
    assert normalize_origin("https://[2001:db8::1]:8443/path?ignored=yes") == (
        "https://[2001:db8::1]:8443"
    )


def test_subdomains_remain_distinct_without_an_explicit_alias():
    assert normalize_hostname("api.example.com") == "api.example.com"
    assert normalize_hostname("example.com") == "example.com"
    assert normalize_hostname("api.example.com") != normalize_hostname("example.com")


def test_redirect_uri_preserves_path_and_query_but_not_fragment():
    assert normalize_redirect_uri(
        "https://BÜCHER.example:8443/OAuth/Callback?state=AbC#browser-only"
    ) == ("https://xn--bcher-kva.example:8443/OAuth/Callback?state=AbC")


@pytest.mark.parametrize("identifier_type", ["hostname", "microsoft_app_id"])
def test_invalid_structured_identifiers_fail_closed(identifier_type):
    with pytest.raises(IdentifierNormalizationError):
        canonicalize(identifier_type, "not valid / identifier")


def test_identifier_model_stores_raw_and_canonical_values(catalog_products):
    provider_product, _name_product = catalog_products
    identifier = ProductIdentifier.objects.create(
        product=provider_product,
        identifier_type=ProductIdentifier.Type.OAUTH_CLIENT_ID,
        raw_value="  MixedCase-Token  ",
        verified=True,
    )

    assert identifier.raw_value == "  MixedCase-Token  "
    assert identifier.canonical_value == "MixedCase-Token"
    assert identifier.normalization_version == "AL-ID-1"


def test_catalog_collision_is_rejected_even_with_null_provider_scope(
    catalog_products,
):
    provider_product, name_product = catalog_products
    ProductIdentifier.objects.create(
        product=provider_product,
        identifier_type=ProductIdentifier.Type.HOSTNAME,
        raw_value="Example.com",
        verified=True,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductIdentifier.objects.create(
            product=name_product,
            identifier_type=ProductIdentifier.Type.HOSTNAME,
            raw_value="example.COM.",
            verified=True,
        )


def test_matcher_uses_provider_id_before_exact_product_name(catalog_products):
    provider_product, _name_product = catalog_products

    result = match_product(
        [
            CandidateIdentifier("product_name", "Name Match"),
            CandidateIdentifier(
                "microsoft_app_id",
                "a8098c1a-f86e-11da-bd1a-00112444be1e",
            ),
        ]
    )

    assert result.status == "known"
    assert result.product_id == provider_product.id
    assert result.identifier_type == "microsoft_app_id"


def test_unknown_and_unverified_identifiers_require_review(catalog_products):
    provider_product, _name_product = catalog_products
    ProductIdentifier.objects.create(
        product=provider_product,
        identifier_type=ProductIdentifier.Type.HOSTNAME,
        raw_value="unreviewed.example",
        verified=False,
    )

    unknown = match_product([CandidateIdentifier("hostname", "unknown.example")])
    unverified = match_product([CandidateIdentifier("hostname", "unreviewed.example")])

    assert unknown.status == "unknown"
    assert unknown.product_id is None
    assert unverified.status == "unknown"


def test_conflicting_same_priority_evidence_does_not_choose_arbitrarily(
    catalog_products,
):
    provider_product, name_product = catalog_products
    ProductIdentifier.objects.create(
        product=provider_product,
        identifier_type=ProductIdentifier.Type.HOSTNAME,
        raw_value="first.example",
        verified=True,
    )
    ProductIdentifier.objects.create(
        product=name_product,
        identifier_type=ProductIdentifier.Type.HOSTNAME,
        raw_value="second.example",
        verified=True,
    )

    result = match_product(
        [
            CandidateIdentifier("hostname", "first.example"),
            CandidateIdentifier("hostname", "second.example"),
        ]
    )

    assert result.status == "review"
    assert result.product_id is None
    assert result.reason == "conflicting_exact_identifiers"


def test_seed_catalog_is_bounded_deterministic_and_idempotent():
    assert len(CATALOG_PRODUCTS) == 40

    call_command("seed_product_catalog", verbosity=0)
    first_ids = set(Product.objects.values_list("id", flat=True))
    call_command("seed_product_catalog", verbosity=0)

    assert Product.objects.count() == 40
    assert Vendor.objects.count() == 40
    assert ProductIdentifier.objects.count() == 80
    assert set(Product.objects.values_list("id", flat=True)) == first_ids
    assert all(isinstance(product_id, UUID) for product_id in first_ids)
    assert set(Vendor.objects.values_list("status", flat=True)) == {"unverified"}
