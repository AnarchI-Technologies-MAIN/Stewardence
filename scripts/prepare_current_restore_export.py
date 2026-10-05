"""Prepare only: no containers, encryption, restore, SSH or provider requests."""

import hashlib
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = Path.home() / ".stewardence-recovery" / "backup.agekey"

STREAM = '''"""Run ONLY inside the held qualification app; stdout is sensitive plaintext."""
import hashlib,json,sys,tarfile
from pathlib import Path
from uuid import UUID
ram=Path(sys.argv[1]).resolve()
assert ram.parent==Path("/dev/shm") and ram.name.startswith("stewardence-restore-export-")
manifest_file=ram/"manifest.json"
raw=manifest_file.read_bytes()
assert hashlib.sha256(raw).hexdigest()==sys.argv[2]
manifest=json.loads(raw)
assert manifest["schema"]=="qualification.local_report_restore_export.v1"
assert len(manifest["objects"])==2
paths=[("manifest.json",manifest_file)]
for obj in manifest["objects"]:
 for field in ("artifact_id","organization_id","report_id","snapshot_id","request_id","pack_id","completion_id"):
  assert str(UUID(obj[field]))==obj[field]
 assert obj["object_key"]=="organizations/"+obj["organization_id"]+"/assessments/"+obj["snapshot_id"]+"/reports/"+obj["report_id"]+".pdf"
 assert obj["ram_store"] in {"other","accounting_bookkeeping"}
 path=(ram/obj["ram_store"]/"private"/obj["object_key"]).resolve()
 assert path.is_relative_to(ram)
 assert path.stat().st_size==obj["size_bytes"] and obj["size_bytes"]<=16*1048576
 assert hashlib.sha256(path.read_bytes()).hexdigest()==obj["sha256"]
 paths.append(("objects/"+obj["artifact_id"]+".pdf",path))
with tarfile.open(fileobj=sys.stdout.buffer,mode="w|") as archive:
 for name,path in paths:
  entry=archive.gettarinfo(str(path),arcname=name)
  entry.uid=entry.gid=0
  entry.uname=entry.gname=""
  entry.mtime=0
  with path.open("rb") as handle:
   archive.addfile(entry,handle)
'''


def main():
    if sys.argv[1:] != ["--prepare-only"]:
        raise SystemExit(
            "Only --prepare-only is admitted; execution needs a separate qualified operator harness"
        )
    if not KEY.is_file() or not shutil.which("age") or not shutil.which("age-keygen"):
        raise SystemExit(
            "Existing approved key or age tools unavailable; no key is created"
        )
    run = (
        ROOT
        / "evidence"
        / "restore-export-preparation"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    )
    run.mkdir(parents=True)
    stream = run / "stream_private_objects.py"
    stream.write_text(STREAM, encoding="utf-8")
    compile(STREAM, str(stream), "exec")
    receipt = {
        "schema": "qualification.local_restore_export_preparation.v1",
        "prepared_only": True,
        "qualified": False,
        "key_path": str(KEY),
        "key_copied": False,
        "ciphertext_custody_distribution": "Ubuntu",
        "ciphertext_custody_directory": "/home/alexg-anarchi/stewardence-backups",
        "streamer_sha256": hashlib.sha256(stream.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "test_sha256": hashlib.sha256(
            (ROOT / "source/tests/test_capture_v4_restore_export.py").read_bytes()
        ).hexdigest(),
        "production_touched": False,
        "docker_executed": False,
    }
    (run / "preparation.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    (run / "NEXT.txt").write_text(
        "Next stage needs a separate operator harness, not manual plaintext exports.\nLaunch isolated --http-renderer qualifier with STEWARDENCE_RESTORE_EXPORT_HOLD=1 forwarded explicitly; test_capture_v4_restore_export.py only.\nWait for public ready receipt. Resolve exact owned app/DB container IDs and labels before reads.\nWhile fixtures are held, pipe DB pg_dump and the RAM-only object tar streamer directly into age encryption using the existing public recipient derived locally from the approved key. Never print/disk-persist plaintext or pass the private key into a container.\nVerify ciphertext hashes/custody, then atomically write the exact release acknowledgement. Preserve failed stages.\nOnly afterward restore both encrypted streams to fresh disposable targets, qualify four-role catalog/RLS/receipt/private-access/corruption invariants, and verify all owned cleanup.\nThis preparation neither performs nor qualifies any of those stages.\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "prepared_directory": str(run),
                "qualified": False,
                "docker_executed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
