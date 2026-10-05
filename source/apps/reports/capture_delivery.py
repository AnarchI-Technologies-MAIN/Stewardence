"""Read-only capture delivery receipts; byte verification remains separate."""

from apps.assessments.snapshots import canonical_sha256
from apps.reviews.models import PackCompletion

from .storage import ReportStorageError


def require_capture_completion(artifact):
    try:
        return _require_capture_completion(artifact)
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise ReportStorageError("Malformed capture delivery receipt") from error


def _require_capture_completion(artifact):
    completion = (
        PackCompletion.objects.filter(
            artifact_id=artifact.id,
            organization_id=artifact.organization_id,
            request__report_id=artifact.report_id,
        )
        .select_related("request__pack")
        .first()
    )
    if completion is None:
        raise ReportStorageError("Committed capture delivery receipt missing")
    request, pack = completion.request, completion.request.pack
    payload = completion.payload
    if type(payload) is not dict or type(pack.manifest) is not dict:
        raise ReportStorageError("Capture delivery receipt structure invalid")
    if (
        pack.organization_id != artifact.organization_id
        or request.organization_id != artifact.organization_id
        or canonical_sha256(payload) != completion.sha256
        or canonical_sha256(pack.manifest) != pack.sha256
        or request.manifest_sha256 != pack.sha256
        or payload.get("schema") != "stewardence.review_pack_completion.v2"
        or payload.get("request_id") != str(request.id)
        or payload.get("pack_id") != str(pack.id)
        or payload.get("manifest_sha256") != pack.sha256
        or payload.get("artifact_id") != str(artifact.id)
        or payload.get("artifact_sha256") != artifact.sha256
        or type(payload.get("artifact_bytes")) is not int
        or payload.get("artifact_bytes") != artifact.size_bytes
        or payload.get("verification") != "trusted_handler_storage_readback"
        or pack.manifest.get("schema")
        not in {"stewardence.review_pack.v3", "stewardence.review_pack.v4"}
        or pack.manifest.get("snapshot", {}).get("snapshot_id")
        != str(artifact.assessment_snapshot_id)
        or pack.manifest.get("organization_id") != str(artifact.organization_id)
    ):
        raise ReportStorageError("Capture delivery receipt integrity failed")
    if pack.manifest["schema"] == "stewardence.review_pack.v4":
        from apps.reviews.capture_pack_reads import read_frozen_capture_entries

        read_frozen_capture_entries(pack, artifact.assessment_snapshot)
    return completion
