"""Owner statements on exact immutable proposals, never execution authority."""

import json
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction


def record_decision(
    *,
    organization_id,
    actor_id,
    revision_id,
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
    if not getattr(settings, "DECISION_DESK_ENABLED", False):
        raise PermissionDenied("DecisionDesk admission is disabled")
    envelope = {
        "schema": "stewardence.core_decision.v1",
        "revision_id": str(UUID(str(revision_id))),
        "card_index": card_index,
        "expected_previous_event": str(UUID(str(expected_previous_event)))
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
    ):
        with connections[using].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_core_decision(%s,%s,%s::jsonb)",
                [organization_id, actor_id, json.dumps(envelope)],
            )
            return cursor.fetchone()[0]
