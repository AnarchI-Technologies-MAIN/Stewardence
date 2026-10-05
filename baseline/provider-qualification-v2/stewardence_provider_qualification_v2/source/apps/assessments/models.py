from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.organizations.models import Organization


class AssessmentSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="assessment_snapshots",
    )
    assessment_id = models.UUIDField(default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assessment_snapshots",
    )
    captured_at = models.DateTimeField(editable=False)
    input_payload = models.JSONField(editable=False)
    result_payload = models.JSONField(editable=False)
    input_sha256 = models.CharField(max_length=64, editable=False)
    result_sha256 = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        db_table = "assessment_snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=("organization", "assessment_id", "version"),
                name="unique_assessment_snapshot_version",
            )
        ]
        indexes = [
            models.Index(
                fields=("organization", "assessment_id", "version"),
                name="assessment_org_identity_idx",
            )
        ]
        ordering = ("-captured_at", "assessment_id", "version")

    def __str__(self) -> str:
        return f"{self.assessment_id} v{self.version}"

    def save(self, *args, **kwargs):
        from .snapshots import canonical_sha256

        if not self._state.adding:
            raise ValidationError("Assessment snapshots are immutable")
        if canonical_sha256(self.input_payload) != self.input_sha256:
            raise ValidationError("Assessment input hash does not match its payload")
        if canonical_sha256(self.result_payload) != self.result_sha256:
            raise ValidationError("Assessment result hash does not match its payload")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Assessment snapshots are immutable")
