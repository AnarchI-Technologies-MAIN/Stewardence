from __future__ import annotations

import uuid

from django.db import models

from .normalization import NORMALIZATION_VERSION, canonicalize


class Vendor(models.Model):
    class Status(models.TextChoices):
        VERIFIED = "verified", "Verified"
        UNVERIFIED = "unverified", "Review incomplete"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    website_domain = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.UNVERIFIED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(
        Vendor, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    is_ai_product = models.BooleanField(default=True)
    default_risk_profile = models.JSONField(default=dict, blank=True)
    catalog_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("vendor", "name", "catalog_version"),
                name="unique_catalog_product_version",
            )
        ]
        ordering = ("vendor__name", "name", "id")

    def __str__(self) -> str:
        return f"{self.vendor.name} — {self.name}"


class ProductIdentifier(models.Model):
    class Type(models.TextChoices):
        MICROSOFT_APP_ID = "microsoft_app_id", "Microsoft application ID"
        GOOGLE_CLIENT_ID = "google_client_id", "Google client ID"
        OAUTH_CLIENT_ID = "oauth_client_id", "OAuth client ID"
        HOSTNAME = "hostname", "Hostname"
        DOMAIN = "domain", "Domain"
        ORIGIN = "origin", "Origin"
        REDIRECT_URI = "redirect_uri", "Redirect URI"
        PRODUCT_NAME = "product_name", "Product name"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="identifiers",
    )
    identifier_type = models.CharField(max_length=32, choices=Type)
    raw_value = models.CharField(max_length=1024)
    canonical_value = models.CharField(max_length=1024, editable=False)
    normalization_version = models.CharField(
        max_length=16,
        default=NORMALIZATION_VERSION,
        editable=False,
    )
    provider_scope = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
    )
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("identifier_type", "canonical_value", "provider_scope"),
                name="unique_catalog_identifier",
                nulls_distinct=False,
            )
        ]
        indexes = [
            models.Index(
                fields=("identifier_type", "canonical_value", "provider_scope"),
                name="catalog_identifier_lookup_idx",
            )
        ]
        ordering = ("identifier_type", "canonical_value", "id")

    def __str__(self) -> str:
        return f"{self.identifier_type}: {self.raw_value}"

    def save(self, *args, **kwargs):
        self.canonical_value = canonicalize(self.identifier_type, self.raw_value)
        self.normalization_version = NORMALIZATION_VERSION
        super().save(*args, **kwargs)
