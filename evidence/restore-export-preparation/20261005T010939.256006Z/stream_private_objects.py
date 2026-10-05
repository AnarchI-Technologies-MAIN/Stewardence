"""Run ONLY inside the held qualification app; stdout is sensitive plaintext."""
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
