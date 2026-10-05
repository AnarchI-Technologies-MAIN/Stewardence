import hashlib
import re
import rfc8785
from .models import RecoveryReceipt


def record_recovery_receipt(job, outcome, *, reason_code="", fingerprint="", using="default"):
    if outcome not in {"completed", "retry", "review"}:
        raise ValueError("Unsupported recovery outcome")
    if reason_code not in {"", "job_execution_failed", "job_requires_review", "retry_limit_reached", "lease_expired"}:
        raise ValueError("Unsupported recovery reason")
    payload = {"schema":"stewardence.recovery.v1", "job_id":str(job.id),
        "organization_id":str(job.organization_id), "operation":job.job_type,
        "attempt":job.attempts, "outcome":outcome,
        "input_sha256":hashlib.sha256(rfc8785.dumps(job.payload)).hexdigest(),
        "reason_code":reason_code, "failure_fingerprint":fingerprint}
    digest = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    receipt, created = RecoveryReceipt.objects.using(using).get_or_create(
        organization_id=job.organization_id, job_id=job.id,
        attempt=job.attempts, outcome=outcome, defaults={"payload":payload, "sha256":digest})
    if not created and (receipt.payload != payload or receipt.sha256 != digest):
        raise ValueError("Recovery receipt conflicts with recorded outcome")
    return receipt


def verify_recovery_receipt(receipt):
    try:
        return _verify_recovery_receipt(receipt)
    except (TypeError, ValueError, AttributeError):
        return False


def _verify_recovery_receipt(receipt):
    payload = receipt.payload
    if not isinstance(payload, dict):
        return False
    expected = {"schema":"stewardence.recovery.v1", "job_id":str(receipt.job_id),
        "organization_id":str(receipt.organization_id), "attempt":receipt.attempt,
        "outcome":receipt.outcome}
    if any(payload.get(key) != value for key, value in expected.items()):
        return False
    if set(payload) != {"schema", "job_id", "organization_id", "attempt", "outcome", "operation",
                        "input_sha256", "reason_code", "failure_fingerprint"}:
        return False
    job = receipt.job
    if job.organization_id != receipt.organization_id or job.job_type != payload["operation"]:
        return False
    if isinstance(payload["attempt"], bool) or type(payload["attempt"]) is not int or payload["attempt"] < 1:
        return False
    if payload["input_sha256"] != hashlib.sha256(rfc8785.dumps(job.payload)).hexdigest():
        return False
    if receipt.outcome == "completed":
        if payload["reason_code"] != "" or payload["failure_fingerprint"] != "":
            return False
    elif receipt.outcome in {"retry", "review"}:
        if payload["reason_code"] not in {"job_execution_failed", "job_requires_review", "retry_limit_reached", "lease_expired"}:
            return False
        if receipt.outcome == "retry" and payload["reason_code"] not in {"job_execution_failed", "lease_expired"}:
            return False
        if receipt.outcome == "review" and payload["reason_code"] == "job_execution_failed":
            return False
        if not isinstance(payload["failure_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", payload["failure_fingerprint"]):
            return False
    else:
        return False
    try:
        return hashlib.sha256(rfc8785.dumps(payload)).hexdigest() == receipt.sha256
    except (TypeError, ValueError):
        return False
