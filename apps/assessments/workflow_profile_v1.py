"""Permanent profile vocabulary and normalization admitted by capture v1."""

import re
import unicodedata
from enum import Enum
from uuid import UUID


class BranchProfile(str, Enum):
    BUSINESS = "business.v1"
    DEVELOPMENT = "development.v1"


def validate_branch_settings(profile, settings):
    profile = BranchProfile(profile)
    if not isinstance(settings, dict):
        raise ValueError("Branch settings must be an object")
    allowed = {
        BranchProfile.BUSINESS: {"name", "jurisdiction", "parent_branch_id"},
        BranchProfile.DEVELOPMENT: {"name", "repository_ref", "environment"},
    }[profile]
    if not set(settings).issubset(allowed) or "name" not in settings:
        raise ValueError("Settings do not match selected branch profile")
    for key, value in settings.items():
        if (
            not isinstance(value, str)
            or not value.strip()
            or not 1 <= len(value) <= 200
            or any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value)
        ):
            raise ValueError("Invalid branch setting")
        if key == "parent_branch_id":
            UUID(value)
        if key == "repository_ref" and not re.fullmatch(
            r"[A-Za-z0-9_.\-/]{1,200}", value
        ):
            raise ValueError(
                "Repository reference must be an identifier without credentials"
            )
        if key == "repository_ref" and (
            value.startswith("/")
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise ValueError("Repository reference cannot be a filesystem path")
    # Unknown/custom profiles require a registered, versioned schema first.
    return {"profile": profile.value, "settings": dict(settings)}
