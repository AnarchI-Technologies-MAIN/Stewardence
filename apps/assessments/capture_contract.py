"""Compatibility entrypoint pinned to permanent capture v1.

A successor capture contract requires explicit version dispatch, never changing
the implementation selected for existing schema-2 snapshots and pack v3.
"""

from .capture_v1 import (
    CONTRACT,
    DECLARATION_CONTRACT,
    EXPOSURE_VERSION,
    INDUSTRIES,
    INT_FIELDS,
    LIST_FIELDS,
    POLICY_CONTRACT,
    RECORD_KEYS,
    build_capture_payloads,
    validate_capture_payloads,
)

__all__ = [
    "CONTRACT",
    "POLICY_CONTRACT",
    "EXPOSURE_VERSION",
    "DECLARATION_CONTRACT",
    "INDUSTRIES",
    "LIST_FIELDS",
    "INT_FIELDS",
    "RECORD_KEYS",
    "build_capture_payloads",
    "validate_capture_payloads",
]
