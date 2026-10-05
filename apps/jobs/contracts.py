"""Versioned Core workflow admission; no transport or provider authority implied."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import re
import unicodedata
from uuid import UUID
import rfc8785

SCHEMA = "stewardence.workflow.v1"


class Operation(str, Enum):
    REPORT = "report.generate_from_receipts"
    REASSESS = "action_cards.reassess_from_signals"
    HEALTH = "core.health_check"


class BranchProfile(str, Enum):
    BUSINESS = "business.v1"
    DEVELOPMENT = "development.v1"


def validate_branch_settings(profile, settings):
    profile = BranchProfile(profile)
    if not isinstance(settings, dict):
        raise ValueError("Branch settings must be an object")
    allowed = {BranchProfile.BUSINESS:{"name", "jurisdiction", "parent_branch_id"},
               BranchProfile.DEVELOPMENT:{"name", "repository_ref", "environment"}}[profile]
    if not set(settings).issubset(allowed) or "name" not in settings:
        raise ValueError("Settings do not match selected branch profile")
    for key, value in settings.items():
        if not isinstance(value, str) or not value.strip() or not 1 <= len(value) <= 200 or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value):
            raise ValueError("Invalid branch setting")
        if key == "parent_branch_id":
            UUID(value)
        if key == "repository_ref" and not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,200}", value):
            raise ValueError("Repository reference must be an identifier without credentials")
        if key == "repository_ref" and (value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/"))):
            raise ValueError("Repository reference cannot be a filesystem path")
    # Unknown/custom profiles require a registered, versioned schema first.
    return {"profile":profile.value, "settings":dict(settings)}


@dataclass(frozen=True)
class WorkflowRequest:
    organization_id: UUID
    operation: Operation
    receipt_ids: tuple[UUID, ...]
    effective_at: datetime
    branch_profile: BranchProfile

    def __post_init__(self):
        if not isinstance(self.organization_id, UUID) or not isinstance(self.operation, Operation):
            raise ValueError("Typed organization and operation are required")
        if not isinstance(self.branch_profile, BranchProfile):
            raise ValueError("Registered branch profile required")
        if not isinstance(self.receipt_ids, tuple) or not all(isinstance(value, UUID) for value in self.receipt_ids):
            raise ValueError("Receipt identities must be immutable UUIDs")
        if len(self.receipt_ids) > 1000 or len(set(self.receipt_ids)) != len(self.receipt_ids):
            raise ValueError("Receipt selection is duplicated or too large")
        if self.operation is not Operation.HEALTH and not self.receipt_ids:
            raise ValueError("Evidence-based operations require receipts")
        if not isinstance(self.effective_at, datetime) or self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("Workflow time must include a timezone")

    def envelope(self):
        from datetime import UTC
        return {"schema":SCHEMA, "organization_id":str(self.organization_id),
            "operation":self.operation.value, "branch_profile":self.branch_profile.value,
            "receipt_ids":sorted(str(value) for value in self.receipt_ids),
            "effective_at":self.effective_at.astimezone(UTC).isoformat()}

    @property
    def input_sha256(self):
        return hashlib.sha256(rfc8785.dumps(self.envelope())).hexdigest()


def logical_evidence_directory(organization_id: UUID, category: str, record_id: UUID):
    if category not in {"services", "branches", "ai_accounts", "agents", "employees"}:
        raise ValueError("Unregistered evidence category")
    if not isinstance(organization_id, UUID) or not isinstance(record_id, UUID):
        raise ValueError("Evidence directory identities must be UUIDs")
    return f"organizations/{organization_id}/evidence/{category}/{record_id}"
