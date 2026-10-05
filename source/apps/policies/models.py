from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.organizations.models import Organization


class OrganizationRule(models.Model):
    class SourceType(models.TextChoices):
        MANUAL = "manual", "Created by a person"
        DETECTOR = "detector", "Created from Collector evidence"

    class Result(models.TextChoices):
        FAIL = "FAIL", "Does not meet the rule"
        WARNING = "WARNING", "Needs attention"

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MODERATE = "MODERATE", "Moderate"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="policy_rules",
    )
    name = models.CharField(max_length=255)
    version = models.PositiveIntegerField(default=1, editable=False)
    enabled = models.BooleanField(default=True)
    definition = models.JSONField()
    result_on_match = models.CharField(
        max_length=16,
        choices=Result,
        default=Result.WARNING,
    )
    severity = models.CharField(
        max_length=16,
        choices=Severity,
        default=Severity.MODERATE,
    )
    explanation = models.TextField()
    remediation = models.TextField()
    source_type = models.CharField(
        max_length=16,
        choices=SourceType,
        default=SourceType.MANUAL,
        editable=False,
    )
    generation_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        default="",
        editable=False,
    )
    source_inventory_item = models.ForeignKey(
        "inventory.InventoryItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="detector_rules",
        editable=False,
    )
    detector_id = models.CharField(max_length=100, blank=True, editable=False)
    detector_version = models.CharField(max_length=32, blank=True, editable=False)
    mapping_id = models.CharField(max_length=100, blank=True, editable=False)
    mapping_version = models.CharField(max_length=32, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_rules",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "organization_rules"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "name"),
                condition=models.Q(source_type="manual"),
                name="unique_manual_organization_rule_name",
            ),
            models.UniqueConstraint(
                fields=("organization", "generation_fingerprint"),
                condition=models.Q(source_type="detector"),
                name="unique_detector_rule_fingerprint",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        source_type="detector",
                        source_inventory_item__isnull=False,
                    )
                    & ~models.Q(generation_fingerprint="")
                    & ~models.Q(detector_id="")
                    & ~models.Q(detector_version="")
                    & ~models.Q(mapping_id="")
                    & ~models.Q(mapping_version="")
                    | models.Q(
                        source_type="manual",
                        generation_fingerprint="",
                        source_inventory_item__isnull=True,
                        detector_id="",
                        detector_version="",
                        mapping_id="",
                        mapping_version="",
                    )
                ),
                name="organization_rule_provenance_shape",
            ),
        ]
        indexes = [
            models.Index(fields=("organization",), name="organization_rule_org_idx")
        ]
        ordering = ("name", "id")

    def __str__(self) -> str:
        return f"{self.name} v{self.version}"
