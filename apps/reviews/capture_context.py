"""Closed capture2 render projection; deterministic content is not issuance proof."""

import hashlib
import json
from copy import deepcopy
from uuid import UUID

import rfc8785

from apps.assessments.capture_v1 import CONTRACT, validate_capture_payloads

from .exposure_v1 import review_record

VERSION = "AL-REVIEW-PACK-CONTEXT-2"
TITLE = "Frozen Tool Exposure Evidence Pack"
PROJECTION_KEYS = frozenset(
    {
        "schema",
        "request_id",
        "job_id",
        "report_id",
        "organization_id",
        "pack_id",
        "manifest",
        "manifest_sha256",
        "snapshot_input",
        "snapshot_result",
        "selected_decisions",
    }
)
MANIFEST_KEYS = frozenset(
    {
        "schema",
        "cycle_id",
        "organization_id",
        "baseline_pack_id",
        "snapshot",
        "selected_decisions",
        "selection_scope",
        "artifact_state",
        "baseline_promotion",
        "capture",
    }
)
PIN_KEYS = frozenset(
    {
        "snapshot_id",
        "assessment_id",
        "assessment_version",
        "input_sha256",
        "result_sha256",
        "captured_at",
        "snapshot_schema",
        "workflow_profile_id",
        "workflow_profile",
        "workflow_settings_sha256",
        "rules_sha256",
        "configuration_sha256",
        "engine_versions",
        "capture_contract",
    }
)


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError("Capture review fields do not match closed contract")


def canonical_uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("Canonical capture review identity required")
    return UUID(value)


def validate_capture_projection(projection):
    closed(projection, PROJECTION_KEYS)
    if projection["schema"] != "stewardence.review_worker_projection.v2":
        raise ValueError("Capture review projection version invalid")
    for key in ("request_id", "job_id", "report_id", "organization_id", "pack_id"):
        canonical_uuid(projection[key])
    manifest = projection["manifest"]
    closed(manifest, MANIFEST_KEYS)
    capture = manifest["capture"]
    closed(capture, {"receipt_id", "request_sha256", "contract", "exposure_contract"})
    canonical_uuid(capture["receipt_id"])
    if (
        type(capture["request_sha256"]) is not str
        or len(capture["request_sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in capture["request_sha256"])
        or capture["contract"] != CONTRACT
        or capture["exposure_contract"] != "core.exposure.declarations.v1"
    ):
        raise ValueError("Capture issuance receipt binding invalid")
    pinned = manifest["snapshot"]
    closed(pinned, PIN_KEYS)
    if (
        capture["receipt_id"] != pinned["snapshot_id"]
        or pinned["snapshot_id"] != pinned["assessment_id"]
    ):
        raise ValueError("Capture receipt snapshot identity mismatch")
    for key in ("snapshot_id", "assessment_id", "workflow_profile_id"):
        canonical_uuid(pinned[key])
    canonical_uuid(manifest["cycle_id"])
    if manifest["baseline_pack_id"] is not None:
        raise ValueError("Initial capture pack has no admitted baseline")
    if (
        manifest["schema"] != "stewardence.review_pack.v3"
        or manifest["organization_id"] != projection["organization_id"]
        or manifest["selected_decisions"] != []
        or projection["selected_decisions"] != []
        or manifest["selection_scope"] != "empty_capture_kernel"
        or manifest["artifact_state"] != "not_created"
        or manifest["baseline_promotion"] != "blocked"
        or pinned["snapshot_schema"] != 2
        or type(pinned["snapshot_schema"]) is not int
        or pinned["capture_contract"] != CONTRACT
        or digest(manifest) != projection["manifest_sha256"]
    ):
        raise ValueError(
            "Capture review manifest identity or initial selection invalid"
        )
    inputs, results = projection["snapshot_input"], projection["snapshot_result"]
    validate_capture_payloads(
        {
            "input_payload": inputs,
            "result_payload": results,
            "input_sha256": pinned["input_sha256"],
            "result_sha256": pinned["result_sha256"],
        },
        organization_id=canonical_uuid(projection["organization_id"]),
        created_by_id=canonical_uuid(inputs["created_by_id"]),
        workflow_profile_id=canonical_uuid(pinned["workflow_profile_id"]),
    )
    if (
        inputs["assessment"]
        != {"id": pinned["assessment_id"], "version": pinned["assessment_version"]}
        or type(pinned["assessment_version"]) is not int
        or inputs["captured_at"] != pinned["captured_at"]
        or inputs["workflow_profile"]["profile"] != pinned["workflow_profile"]
        or inputs["workflow_profile"]["settings_sha256"]
        != pinned["workflow_settings_sha256"]
        or digest(inputs["rulesets"]) != pinned["rules_sha256"]
        or digest(inputs["risk_configuration"]) != pinned["configuration_sha256"]
        or inputs["engine_versions"] != pinned["engine_versions"]
    ):
        raise ValueError("Capture review frozen meaning mismatch")
    return projection


def build_capture_pack_context(metadata, projection):
    validate_capture_projection(projection)
    pinned = projection["manifest"]["snapshot"]
    closed(
        metadata,
        {
            "report_identifier",
            "organization_display_name",
            "assessment_date",
            "assessment_id",
            "assessment_version",
            "assessment_snapshot_id",
            "input_sha256",
            "result_sha256",
        },
    )
    if (
        type(metadata["assessment_version"]) is not int
        or metadata["assessment_version"] != 1
    ):
        raise ValueError("Capture metadata assessment version must be integer one")
    for source, target in (
        ("snapshot_id", "assessment_snapshot_id"),
        ("assessment_id", "assessment_id"),
        ("assessment_version", "assessment_version"),
        ("captured_at", "assessment_date"),
        ("input_sha256", "input_sha256"),
        ("result_sha256", "result_sha256"),
    ):
        if pinned[source] != metadata[target]:
            raise ValueError("Capture report metadata binding mismatch")
    return deepcopy(
        {
            "context_version": VERSION,
            "title": TITLE,
            "metadata": metadata,
            "projection": projection,
            "exposure_reviews": [
                json.loads(json.dumps(review_record(row)))
                for row in projection["snapshot_input"]["inventory"]
            ],
        }
    )
