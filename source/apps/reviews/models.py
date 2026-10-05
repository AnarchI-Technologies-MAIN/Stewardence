"""Immutable initial review kernel; FROZEN does not mean artifact complete."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ImmutableRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(editable=False)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Review evidence is immutable")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Review evidence is append-only")


class ReviewCycle(ImmutableRecord):
    input_snapshot = models.ForeignKey(
        "assessments.AssessmentSnapshot", on_delete=models.PROTECT
    )
    baseline_pack_id = models.UUIDField(null=True, editable=False)

    class Meta:
        db_table = "review_cycles"

    def __str__(self):
        return f"Review cycle {self.id}"

    @property
    def current_event(self):
        return self.events.order_by("-revision").first()

    @property
    def revision(self):
        event = self.current_event
        return event.revision if event else None

    @property
    def state(self):
        event = self.current_event
        return event.state if event else None


class CycleEvent(ImmutableRecord):
    cycle = models.ForeignKey(
        ReviewCycle, on_delete=models.PROTECT, related_name="events"
    )
    revision = models.PositiveIntegerField()
    state = models.CharField(max_length=32)
    payload = models.JSONField(editable=False)
    sha256 = models.CharField(max_length=64, editable=False)

    class Meta:
        db_table = "review_cycle_events"
        constraints = [
            models.UniqueConstraint(
                fields=("cycle", "revision"), name="review_event_revision_unique"
            )
        ]

    def __str__(self):
        return f"Review cycle event {self.id}"


class PackIdentity(ImmutableRecord):
    cycle = models.OneToOneField(
        ReviewCycle, on_delete=models.PROTECT, related_name="frozen_pack"
    )
    admitted_revision = models.PositiveIntegerField()
    manifest = models.JSONField(editable=False)
    sha256 = models.CharField(max_length=64, editable=False)

    class Meta:
        db_table = "review_pack_identities"

    def __str__(self):
        return f"Review pack {self.id}"


class CapacityReservation(ImmutableRecord):
    cycle = models.OneToOneField(
        ReviewCycle, on_delete=models.PROTECT, related_name="capacity_reservation"
    )
    paid_coverage = models.ForeignKey("billing.PaidCoverage", on_delete=models.PROTECT)
    reserved_bytes = models.PositiveBigIntegerField()
    state = models.CharField(max_length=32, default="reserved")

    class Meta:
        db_table = "review_capacity_reservations"

    def __str__(self):
        return f"Review capacity reservation {self.id}"


class ReservationEvent(ImmutableRecord):
    reservation = models.ForeignKey(
        CapacityReservation, on_delete=models.PROTECT, related_name="events"
    )
    revision = models.PositiveIntegerField()
    state = models.CharField(max_length=32)
    payload = models.JSONField(editable=False)
    sha256 = models.CharField(max_length=64, editable=False)

    class Meta:
        db_table = "review_reservation_events"
        constraints = [
            models.UniqueConstraint(
                fields=("reservation", "revision"),
                name="review_reservation_event_unique",
            )
        ]

    def __str__(self):
        return f"Review reservation event {self.id}"


class ReviewLifecycleGate(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "review_lifecycle_gate"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="review_lifecycle_gate_singleton"
            )
        ]

    def __str__(self):
        return "Review lifecycle gate"


class ArtifactRequest(ImmutableRecord):
    pack = models.OneToOneField(
        PackIdentity, on_delete=models.PROTECT, related_name="artifact_request"
    )
    report = models.OneToOneField("reports.Report", on_delete=models.PROTECT)
    job = models.OneToOneField("jobs.BackgroundJob", on_delete=models.PROTECT)
    manifest_sha256 = models.CharField(max_length=64)
    promote_baseline = models.BooleanField(default=False)
    observed_head_revision = models.PositiveIntegerField()
    observed_head_pack_id = models.UUIDField(null=True)

    class Meta:
        db_table = "review_artifact_requests"

    def __str__(self):
        return f"Review artifact request {self.id}"


class PackCompletion(ImmutableRecord):
    request = models.OneToOneField(
        ArtifactRequest, on_delete=models.PROTECT, related_name="completion"
    )
    artifact = models.OneToOneField("reports.ReportArtifact", on_delete=models.PROTECT)
    payload = models.JSONField()
    sha256 = models.CharField(max_length=64)

    class Meta:
        db_table = "review_pack_completions"

    def __str__(self):
        return f"Review pack completion {self.id}"


class BaselineHead(models.Model):
    organization = models.OneToOneField(
        "organizations.Organization", on_delete=models.PROTECT, primary_key=True
    )
    pack = models.ForeignKey(PackIdentity, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField()

    class Meta:
        db_table = "review_baseline_heads"

    def __str__(self):
        return f"Review baseline head {self.organization_id}"


class CoreProposalAdmissionGate(models.Model):
    """Operator-owned proposal admission; disabled until separately qualified."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "review_core_proposal_gate"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="review_proposal_gate_singleton"
            )
        ]

    def __str__(self):
        return f"Core proposal gate {self.id}"


class UnusedStopGate(models.Model):
    """Operator gate for positive-unused termination, never artifact cleanup."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "review_unused_stop_gate"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1), name="review_unused_stop_gate_singleton"
            )
        ]

    def __str__(self):
        return f"Unused report stop gate {self.id}"


class CaptureProposalAdmissionReceipt(ImmutableRecord):
    """Issued proposal identity; hashes alone never establish issuance."""

    snapshot = models.OneToOneField(
        "assessments.AssessmentSnapshot", on_delete=models.PROTECT
    )
    revision = models.OneToOneField("jobs.ActionCardRevision", on_delete=models.PROTECT)
    capture_receipt = models.ForeignKey(
        "assessments.SnapshotCaptureReceipt", on_delete=models.PROTECT
    )
    contract = models.CharField(max_length=80, editable=False)
    input_sha256 = models.CharField(max_length=64, editable=False)
    result_sha256 = models.CharField(max_length=64, editable=False)
    revision_sha256 = models.CharField(max_length=64, editable=False)
    qualification_sha256 = models.CharField(max_length=64, editable=False)

    class Meta:
        db_table = "review_capture_proposal_receipts"

    def __str__(self):
        return f"Capture proposal receipt {self.id}"
