"""Owner-read binding of frozen v4 content to actual immutable issuance rows."""

from datetime import datetime

from .capture_context import digest
from .capture_event_v2 import validate_frozen_capture_selection
from .models import CaptureProposalAdmissionReceipt
from .proposals_v1 import APPLICABILITY_VERSION, VERSION


def read_frozen_capture_entries(pack, snapshot):
    from apps.assessments.models import SnapshotCaptureReceipt
    from apps.jobs.core_models import DecisionEvent

    manifest = pack.manifest
    validate_frozen_capture_selection(
        manifest=manifest,
        snapshot_input=snapshot.input_payload,
        snapshot_result=snapshot.result_payload,
    )
    if (
        digest(manifest) != pack.sha256
        or manifest["cycle_id"] != str(pack.cycle_id)
        or manifest["organization_id"] != str(pack.organization_id)
        or manifest["snapshot"]["snapshot_id"] != str(snapshot.id)
        or pack.organization_id != snapshot.organization_id
    ):
        raise ValueError("Frozen capture pack identity mismatch")
    capture = SnapshotCaptureReceipt.objects.filter(
        snapshot_id=snapshot.id,
        organization_id=pack.organization_id,
        created_by_id=snapshot.created_by_id,
    ).first()
    receipt = (
        CaptureProposalAdmissionReceipt.objects.select_related("revision")
        .filter(
            snapshot_id=snapshot.id,
            organization_id=pack.organization_id,
            created_by_id=snapshot.created_by_id,
        )
        .first()
    )
    if capture is None or receipt is None:
        raise ValueError("Frozen capture proposal issuance missing")
    expected_capture = {
        "receipt_id": str(capture.id),
        "request_sha256": capture.request_sha256,
        "contract": "core.capture.declarations.v1",
        "exposure_contract": "core.exposure.declarations.v1",
    }
    revision = receipt.revision
    qualification = digest(
        {
            "schema": APPLICABILITY_VERSION,
            "industry_applicability": snapshot.input_payload["industry_applicability"],
            "ruleset": snapshot.input_payload["rulesets"]["industry"],
            "engine_versions": snapshot.input_payload["engine_versions"],
        }
    )
    if (
        manifest["capture"] != expected_capture
        or capture.id != snapshot.id
        or digest(capture.reviewed_frame) != capture.request_sha256
        or receipt.capture_receipt_id != capture.id
        or receipt.contract != VERSION
        or receipt.input_sha256 != snapshot.input_sha256
        or receipt.result_sha256 != snapshot.result_sha256
        or receipt.revision_sha256 != revision.sha256
        or receipt.qualification_sha256 != qualification
        or revision.input_sha256 != snapshot.result_sha256
        or revision.organization_id != pack.organization_id
        or revision.snapshot_id != snapshot.id
        or revision.created_by_id != snapshot.created_by_id
        or digest(revision.cards) != revision.sha256
    ):
        raise ValueError("Frozen capture proposal receipt mismatch")
    for index, selected in enumerate(manifest["selected_proposals"]):
        if (
            selected["proposal_receipt_id"] != str(receipt.id)
            or selected["revision_id"] != str(revision.id)
            or selected["revision_sha256"] != revision.sha256
            or selected["card_index"] != index
            or selected["proposal"] != revision.cards[index]
            or selected["qualification_sha256"] != receipt.qualification_sha256
        ):
            raise ValueError("Frozen capture selection issuance mismatch")
    selected_events = manifest["selected_decisions"]
    events = {
        str(event.id): event
        for event in DecisionEvent.objects.filter(
            id__in=[selected["event_id"] for selected in selected_events],
            organization_id=pack.organization_id,
            snapshot_id=snapshot.id,
            revision_id=revision.id,
        )
    }
    entries = []
    for selected in selected_events:
        event = events.get(selected["event_id"])
        if (
            event is None
            or type(event.card_index) is not int
            or not 0 <= event.card_index < len(revision.cards)
        ):
            raise ValueError("Frozen capture statement index invalid")
        if (
            selected["payload"] != event.payload
            or selected["event_sha256"] != event.sha256
            or digest(event.payload) != event.sha256
            or event.card_sha256 != digest(revision.cards[event.card_index])
            or event.revision_sha256 != revision.sha256
            or event.snapshot_result_sha256 != snapshot.result_sha256
            or event.payload["revision_sha256"] != event.revision_sha256
            or event.payload["snapshot_result_sha256"] != event.snapshot_result_sha256
            or event.payload["card_sha256"] != event.card_sha256
            or event.payload["id"] != str(event.id)
            or event.payload["organization_id"] != str(event.organization_id)
            or event.payload["created_by_id"] != str(event.created_by_id)
            or event.payload["revision_id"] != str(event.revision_id)
            or event.payload["snapshot_id"] != str(event.snapshot_id)
            or event.payload["previous_event_id"]
            != (str(event.previous_event_id) if event.previous_event_id else None)
            or event.payload["due_date"]
            != (event.due_date.isoformat() if event.due_date else None)
            or datetime.fromisoformat(
                event.payload["created_at"].replace("Z", "+00:00")
            )
            != event.created_at
            or any(
                event.payload[field] != getattr(event, field)
                for field in (
                    "card_index",
                    "sequence",
                    "event_kind",
                    "state",
                    "responsible_label",
                    "notes",
                    "links",
                )
            )
        ):
            raise ValueError("Frozen capture statement issuance mismatch")
        entries.append(
            {
                "selection": selected,
                "event": event,
                "proposal": revision.cards[event.card_index],
            }
        )
    return entries
