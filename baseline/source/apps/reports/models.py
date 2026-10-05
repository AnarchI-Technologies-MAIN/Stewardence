from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.assessments.models import AssessmentSnapshot
from apps.organizations.models import Organization

from .storage import PDF_CONTENT_TYPE, SHA256_PATTERN


class Report(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="reports",
    )
    assessment_snapshot = models.OneToOneField(
        AssessmentSnapshot,
        on_delete=models.PROTECT,
        related_name="report",
    )
    sequence = models.BigIntegerField(unique=True, editable=False)
    identifier_year = models.PositiveSmallIntegerField(editable=False)
    report_identifier = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
    )
    organization_display_name = models.CharField(
        max_length=200,
        editable=False,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="generated_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        db_table = "reports"
        ordering = ("-created_at", "report_identifier")
        constraints = [
            models.CheckConstraint(
                condition=Q(sequence__gte=1),
                name="report_sequence_positive",
            ),
            models.CheckConstraint(
                condition=Q(identifier_year__gte=2000),
                name="report_identifier_year_supported",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "created_at"),
                name="report_org_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.report_identifier

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Report identity records are immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Report identity records are immutable")


class ReportArtifact(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="report_artifacts",
    )
    report = models.OneToOneField(
        Report,
        on_delete=models.PROTECT,
        related_name="artifact",
    )
    assessment_snapshot = models.ForeignKey(
        AssessmentSnapshot,
        on_delete=models.PROTECT,
        related_name="report_artifacts",
    )
    object_key = models.CharField(
        max_length=512,
        unique=True,
        editable=False,
    )
    content_type = models.CharField(
        max_length=100,
        default=PDF_CONTENT_TYPE,
        editable=False,
    )
    sha256 = models.CharField(
        max_length=64,
        editable=False,
    )
    size_bytes = models.PositiveBigIntegerField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        db_table = "report_artifacts"
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=Q(size_bytes__gte=1),
                name="report_artifact_size_positive",
            ),
        ]
        indexes = [
            models.Index(
                fields=("organization", "created_at"),
                name="artifact_org_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.object_key

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Report artifact metadata is immutable")
        # The worker deliberately cannot read organization identity rows. The
        # database foreign key still enforces existence, while clean() below
        # verifies that the report and snapshot carry the same tenant identity.
        self.full_clean(exclude={"organization"})
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Report artifact metadata is immutable")

    def clean(self):
        super().clean()

        if self.content_type != PDF_CONTENT_TYPE:
            raise ValidationError(
                {"content_type": "Report artifacts must use application/pdf"}
            )

        if not SHA256_PATTERN.fullmatch(self.sha256):
            raise ValidationError(
                {"sha256": "Report artifact SHA-256 must be lowercase hexadecimal"}
            )

        if self.report_id and self.organization_id:
            if self.report.organization_id != self.organization_id:
                raise ValidationError("Report artifact tenant does not match report")

        if self.report_id and self.assessment_snapshot_id:
            if self.report.assessment_snapshot_id != self.assessment_snapshot_id:
                raise ValidationError(
                    "Report artifact snapshot does not match report snapshot"
                )
