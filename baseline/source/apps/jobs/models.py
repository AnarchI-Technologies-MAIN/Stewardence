from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q

from apps.organizations.models import Organization


class BackgroundJob(models.Model):
    class Type(models.TextChoices):
        RISK_REASSESSMENT = "risk_reassessment", "Risk reassessment"
        REPORT_GENERATION = "report_generation", "Report generation"
        CATALOG_REFRESH = "catalog_refresh", "Catalog refresh"
        AUDIT_BATCH_SEAL = "audit_batch_seal", "Audit batch seal"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="background_jobs",
    )
    job_type = models.CharField(max_length=32, choices=Type)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=Status,
        default=Status.QUEUED,
    )
    priority = models.IntegerField(default=100)
    attempts = models.PositiveSmallIntegerField(default=0)
    available_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True, blank=True)
    lock_expires_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(  # noqa: DJ001
        max_length=255,
        null=True,
        blank=True,
    )
    claim_token = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
    )
    safe_error_summary = models.TextField(  # noqa: DJ001
        null=True,
        blank=True,
    )
    error_fingerprint = models.CharField(  # noqa: DJ001
        max_length=128,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "background_jobs"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status="queued",
                        locked_at__isnull=True,
                        lock_expires_at__isnull=True,
                        locked_by__isnull=True,
                        claim_token__isnull=True,
                        completed_at__isnull=True,
                    )
                    | Q(
                        status="running",
                        locked_at__isnull=False,
                        lock_expires_at__isnull=False,
                        locked_by__isnull=False,
                        claim_token__isnull=False,
                        completed_at__isnull=True,
                    )
                    | Q(
                        status__in=("completed", "failed"),
                        locked_at__isnull=True,
                        lock_expires_at__isnull=True,
                        locked_by__isnull=True,
                        claim_token__isnull=True,
                        completed_at__isnull=False,
                    )
                ),
                name="background_job_state_consistent",
            )
        ]
        indexes = [
            models.Index(
                fields=("status", "available_at", "priority", "id"),
                name="job_claim_order_idx",
            ),
            models.Index(
                fields=("status", "lock_expires_at"),
                name="job_lease_recovery_idx",
            ),
            models.Index(fields=("organization",), name="job_org_idx"),
        ]
        ordering = ("priority", "available_at", "id")

    def __str__(self) -> str:
        return f"{self.job_type} {self.id} ({self.status})"
