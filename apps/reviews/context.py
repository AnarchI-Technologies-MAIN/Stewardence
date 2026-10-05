"""Trusted projection-to-render boundary; no provider or live evidence reads."""

import hashlib
import json
from copy import deepcopy

import rfc8785

from .exposure import historical_review_record

VERSION = "AL-REVIEW-PACK-CONTEXT-1"


def _sha(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def build_pack_context(legacy_context, projection):
    if (
        type(projection) is dict
        and projection.get("schema") == "stewardence.review_worker_projection.v3"
    ):
        from .capture_context_v3 import build_capture_v4_pack_context

        return build_capture_v4_pack_context(legacy_context["metadata"], projection)
    if (
        type(projection) is dict
        and projection.get("schema") == "stewardence.review_worker_projection.v2"
    ):
        from .capture_context import build_capture_pack_context

        return build_capture_pack_context(legacy_context["metadata"], projection)
    if (
        type(projection) is not dict
        or projection.get("schema") != "stewardence.review_worker_projection.v1"
    ):
        raise ValueError("Admitted review projection required")
    manifest = projection["manifest"]
    inputs = projection["snapshot_input"]
    results = projection["snapshot_result"]
    pinned = manifest["snapshot"]
    metadata = legacy_context["metadata"]
    if (
        manifest["organization_id"] != projection["organization_id"]
        or inputs["organization_id"] != projection["organization_id"]
        or _sha(manifest) != projection["manifest_sha256"]
        or _sha(inputs) != pinned["input_sha256"]
        or _sha(results) != pinned["result_sha256"]
        or metadata["assessment_snapshot_id"] != pinned["snapshot_id"]
        or metadata["assessment_date"] != pinned["captured_at"]
        or metadata["input_sha256"] != pinned["input_sha256"]
        or metadata["result_sha256"] != pinned["result_sha256"]
    ):
        raise ValueError("Review render snapshot identity mismatch")
    selected = projection["selected_decisions"]
    if (
        type(selected) is not list
        or [item["selection"] for item in selected] != manifest["selected_decisions"]
    ):
        raise ValueError("Review frozen decision selection mismatch")
    seen = set()
    for item in selected:
        selection = item["selection"]
        payload = item["payload"]
        key = (selection["revision_id"], selection["card_index"])
        if (
            key in seen
            or _sha(payload) != item["event_sha256"]
            or item["event_sha256"] != selection["event_sha256"]
            or _sha(item["proposal"]) != selection["card_sha256"]
            or payload["id"] != selection["event_id"]
            or payload["organization_id"] != projection["organization_id"]
            or any(
                payload[field] != selection[field]
                for field in (
                    "revision_id",
                    "revision_sha256",
                    "card_index",
                    "card_sha256",
                    "event_kind",
                    "state",
                )
            )
            or payload["snapshot_id"] != pinned["snapshot_id"]
            or payload["snapshot_result_sha256"] != pinned["result_sha256"]
            or payload["owner_statement_only"] is not True
            or payload["resolution_verified"] is not False
        ):
            raise ValueError("Review selected statement identity mismatch")
        seen.add(key)
    records = inputs["inventory"]
    if type(records) is not list or any(type(row) is not dict for row in records):
        raise ValueError("Review captured inventory invalid")
    identities = [row["id"] for row in records]
    if (
        len(set(identities)) != len(identities)
        or [row["id"] for row in legacy_context["inventory"]] != identities
    ):
        raise ValueError("Review captured inventory identity or order mismatch")
    context = deepcopy(legacy_context)
    context["context_version"] = VERSION
    context["title"] = "Frozen AI Evidence Review Pack"
    context["review_pack"] = {
        "schema": "stewardence.review_pack_render.v1",
        "pack_id": projection["pack_id"],
        "manifest_sha256": projection["manifest_sha256"],
        "manifest": deepcopy(manifest),
        "selected_decisions": deepcopy(selected),
        "exposure_reviews": [
            {
                "source_record": deepcopy(row),
                "review": json.loads(
                    json.dumps(historical_review_record(row, manifest["schema"]))
                ),
            }
            for row in records
        ],
    }
    return context
