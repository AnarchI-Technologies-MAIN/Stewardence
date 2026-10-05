from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from .contract import COLLECTOR_VERSION, DETECTOR_ID, digest, validate_bundle
from .windows import installed_programs


def main():
    parser = argparse.ArgumentParser(description="Stewardence one-shot Collector")
    parser.add_argument(
        "--device-id",
        required=True,
        type=UUID,
        help="Stable pseudonymous device UUID from your profile",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New JSON bundle path; existing files are never overwritten",
    )
    args = parser.parse_args()
    observed_at = datetime.now(UTC).isoformat()
    records, coverage = installed_programs(observed_at)
    bundle = {
        "schema_version": 1,
        "collector_version": COLLECTOR_VERSION,
        "device_id": str(args.device_id),
        "observed_at": observed_at,
        "coverage": {DETECTOR_ID: coverage},
        "evidence": records,
    }
    bundle["scan_id"] = digest(bundle)
    raw = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    validate_bundle(raw)
    with args.output.open("xb") as handle:
        handle.write(raw)
    print(
        f"Collected {len(records)} installed-program observations; coverage={coverage}."
    )
    print("Review the bundle, then upload it in your Stewardence workspace.")


if __name__ == "__main__":
    main()
