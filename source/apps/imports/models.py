from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.organizations.models import Organization


class ImportBatch(models.Model):
    class Status(models.TextChoices):
        REVIEWING = "reviewing", "Needs review"
        READY = "ready", "Ready for final approval"
        IMPORTED = "imported", "Imported"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="import_batches",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_import_batches",
    )
    source_filename = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.REVIEWING,
    )
    row_count = models.PositiveIntegerField(default=0)
    imported_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_import_batches"
        indexes = [models.Index(fields=("organization",), name="import_batch_org_idx")]
        ordering = ("-created_at", "id")

    def __str__(self) -> str:
        return f"{self.source_filename} ({self.get_status_display()})"


class ImportRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="import_rows",
    )
    batch = models.ForeignKey(
        ImportBatch,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    errors = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inventory_import_rows"
        constraints = [
            models.UniqueConstraint(
                fields=("batch", "row_number"),
                name="unique_import_batch_row",
            )
        ]
        indexes = [models.Index(fields=("organization",), name="import_row_org_idx")]
        ordering = ("row_number", "id")

    def __str__(self) -> str:
        return f"{self.batch.source_filename}, row {self.row_number}"
