"""Create a review-only source package. Does not deploy, migrate, commit or push."""
import difflib
import hashlib
import io
import json
import tarfile
from datetime import datetime, UTC
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = json.loads((ROOT/'baseline/baseline-manifest.json').read_text())
    source = ROOT/'source'
    files = {}
    for path in sorted(source.rglob('*')):
        if not path.is_file():
            continue
        name = path.relative_to(source).as_posix()
        if any(part in {'.git', '.venv', '__pycache__', '.pytest_cache'} for part in path.parts):
            continue
        if '.env' in path.name or path.suffix.lower() in {'.key', '.p12', '.pfx', '.dump', '.age'}:
            continue
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    changes = []
    diff = []
    for name in sorted(set(files) | set(baseline['files'])):
        old_hash = baseline['files'].get(name)
        new_hash = files.get(name)
        if old_hash == new_hash:
            continue
        changes.append({'path':name, 'baseline_sha256':old_hash, 'candidate_sha256':new_hash})
        old = ROOT/'baseline/source'/name
        new = source/name
        try:
            before = old.read_text(encoding='utf-8').splitlines(True) if old.exists() else []
            after = new.read_text(encoding='utf-8').splitlines(True) if new.exists() else []
        except UnicodeDecodeError:
            continue
        diff.extend(difflib.unified_diff(before,after,fromfile='baseline/'+name,tofile='candidate/'+name))
    folder = ROOT/'releases'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    folder.mkdir(parents=True)
    with tarfile.open(folder/'candidate-source.tar.gz','w:gz') as archive:
        for name in files:
            archive.add(source/name,arcname=name,recursive=False)
    summary = {'created_at':datetime.now(UTC).isoformat(), 'base_git_revision':baseline['head'],
               'baseline_archive_sha256':baseline['archive_sha256'],
               'candidate_archive_sha256':hashlib.sha256((folder/'candidate-source.tar.gz').read_bytes()).hexdigest(),
               'production_release_approved':False, 'production_ready':False,
               'source_files':files,'changes':changes,
               'open_gates_document':str(ROOT/'docs/release-gates.md')}
    (folder/'manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (folder/'changes.diff').write_text(''.join(diff),encoding='utf-8')
    print(json.dumps({'review_package':str(folder),'changed_or_added_files':len(changes),
                      'production_ready':False}))


if __name__ == '__main__':
    main()
