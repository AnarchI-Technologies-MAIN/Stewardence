"""Offline renderer-only specimen on one retained immutable image; no admission."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from uuid import uuid4

IMAGE = "sha256:afd7c85b5339b47489a927c86dd036f893bc54d2e9c602dffcf1bc3edc292f1a"
ROOT = Path(__file__).resolve().parent.parent


def probe(validate_only=False):
    sys.path.insert(0, "/app/tests")
    from copy import deepcopy
    from uuid import UUID
    from test_review_renderer import review_payload, reseal
    from renderer.schema import validate_report_render_payload
    from renderer.render import render_pdf
    from tests.renderer_qualification_diagnostics import resource_snapshot
    from apps.reviews.exposure import review_record

    directory = Path("/qualification-evidence")
    payload = review_payload()
    seed = payload["review_pack"]["exposure_reviews"][0]["source_record"]
    records = []
    for index in range(100):
        record = deepcopy(seed)
        record["id"] = str(UUID(int=index+1))
        record["display_name"] = f"STABILITY TOOL {index:03d}"
        records.append(record)
    payload["inventory"] = deepcopy(records)
    pack = payload["review_pack"]
    pack["exposure_reviews"] = [
        {"source_record": item, "review": json.loads(json.dumps(review_record(item)))}
        for item in records]
    entry = pack["selected_decisions"][0]
    entry["proposal"]["inventory_item_id"] = records[0]["id"]
    from test_review_renderer import digest
    event = entry["payload"]
    event["card_sha256"] = digest(entry["proposal"])
    event["revision_sha256"] = digest([entry["proposal"]])
    entry["selection"]["card_sha256"] = event["card_sha256"]
    entry["selection"]["revision_sha256"] = event["revision_sha256"]
    event["notes"] = ("STABILITY OWNER NOTE " + "bounded declaration " * 250)[:4096]
    assert len(event["notes"]) == 4096
    event["links"] = []
    for index in range(10):
        prefix = f"https://example.invalid/stability-ref-{index}/"
        event["links"].append(prefix + "x" * (2048-len(prefix)))
    reseal(payload)
    encoded = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    validate_report_render_payload(payload)
    (directory/"synthetic-payload.json").write_bytes(encoded)
    facts = {"image": IMAGE, "specimen": "100 inventory records; one decision; max note/link fields",
             "inventory_count": 100, "decision_count": 1, "notes_chars": 4096,
             "link_count": 10, "link_chars_each": 2048,
             "payload_bytes": len(encoded), "payload_sha256": hashlib.sha256(encoded).hexdigest(),
             "customer_maximum_proven": False, "admitted_or_stored_pack": False,
             "concurrency": 1, "timeout_seconds": 60, "renders": []}
    (directory/"specimen.json").write_text(json.dumps(facts, indent=2))
    if validate_only:
        print(json.dumps(facts), flush=True)
        return

    def zombies():
        result = []
        for path in Path("/proc").iterdir():
            if not path.name.isdecimal():
                continue
            try:
                fields = dict(line.split(":", 1) for line in (path/"status").read_text().splitlines() if ":" in line)
                if fields["Name"].strip().startswith("chrome") and fields["State"].strip().startswith("Z"):
                    result.append(int(path.name))
            except (OSError, KeyError):
                continue
        return result

    facts["before"] = resource_snapshot()
    try:
        with tempfile.TemporaryDirectory(prefix="core-stability-") as output:
            for index in range(20):
                started = time.monotonic()
                pdf = render_pdf(payload, output_directory=Path(output), timeout_seconds=60)
                elapsed = time.monotonic()-started
                text = subprocess.run(["pdftotext", "-", "-"], input=pdf,
                                      check=True, capture_output=True).stdout.decode()
                markers = ["STABILITY TOOL 000", "STABILITY TOOL 099", "STABILITY OWNER NOTE",
                           "stability-ref-0", "stability-ref-9", "Resolution remains unverified"]
                missing = [marker for marker in markers if marker not in text]
                record = {"index": index, "elapsed_seconds": elapsed, "pdf_bytes": len(pdf),
                          "sha256": hashlib.sha256(pdf).hexdigest(), "missing_markers": missing,
                          "zombie_pids": zombies(), "resources": resource_snapshot()}
                facts["renders"].append(record)
                (directory/"stability.json").write_text(json.dumps(facts, indent=2))
                assert elapsed <= 60 and not missing and not record["zombie_pids"], record
                assert record["sha256"] == facts["renders"][0]["sha256"], "Same-input normalized bytes changed"
                if index == 0:
                    (directory/"synthetic-pack.pdf").write_bytes(pdf)
                    (directory/"synthetic-pack.txt").write_text(text)
                print(json.dumps({"render": index, "elapsed_seconds": elapsed,
                                  "pdf_bytes": len(pdf)}), flush=True)
    except BaseException as error:
        facts["failure_type"] = type(error).__name__
        raise
    finally:
        facts["after"] = resource_snapshot()
        (directory/"stability.json").write_text(json.dumps(facts, indent=2))


def main():
    if "--probe" in sys.argv:
        probe("--validate-only" in sys.argv)
        return
    evidence = ROOT/"evidence"/"core-renderer-stability"/datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    evidence.mkdir(parents=True)
    frozen = evidence/Path(__file__).name
    frozen.write_bytes(Path(__file__).read_bytes())
    (evidence/"probe-manifest.json").write_text(json.dumps({"sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
        "image": IMAGE, "source_evidence": "20261004T204824.067533Z", "network": "none",
        "init": True, "memory_bytes": 1073741824, "pids_limit": 512}, indent=2))
    name = "stewardence-render-stability-"+uuid4().hex
    cid = None
    try:
        arguments = ["docker", "create", "--name", name, "--network", "none", "--init",
                     "--memory", "1g", "--pids-limit", "512", "--mount",
                     f"type=bind,source={evidence},target=/qualification-evidence", "--mount",
                     f"type=bind,source={frozen},target=/probe.py,readonly", IMAGE,
                     "/app/.venv/bin/python", "/probe.py", "--probe"]
        if "--validate-only" in sys.argv:
            arguments.append("--validate-only")
        cid = subprocess.run(arguments, check=True, capture_output=True, text=True).stdout.strip()
        inspected = json.loads(subprocess.run(["docker", "inspect", cid], check=True, capture_output=True, text=True).stdout)[0]
        assert inspected["Image"] == IMAGE and inspected["HostConfig"]["Init"] is True
        with (evidence/"container.log").open("w") as log:
            result = subprocess.run(["docker", "start", "-a", cid], stdout=log, stderr=subprocess.STDOUT, timeout=1500)
        (evidence/"result.json").write_text(json.dumps({"exit_code": result.returncode,
            "production_touched": False, "network": "none", "evidence": str(evidence)}, indent=2))
        print(json.dumps({"evidence": str(evidence), "exit_code": result.returncode}), flush=True)
        result.check_returncode()
    finally:
        if cid:
            subprocess.run(["docker", "rm", "-f", cid], check=True, capture_output=True)


if __name__ == "__main__":
    main()
