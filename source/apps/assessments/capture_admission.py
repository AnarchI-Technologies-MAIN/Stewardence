"""Gated issuance; deterministic result computation remains trusted Python.

A signed preview provides user integrity, not SQL role authority. The issuer
separately compares the reviewed frame to locked tenant source and DB time.
Schema-2 freeze/rendering is not enabled by issuing a snapshot.
"""

import json
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction

from .capture_v1 import build_capture_payloads
from .models import AssessmentSnapshot


def _identities(organization_id, actor_id):
    if type(organization_id) is not UUID or type(actor_id) is not UUID:
        raise ValidationError("Typed capture identities required")
    if not getattr(settings, "DELIBERATE_CAPTURE_ENABLED", False):
        raise ValidationError("Deliberate capture deployment gate closed")


def prepare_capture_preview(*, organization_id, actor_id, using="default"):
    """Return a server-derived reviewed frame; no persistent writes."""
    _identities(organization_id, actor_id)
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
    ):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.prepare_capture_preview(%s,%s)",
                [organization_id, actor_id],
            )
            value = cursor.fetchone()[0]
            return json.loads(value) if type(value) is str else value


def issue_deliberate_capture(
    *, organization_id, actor_id, reviewed_frame, using="default"
):
    """Qualify computation before the narrow issuer admits exact live pins."""
    _identities(organization_id, actor_id)
    if type(reviewed_frame) is not dict or set(reviewed_frame) != {
        "schema",
        "capture_id",
        "reviewed_at",
        "organization_id",
        "actor_id",
        "industry",
        "workflow_profile",
        "inventory_records",
        "excluded_active_count",
        "legacy_active_count",
    }:
        raise ValidationError("Exact reviewed capture frame required")
    if (
        reviewed_frame["schema"] != "core.capture.preview.v1"
        or reviewed_frame["organization_id"] != str(organization_id)
        or reviewed_frame["actor_id"] != str(actor_id)
    ):
        raise ValidationError("Reviewed capture identity invalid")
    try:
        profile = reviewed_frame["workflow_profile"]
        envelope = build_capture_payloads(
            organization_id=organization_id,
            created_by_id=actor_id,
            assessment_id=UUID(reviewed_frame["capture_id"]),
            assessment_version=1,
            captured_at=datetime.fromisoformat(
                reviewed_frame["reviewed_at"].replace("Z", "+00:00")
            ),
            industry=reviewed_frame["industry"],
            workflow_profile_id=UUID(profile["id"]),
            workflow_profile=profile["profile"],
            workflow_settings=profile["settings"],
            inventory_records=reviewed_frame["inventory_records"],
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ValidationError("Reviewed capture contract invalid") from error
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
    ):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_deliberate_capture(%s,%s,"
                "%s::jsonb,%s::jsonb)",
                [
                    organization_id,
                    actor_id,
                    json.dumps(reviewed_frame, allow_nan=False),
                    json.dumps(envelope, allow_nan=False),
                ],
            )
            snapshot_id = cursor.fetchone()[0]
        return AssessmentSnapshot.objects.using(using).get(
            id=snapshot_id, organization_id=organization_id
        )
