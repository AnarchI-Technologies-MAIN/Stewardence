"""Statements on exact admitted capture proposals; never source resolution."""

import json
import re
from datetime import date
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction


def record_capture_decision(
    *,
    organization_id,
    actor_id,
    revision_id,
    proposal_id,
    proposal_sha256,
    card_index,
    event_kind,
    state,
    responsible_label,
    expected_previous_event=None,
    due_date=None,
    notes="",
    links=(),
    using="default",
):
    if not getattr(settings, "DECISION_DESK_ENABLED", False) or not getattr(
        settings, "CORE_PROPOSAL_ADMISSION_ENABLED", False
    ):
        raise PermissionDenied("Capture DecisionDesk admission is disabled")
    if any(
        type(value) is not UUID
        for value in (
            organization_id,
            actor_id,
            revision_id,
            proposal_id,
        )
    ) or (
        expected_previous_event is not None
        and type(expected_previous_event) is not UUID
    ):
        raise ValidationError("Exact decision identities required")
    if (
        type(proposal_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", proposal_sha256) is None
        or type(card_index) is not int
        or card_index < 0
        or (due_date is not None and type(due_date) is not date)
        or type(links) not in (list, tuple)
    ):
        raise ValidationError("Exact decision fields required")
    envelope = {
        "schema": "stewardence.core_decision.v2",
        "revision_id": str(revision_id),
        "proposal_id": str(proposal_id),
        "proposal_sha256": proposal_sha256,
        "card_index": card_index,
        "expected_previous_event": str(expected_previous_event)
        if expected_previous_event is not None
        else None,
        "event_kind": event_kind,
        "state": state,
        "responsible_label": responsible_label,
        "due_date": due_date.isoformat() if due_date is not None else None,
        "notes": notes,
        "links": list(links),
    }
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
        connections[using].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.issue_core_capture_decision(%s,%s,%s::jsonb)",
            [organization_id, actor_id, json.dumps(envelope)],
        )
        return cursor.fetchone()[0]
