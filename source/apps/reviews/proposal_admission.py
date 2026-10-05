"""Request identity-only database issuance; no provider actions or truth claims."""

from uuid import UUID, uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.models import AssessmentSnapshot
from apps.jobs.core_models import ActionCardRevision

from .models import CaptureProposalAdmissionReceipt
from .proposals_v1 import VERSION, validate_review_proposals


def issue_capture_proposals(*, organization_id, actor_id, snapshot_id, using="default"):
    """Issue one exact capture-v1 proposal revision behind both closed gates.

    SQL recomputes source questions and permanent accounting results. Python
    independently compares its permanent contract; disagreement rolls back.
    """
    if any(
        type(value) is not UUID for value in (organization_id, actor_id, snapshot_id)
    ):
        raise ValidationError(
            "Exact proposal owner, organization and snapshot UUIDs required"
        )
    if not getattr(settings, "CORE_PROPOSAL_ADMISSION_ENABLED", False):
        raise ValidationError("Core proposal deployment gate closed")
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
    ):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_core_exposure_proposals(%s,%s,%s,%s)",
                [uuid4(), organization_id, actor_id, snapshot_id],
            )
            revision_id = cursor.fetchone()[0]
        revision = ActionCardRevision.objects.using(using).get(
            id=revision_id, organization_id=organization_id, snapshot_id=snapshot_id
        )
        snapshot = AssessmentSnapshot.objects.using(using).get(
            id=snapshot_id, organization_id=organization_id
        )
        receipt = CaptureProposalAdmissionReceipt.objects.using(using).get(
            revision_id=revision_id,
            snapshot_id=snapshot_id,
            organization_id=organization_id,
            contract=VERSION,
        )
        try:
            validate_review_proposals(
                snapshot_id=snapshot.id,
                capture_envelope={
                    "input_payload": snapshot.input_payload,
                    "result_payload": snapshot.result_payload,
                    "input_sha256": snapshot.input_sha256,
                    "result_sha256": snapshot.result_sha256,
                },
                proposals=revision.cards,
            )
        except ValueError as error:
            raise ValidationError("Issued proposal contract disagreement") from error
        if receipt.revision_sha256 != revision.sha256:
            raise ValidationError("Issued proposal receipt identity mismatch")
        return revision
