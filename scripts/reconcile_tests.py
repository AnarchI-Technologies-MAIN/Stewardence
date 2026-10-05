"""Add missing qualification tests; never replace current deployed-source files."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]

def main():
    bundle = ROOT/'baseline/provider-qualification-v2/stewardence_provider_qualification_v2/source'
    source = ROOT/'source'
    report = {'added_tests':[], 'bundle_differences':[]}
    for old in sorted(bundle.rglob('*')):
        if not old.is_file():
            continue
        rel = old.relative_to(bundle)
        current = source/rel
        if not current.exists():
            if rel.parts[0] == 'tests':
                current.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(old,current)
                report['added_tests'].append(str(rel))
            continue
        if old.read_bytes() != current.read_bytes():
            report['bundle_differences'].append({'path':str(rel),
                'bundle_sha256':hashlib.sha256(old.read_bytes()).hexdigest(),
                'deployed_sha256':hashlib.sha256(current.read_bytes()).hexdigest()})
    (ROOT/'docs/test-reconciliation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
