#!/usr/bin/env python3
"""Validate AgentLedger control files and report MVP checklist status.

This script deliberately does not infer product completion from file existence.
`--control-files` validates the Phase 0 control plane. `--require-complete`
additionally fails unless every checklist item is marked verified.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CHECKLIST = DOCS / "MVP_CHECKLIST.md"
SPEC = DOCS / "SPEC-1-AgentLedger-v1.8.md"
EXPECTED_SPEC_SHA256 = (
    "e42e9d400d93b269a968322c988a9cde5b0f244484e81641206cc092da4aa401"
)
REQUIRED_FILES = (
    SPEC,
    CHECKLIST,
    DOCS / "DEPLOYMENT_RAILWAY.md",
    DOCS / "SECURITY_INVARIANTS.md",
    DOCS / "CUSTOMER_PILOT_RUNBOOK.md",
    Path(__file__).resolve(),
)
CHECKBOX_RE = re.compile(r"^- \[(?P<status>[ ~x])\] (?P<label>\S.*)$")
REQUIRED_PHASES = tuple(range(24))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def control_errors() -> list[str]:
    errors: list[str] = []
    for path in REQUIRED_FILES:
        if not path.is_file():
            errors.append(f"missing required control file: {path.relative_to(ROOT)}")

    if SPEC.is_file():
        actual_hash = sha256(SPEC)
        if actual_hash != EXPECTED_SPEC_SHA256:
            errors.append(
                "specification hash mismatch: "
                f"expected {EXPECTED_SPEC_SHA256}, got {actual_hash}"
            )

    if CHECKLIST.is_file():
        text = CHECKLIST.read_text(encoding="utf-8")
        for phase in REQUIRED_PHASES:
            marker = f"## Phase {phase} "
            if marker not in text:
                errors.append(f"checklist is missing Phase {phase}")

        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.startswith("- [") and CHECKBOX_RE.fullmatch(line) is None:
                errors.append(
                    f"invalid checklist syntax at line {line_number}: {line!r}"
                )

        if not any(CHECKBOX_RE.fullmatch(line) for line in text.splitlines()):
            errors.append("checklist contains no tracked exit conditions")

    return errors


def checklist_status() -> tuple[Counter[str], list[str]]:
    counts: Counter[str] = Counter()
    pending: list[str] = []
    if not CHECKLIST.is_file():
        return counts, pending

    for line in CHECKLIST.read_text(encoding="utf-8").splitlines():
        match = CHECKBOX_RE.fullmatch(line)
        if match is None:
            continue
        status = match.group("status")
        counts[status] += 1
        if status != "x":
            pending.append(match.group("label"))
    return counts, pending


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--control-files",
        action="store_true",
        help="validate only the Phase 0 control-file baseline",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="fail unless every MVP checklist item is verified",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = control_errors()
    if errors:
        print("CONTROL FILE VERIFICATION: FAIL")
        for error in errors:
            print(f"- {error}")
        return 2

    print("CONTROL FILE VERIFICATION: PASS")
    counts, pending = checklist_status()
    total = sum(counts.values())
    print(
        "MVP CHECKLIST: "
        f"{counts['x']} verified, {counts['~']} in progress, "
        f"{counts[' ']} not started, {total} total"
    )

    if args.control_files and not args.require_complete:
        return 0

    if pending:
        print("MVP RELEASE GATE: NOT READY")
        if args.require_complete:
            print(f"First incomplete item: {pending[0]}")
            return 1
        return 0

    print("MVP RELEASE GATE: COMPLETE")
    print("MVP CODE FREEZE REACHED.")
    print("THE NEXT TASK IS CUSTOMER VALIDATION.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
