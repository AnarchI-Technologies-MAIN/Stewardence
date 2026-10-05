"""Exact v4 frozen proposals/statements; no database issuance claim here."""

from copy import deepcopy
from uuid import UUID

from apps.reviews.proposals_v1 import validate_review_proposals

from .capture_context import build_capture_pack_context, digest
from .capture_event_v2 import validate_capture_v4_render_payload

VERSION = "AL-REVIEW-PACK-CONTEXT-3"


def build_capture_v4_pack_context(metadata, projection):
    original = deepcopy(projection)
    base = deepcopy(projection)
    if base.get("schema") != "stewardence.review_worker_projection.v3":
        raise ValueError("Exact v4 projection required")
    base["schema"] = "stewardence.review_worker_projection.v2"
    base.pop("selected_proposals")
    base["selected_decisions"] = []
    manifest = base["manifest"]
    if manifest.get("schema") != "stewardence.review_pack.v4":
        raise ValueError("Exact v4 manifest required")
    manifest["schema"] = "stewardence.review_pack.v3"
    manifest.pop("selected_proposals")
    manifest.pop("proposal_contract_version")
    manifest["selected_decisions"] = []
    manifest["selection_scope"] = "empty_capture_kernel"
    base["manifest_sha256"] = digest(manifest)
    context = build_capture_pack_context(metadata, base)
    context["context_version"] = VERSION
    context["projection"] = original
    pin = original["manifest"]["snapshot"]
    validate_review_proposals(
        snapshot_id=UUID(pin["snapshot_id"]),
        capture_envelope={
            "input_payload": original["snapshot_input"],
            "result_payload": original["snapshot_result"],
            "input_sha256": pin["input_sha256"],
            "result_sha256": pin["result_sha256"],
        },
        proposals=[entry["proposal"] for entry in original["selected_proposals"]],
    )
    # Performs exact byte/resource preflight before external rendering. SQL
    # admission must separately enforce preflight before queue creation.
    return validate_capture_v4_render_payload(context)
