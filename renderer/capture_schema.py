"""Standalone closed renderer contract: no application/database imports."""

import json
from datetime import date

from .schema import (
    MAX_PAYLOAD_BYTES,
    REPORT_IDENTIFIER,
    InvalidReportRenderPayload,
    _closed,
    _digest,
    _sha,
    _timestamp,
    _uuid,
    _validate_tree,
)


def validate_capture_render_payload(report):
    try:
        return _validate(report)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, InvalidReportRenderPayload):
            raise
        raise InvalidReportRenderPayload(
            "Malformed capture review render contract"
        ) from error


def _validate(report):
    _closed(
        report,
        {"context_version", "title", "metadata", "projection", "exposure_reviews"},
    )
    if (
        report["context_version"] != "AL-REVIEW-PACK-CONTEXT-2"
        or report["title"] != "Frozen Tool Exposure Evidence Pack"
    ):
        raise InvalidReportRenderPayload("Unsupported capture review title/version")
    if (
        len(
            json.dumps(
                report, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        )
        > MAX_PAYLOAD_BYTES
    ):
        raise InvalidReportRenderPayload("Payload is too large")
    _validate_tree(report)
    metadata = report["metadata"]
    _closed(
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
        type(metadata["organization_display_name"]) is not str
        or not metadata["organization_display_name"].strip()
        or not REPORT_IDENTIFIER.fullmatch(metadata["report_identifier"])
    ):
        raise InvalidReportRenderPayload("Invalid capture report identity")
    if (
        type(metadata["assessment_version"]) is not int
        or metadata["assessment_version"] != 1
    ):
        raise InvalidReportRenderPayload(
            "Capture metadata assessment version must be integer one"
        )
    p = report["projection"]
    _closed(
        p,
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
        },
    )
    if p["schema"] != "stewardence.review_worker_projection.v2":
        raise InvalidReportRenderPayload("Unsupported capture projection")
    for field in ("request_id", "job_id", "report_id", "organization_id", "pack_id"):
        _uuid(p[field])
    m = p["manifest"]
    _closed(
        m,
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
        },
    )
    capture = m["capture"]
    _closed(capture, {"receipt_id", "request_sha256", "contract", "exposure_contract"})
    _uuid(capture["receipt_id"])
    _sha(capture["request_sha256"])
    if (
        capture["contract"] != "core.capture.declarations.v1"
        or capture["exposure_contract"] != "core.exposure.declarations.v1"
    ):
        raise InvalidReportRenderPayload("Capture issuance pin invalid")
    _uuid(m["cycle_id"])
    if m["baseline_pack_id"] is not None:
        raise InvalidReportRenderPayload(
            "Initial capture pack has no admitted baseline"
        )
    if (
        m["schema"] != "stewardence.review_pack.v3"
        or m["organization_id"] != p["organization_id"]
        or m["selected_decisions"] != []
        or p["selected_decisions"] != []
        or m["selection_scope"] != "empty_capture_kernel"
        or m["artifact_state"] != "not_created"
        or m["baseline_promotion"] != "blocked"
        or _digest(m) != p["manifest_sha256"]
    ):
        raise InvalidReportRenderPayload("Capture frozen manifest mismatch")
    s = m["snapshot"]
    _closed(
        s,
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
        },
    )
    for key in ("snapshot_id", "assessment_id", "workflow_profile_id"):
        _uuid(s[key])
    if (
        capture["receipt_id"] != s["snapshot_id"]
        or s["snapshot_id"] != s["assessment_id"]
    ):
        raise InvalidReportRenderPayload("Capture receipt snapshot identity mismatch")
    for key in (
        "input_sha256",
        "result_sha256",
        "workflow_settings_sha256",
        "rules_sha256",
        "configuration_sha256",
    ):
        _sha(s[key])
    _timestamp(s["captured_at"])
    for source, target in (
        ("snapshot_id", "assessment_snapshot_id"),
        ("assessment_id", "assessment_id"),
        ("assessment_version", "assessment_version"),
        ("captured_at", "assessment_date"),
        ("input_sha256", "input_sha256"),
        ("result_sha256", "result_sha256"),
    ):
        if s[source] != metadata[target]:
            raise InvalidReportRenderPayload("Capture metadata pin mismatch")
    i, r = p["snapshot_input"], p["snapshot_result"]
    _closed(
        i,
        {
            "snapshot_schema_version",
            "capture_contract",
            "assessment",
            "organization_id",
            "created_by_id",
            "captured_at",
            "industry_applicability",
            "workflow_profile",
            "inventory",
            "evidence_references",
            "benefit_model",
            "rulesets",
            "risk_configuration",
            "engine_versions",
        },
    )
    _closed(
        r,
        {
            "snapshot_schema_version",
            "capture_contract",
            "assessment",
            "industry_applicability",
            "benefit_model",
            "inventory_results",
        },
    )
    _uuid(i["created_by_id"])
    if (
        type(s["snapshot_schema"]) is not int
        or s["snapshot_schema"] != 2
        or type(s["assessment_version"]) is not int
        or s["assessment_version"] != 1
        or any(
            type(x["snapshot_schema_version"]) is not int
            or x["snapshot_schema_version"] != 2
            or x["capture_contract"] != "core.capture.declarations.v1"
            for x in (i, r)
        )
        or s["capture_contract"] != i["capture_contract"]
        or _digest(i) != s["input_sha256"]
        or _digest(r) != s["result_sha256"]
        or i["organization_id"] != p["organization_id"]
        or i["captured_at"] != s["captured_at"]
        or i["assessment"] != r["assessment"]
        or i["assessment"]
        != {"id": s["assessment_id"], "version": s["assessment_version"]}
        or i["benefit_model"] != {"state": "not_supplied"}
        or r["benefit_model"] != i["benefit_model"]
        or i["risk_configuration"] != {"state": "not_assessed"}
        or i["evidence_references"] != []
    ):
        raise InvalidReportRenderPayload("Capture input/result binding mismatch")
    profile = i["workflow_profile"]
    _closed(profile, {"id", "profile", "settings", "settings_sha256"})
    if (
        profile["id"] != s["workflow_profile_id"]
        or profile["profile"] != s["workflow_profile"]
        or profile["profile"] not in ("business.v1", "development.v1")
        or _digest(profile["settings"]) != profile["settings_sha256"]
        or profile["settings_sha256"] != s["workflow_settings_sha256"]
        or _digest(i["rulesets"]) != s["rules_sha256"]
        or _digest(i["risk_configuration"]) != s["configuration_sha256"]
        or i["engine_versions"] != s["engine_versions"]
    ):
        raise InvalidReportRenderPayload("Capture frozen workflow/rule mismatch")
    a = i["industry_applicability"]
    _closed(a, {"industry", "policy_state", "reason", "generic_exposure"})
    accounting = a["industry"] == "accounting_bookkeeping"
    if (
        a["industry"]
        not in {
            "accounting_bookkeeping",
            "legal",
            "healthcare",
            "construction",
            "agency",
            "other",
        }
        or a != r["industry_applicability"]
        or a["generic_exposure"] != "core.exposure.declarations.v1"
        or a["policy_state"] != ("applicable" if accounting else "not_assessed")
        or a["reason"]
        != ("accounting_pack_selected" if accounting else "no_qualified_industry_pack")
    ):
        raise InvalidReportRenderPayload("Capture industry applicability mismatch")
    rows, results, exposures = (
        i["inventory"],
        r["inventory_results"],
        report["exposure_reviews"],
    )
    if (
        any(type(x) is not list for x in (rows, results, exposures))
        or not 1 <= len(rows) <= 100
        or len(rows) != len(results)
        or len(rows) != len(exposures)
    ):
        raise InvalidReportRenderPayload("Capture inventory bounds invalid")
    ids = [row["id"] for row in rows]
    if ids != sorted(set(ids), key=lambda v: int(v.replace("-", ""), 16)):
        raise InvalidReportRenderPayload("Capture inventory order/identity invalid")
    for row, result, exposure in zip(rows, results, exposures, strict=True):
        _uuid(row["id"])
        _validate_record(row, s["captured_at"])
        _closed(result, {"inventory_item_id", "policy_results", "risk"})
        if (
            result["inventory_item_id"] != row["id"]
            or result["risk"] != {"state": "not_assessed", "score": None, "band": None}
            or type(result["policy_results"]) is not list
            or (not accounting and result["policy_results"] != [])
        ):
            raise InvalidReportRenderPayload("Capture risk/policy semantics invalid")
        _closed(
            exposure,
            {
                "schema",
                "inventory_item_id",
                "record_sha256",
                "questions",
                "authority",
                "verification",
                "sha256",
            },
        )
        if (
            exposure["schema"] != a["generic_exposure"]
            or exposure["inventory_item_id"] != row["id"]
            or exposure["record_sha256"] != _digest(row)
            or exposure["authority"] != "proposal_only"
            or exposure["verification"] != "not_established"
            or exposure["sha256"]
            != _digest({k: v for k, v in exposure.items() if k != "sha256"})
        ):
            raise InvalidReportRenderPayload("Capture exposure binding invalid")
        if type(exposure["questions"]) is not list or [
            q["question_id"] for q in exposure["questions"]
        ] != [
            "business_owner",
            "business_purpose",
            "data_categories",
            "permissions",
            "capabilities",
            "approval",
            "account_identity",
            "access_removal",
        ]:
            raise InvalidReportRenderPayload("Capture exposure questions invalid")
        for q in exposure["questions"]:
            _closed(
                q,
                {
                    "question_id",
                    "outcome",
                    "explanation",
                    "source_fields",
                    "basis",
                    "verification",
                },
            )
            if (
                q["outcome"] not in {"PASS", "CONCERN", "UNKNOWN", "NOT_APPLICABLE"}
                or q["verification"] != "not_established"
                or q["basis"] not in {"unknown", "customer_declaration"}
                or type(q["explanation"]) is not str
                or type(q["source_fields"]) is not list
            ):
                raise InvalidReportRenderPayload("Capture exposure authority invalid")
            expected = _outcome(row, q["question_id"])
            if q["outcome"] != expected or q["basis"] != (
                "unknown" if expected == "UNKNOWN" else "customer_declaration"
            ):
                raise InvalidReportRenderPayload(
                    "Capture exposure declaration semantics mismatch"
                )
    return report


FACT_FIELDS = {
    "display_name",
    "vendor_name",
    "business_owner",
    "department",
    "user_count",
    "business_purpose",
    "monthly_cost_cents",
    "seat_count",
    "connected_systems",
    "data_categories",
    "permissions",
    "capabilities",
    "autonomy_level",
    "human_approval",
    "status",
}


def _validate_record(row, captured_at):
    _closed(
        row,
        FACT_FIELDS
        | {
            "id",
            "product_id",
            "source_type",
            "declaration_contract",
            "declaration_as_of",
            "provenance",
            "archived_at",
        },
    )
    provenance = row["provenance"]
    _closed(provenance, FACT_FIELDS | {"product_id", "source_type"})
    if (
        row["declaration_contract"] != "core.inventory.declarations.v1"
        or row["archived_at"] is not None
        or row["product_id"] is not None
        or provenance["product_id"] != "Unknown"
        or row["source_type"] != "manual"
        or provenance["source_type"] != "Declared"
        or provenance["display_name"] != "Declared"
        or not row["display_name"].strip()
        or date.fromisoformat(row["declaration_as_of"]).isoformat()
        != row["declaration_as_of"]
        or row["declaration_as_of"] > captured_at[:10]
    ):
        raise InvalidReportRenderPayload("Capture declaration identity invalid")
    for field in FACT_FIELDS:
        value, basis = row[field], provenance[field]
        if basis == "Unknown":
            if value is not None:
                raise InvalidReportRenderPayload("Unknown capture field must be null")
        elif basis == "Declared":
            if field in {
                "connected_systems",
                "data_categories",
                "permissions",
                "capabilities",
            }:
                if (
                    type(value) is not list
                    or any(type(v) is not str or not v or len(v) > 200 for v in value)
                    or len(value) != len(set(value))
                ):
                    raise InvalidReportRenderPayload("Invalid capture list declaration")
            elif field in {
                "user_count",
                "monthly_cost_cents",
                "seat_count",
                "autonomy_level",
            }:
                if type(value) is not int or not 0 <= value <= (
                    4 if field == "autonomy_level" else 2147483647
                ):
                    raise InvalidReportRenderPayload(
                        "Invalid capture integer declaration"
                    )
            elif field == "human_approval":
                if type(value) is not bool:
                    raise InvalidReportRenderPayload(
                        "Invalid capture approval declaration"
                    )
            elif type(value) is not str or len(value) > (
                4096 if field == "business_purpose" else 255
            ):
                raise InvalidReportRenderPayload("Invalid capture text declaration")
        else:
            raise InvalidReportRenderPayload("Explicit capture provenance required")


def _outcome(row, key):
    def declared(field):
        return row["provenance"].get(field) == "Declared"

    if key in {"account_identity", "access_removal"}:
        return "UNKNOWN"
    if key in {"business_owner", "business_purpose"}:
        return (
            "UNKNOWN"
            if not declared(key)
            else ("PASS" if row[key].strip() else "CONCERN")
        )
    if key in {"data_categories", "permissions", "capabilities"}:
        return "PASS" if declared(key) else "UNKNOWN"
    if not all(
        declared(field)
        for field in ("human_approval", "autonomy_level", "capabilities", "permissions")
    ):
        return "UNKNOWN"
    if not (row["capabilities"] or row["permissions"] or row["autonomy_level"]):
        return "NOT_APPLICABLE"
    return "PASS" if row["human_approval"] else "CONCERN"
