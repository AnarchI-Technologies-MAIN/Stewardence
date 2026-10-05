"""Owner-bound initial slice. No artifacts, decisions or baseline promotion."""

from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.models import AssessmentSnapshot
from apps.assessments.snapshots import verify_snapshot

from .models import PackIdentity, ReviewCycle


def request_pack_artifact(
    *,
    pack_id,
    organization_id,
    actor_id,
    expected_revision=3,
    promote_baseline=False,
    using="default",
):
    """Stage one immutable request. Closed application and database gates apply.

    Report identity is one per snapshot; this slice cannot consume a report
    already rendered or already attached to another pack.
    """
    from django.conf import settings

    from apps.reports.jobs import ensure_report_generation_job
    from apps.reports.services import create_report

    from .models import ArtifactRequest

    for value in (pack_id, organization_id, actor_id):
        _identity(value)
    if not getattr(settings, "REVIEW_PACK_LIFECYCLE_ENABLED", False):
        raise ValidationError("Review lifecycle deployment gate closed")
    if (
        type(expected_revision) is not int
        or expected_revision != 3
        or type(promote_baseline) is not bool
    ):
        raise ValidationError(
            "Exact frozen revision and explicit promotion choice required"
        )
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
    ):
        # Same lock order as the database issuer; no report side effects precede
        # serialization, and SQL rechecks authority after all waits.
        with connections[using].cursor() as cursor:
            for name in (
                f"core:{organization_id}:control",
                f"review:{organization_id}:capacity",
            ):
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", [name]
                )
        pack = (
            PackIdentity.objects.using(using)
            .select_related("cycle")
            .get(id=pack_id, organization_id=organization_id)
        )
        existing = (
            ArtifactRequest.objects.using(using)
            .filter(pack_id=pack_id, organization_id=organization_id)
            .first()
        )
        if existing is not None:
            report_id, job_id = existing.report_id, existing.job_id
        else:
            report = create_report(
                organization_id=organization_id,
                assessment_snapshot_id=pack.cycle.input_snapshot_id,
                created_by_id=actor_id,
                using=using,
            )
            job = ensure_report_generation_job(report=report, using=using)
            if job is None:
                raise ValidationError("Review snapshot report is already rendered")
            report_id, job_id = report.id, job.id
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.request_review_artifact(%s,%s,%s,%s,%s,%s,%s)",
                [
                    pack_id,
                    organization_id,
                    actor_id,
                    expected_revision,
                    report_id,
                    job_id,
                    promote_baseline,
                ],
            )
            identity = cursor.fetchone()[0]
        return ArtifactRequest.objects.using(using).get(
            id=identity, organization_id=organization_id
        )


def _identity(value):
    if not isinstance(value, UUID):
        raise ValidationError("Typed review identity required")
    return value


def open_cycle(
    *,
    organization_id,
    actor_id,
    input_snapshot_id,
    baseline_pack_id=None,
    cycle_id=None,
    using="default",
):
    for value in (organization_id, actor_id, input_snapshot_id):
        _identity(value)
    if cycle_id is not None:
        _identity(cycle_id)
    if baseline_pack_id is not None:
        raise ValidationError(
            "Baseline promotion is not qualified in the initial kernel"
        )
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
    ):
        snapshot = AssessmentSnapshot.objects.using(using).get(
            id=input_snapshot_id, organization_id=organization_id
        )
        if not verify_snapshot(snapshot):
            raise ValidationError("Review snapshot integrity failed")
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.open_review_cycle(%s,%s,%s,%s)",
                [
                    cycle_id if cycle_id is not None else uuid4(),
                    organization_id,
                    actor_id,
                    input_snapshot_id,
                ],
            )
            identity = cursor.fetchone()[0]
        return ReviewCycle.objects.using(using).get(
            id=identity, organization_id=organization_id
        )


def freeze_cycle(
    *, cycle_id, organization_id, actor_id, expected_revision, using="default"
):
    for value in (cycle_id, organization_id, actor_id):
        _identity(value)
    if type(expected_revision) is not int or expected_revision != 1:
        raise ValidationError("Initial freeze requires exact OPEN revision 1")
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
    ):
        cycle = (
            ReviewCycle.objects.using(using)
            .select_related("input_snapshot")
            .get(id=cycle_id, organization_id=organization_id)
        )
        if not verify_snapshot(cycle.input_snapshot):
            raise ValidationError("Review snapshot integrity failed")
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.freeze_review_cycle(%s,%s,%s,%s)",
                [cycle_id, organization_id, actor_id, expected_revision],
            )
            identity = cursor.fetchone()[0]
        return PackIdentity.objects.using(using).get(
            id=identity, organization_id=organization_id
        )
