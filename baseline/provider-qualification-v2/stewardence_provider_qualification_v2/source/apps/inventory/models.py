from __future__ import annotations

import uuid
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.catalog.models import Product
from apps.organizations.models import Organization


class InventoryItem(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        TRIAL = "trial", "Trial"
        INACTIVE = "inactive", "Inactive"
        REVIEWING = "reviewing", "Reviewing"

    class SourceType(models.TextChoices):
        MANUAL = "manual", "Entered by a person"
        CSV = "csv", "Imported from a spreadsheet"
        DISCOVERED = "discovered", "Discovered from a connected source"

    class Autonomy(models.IntegerChoices):
        NONE = 0, "It does not act on its own"
        SUGGESTS = 1, "It suggests actions for a person to take"
        AFTER_APPROVAL = 2, "It acts only after a person approves"
        LIMITED_AUTOMATIC = 3, "It can perform some tasks on its own"
        SIGNIFICANT_AUTOMATIC = 4, "It can perform important tasks on its own"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="inventory_items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="inventory_items",
        null=True,
        blank=True,
    )
    display_name = models.CharField(max_length=255)
    vendor_name = models.CharField(max_length=255)
    business_owner = models.CharField(max_length=255, blank=True)
    department = models.CharField(max_length=255, blank=True)
    user_count = models.PositiveIntegerField(default=0)
    business_purpose = models.TextField(blank=True)
    monthly_cost_cents = models.PositiveIntegerField(default=0)
    seat_count = models.PositiveIntegerField(default=0)
    connected_systems = models.JSONField(default=list, blank=True)
    data_categories = models.JSONField(default=list, blank=True)
    permissions = models.JSONField(default=list, blank=True)
    capabilities = models.JSONField(default=list, blank=True)
    autonomy_level = models.PositiveSmallIntegerField(
        choices=Autonomy,
        default=Autonomy.NONE,
        validators=[MinValueValidator(0), MaxValueValidator(4)],
    )
    human_approval = models.BooleanField(default=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.REVIEWING)
    source_type = models.CharField(
        max_length=16,
        choices=SourceType,
        default=SourceType.MANUAL,
    )
    discovery_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    declared_fields = models.JSONField(default=list, blank=True, editable=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_items"
        indexes = [
            models.Index(fields=("organization",), name="inventory_org_idx"),
            models.Index(
                fields=("organization", "status"),
                name="inventory_org_status_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "discovery_fingerprint"),
                condition=models.Q(source_type="discovered"),
                name="inventory_discovery_fingerprint_unique",
            ),
            models.UniqueConstraint(
                fields=("id", "organization"),
                name="inventory_id_org_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_type="discovered",
                    )
                    & ~models.Q(discovery_fingerprint="")
                    | (
                        ~models.Q(source_type="discovered")
                        & models.Q(discovery_fingerprint="")
                    )
                ),
                name="discovered_inventory_has_fingerprint",
            ),
        ]
        ordering = ("display_name", "id")

    def __str__(self) -> str:
        return self.display_name

    @property
    def monthly_cost_display(self) -> str:
        amount = Decimal(self.monthly_cost_cents) / Decimal(100)
        return f"{amount:.2f}"


class DiscoveryScan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    scan_hash = models.CharField(max_length=64)
    device_id = models.UUIDField()
    observed_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)
    bundle = models.JSONField()

    class Meta:
        db_table = "discovery_scans"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "scan_hash"), name="scan_org_hash_unique"
            ),
            models.UniqueConstraint(
                fields=("id", "organization"), name="scan_id_org_unique"
            ),
        ]

    def __str__(self):
        return self.scan_hash


class DetectionEvidence(models.Model):
    class ReconciliationStatus(models.TextChoices):
        RECONCILED = "reconciled", "Exact catalog match"
        REVIEW = "review", "Review required"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    scan = models.ForeignKey(
        DiscoveryScan, on_delete=models.PROTECT, related_name="observations"
    )
    fingerprint = models.CharField(max_length=64)
    evidence_hash = models.CharField(max_length=64)
    record = models.JSONField()
    reconciliation_status = models.CharField(
        max_length=16,
        choices=ReconciliationStatus,
        default=ReconciliationStatus.UNKNOWN,
    )
    reconciliation_reason = models.CharField(
        max_length=64,
        default="not_reconciled_at_ingest",
    )
    matched_identifier_type = models.CharField(max_length=32, blank=True)
    matched_product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="detection_evidence",
    )
    inventory_item = models.ForeignKey(
        InventoryItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="detection_evidence",
    )

    class Meta:
        db_table = "detection_evidence"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "scan", "fingerprint"),
                name="evidence_scan_identity_unique",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        reconciliation_status="reconciled",
                        matched_product__isnull=False,
                        inventory_item__isnull=False,
                    )
                    | models.Q(
                        reconciliation_status__in=("review", "unknown"),
                        matched_product__isnull=True,
                        inventory_item__isnull=True,
                    )
                ),
                name="evidence_reconciliation_shape",
            ),
        ]

    def __str__(self):
        return self.evidence_hash
