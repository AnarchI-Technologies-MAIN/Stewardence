"""Read-only comparison of captured paths against the running web container."""
import hashlib
import json
import shlex
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path

from preserve_source import SSH

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = json.loads((ROOT/'baseline/baseline-manifest.json').read_text())
    names = list(baseline['files'])
    container = 'stewardence-web'
    filename = 'runtime-source-comparison.json'
    if sys.argv[1:] == ['renderer']:
        container = 'stewardence-renderer'
        filename = 'runtime-renderer-comparison.json'
        names = [name for name in names if name.startswith('renderer/') or name == 'static/brand/stewardence-helix-orbit-light.png']
    elif sys.argv[1:]:
        raise SystemExit('Supported target: renderer or no argument for web')
    program = "import json,hashlib,pathlib; names=" + repr(names) + "; root=pathlib.Path('/app'); print(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() if (root/n).is_file() else None for n in names}))"
    command = 'sudo -n docker exec '+container+' /app/.venv/bin/python -c ' + shlex.quote(program)
    hashes = json.loads(subprocess.check_output(SSH+[command],text=True))
    result = {'verified_at':datetime.now(UTC).isoformat(), 'scope':'captured source paths only; excludes secrets, image dependencies and generated assets',
              'matched':[], 'different':[], 'absent_from_image':[]}
    for name in names:
        expected = baseline['files'][name]
        if hashes[name] is None:
            result['absent_from_image'].append(name)
        elif hashes[name] != expected:
            result['different'].append({'path':name,'captured_sha256':expected,'runtime_sha256':hashes[name]})
        else:
            result['matched'].append(name)
    result['container'] = container
    (ROOT/'evidence'/filename).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({key:len(result[key]) for key in ('matched','different','absent_from_image')}))


if __name__ == '__main__':
    main()
