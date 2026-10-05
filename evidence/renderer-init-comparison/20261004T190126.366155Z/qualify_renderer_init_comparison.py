"""Own isolated renderer containers only; immutable image and synthetic data."""
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:6999e54b4cb3df3db88893d79d2274b885f046e90b7c988333448217e229c772'


def main():
    evidence = ROOT/'evidence'/'renderer-init-comparison'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    evidence.mkdir(parents=True)
    frozen_probe = evidence/'probe_renderer_reaping.py'
    frozen_probe.write_bytes((ROOT/'source/scripts/probe_renderer_reaping.py').read_bytes())
    frozen_harness = evidence/'qualify_renderer_init_comparison.py'
    frozen_harness.write_bytes(Path(__file__).read_bytes())
    (evidence/'source-manifest.json').write_text(json.dumps({
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (frozen_probe, frozen_harness)}, indent=2))
    records = []
    for enabled in (False, True):
        name = 'stewardence-render-init-'+uuid.uuid4().hex
        directory = evidence/('with-init' if enabled else 'without-init')
        directory.mkdir()
        cid = None
        try:
            args = ['docker', 'create', '--name', name, '--network', 'none',
                    '--memory', '1g', '--pids-limit', '512',
                    '--mount', f'type=bind,source={directory},target=/qualification-evidence',
                    '--mount', f'type=bind,source={frozen_probe},target=/probe.py,readonly']
            if enabled:
                args.append('--init')
            created = subprocess.run(args+[IMAGE, '/app/.venv/bin/python', '/probe.py'], check=True, capture_output=True, text=True)
            cid = created.stdout.strip()
            inspected = json.loads(subprocess.run(['docker','inspect',cid], check=True, capture_output=True, text=True).stdout)[0]
            assert inspected['Image'] == IMAGE
            assert bool(inspected['HostConfig'].get('Init', False)) == enabled
            with (directory/'container.log').open('w') as log:
                subprocess.run(['docker','start','-a',cid], check=True, stdout=log, stderr=subprocess.STDOUT, timeout=300)
            finished = json.loads(subprocess.run(['docker','inspect',cid], check=True, capture_output=True, text=True).stdout)[0]
            assert finished['State']['ExitCode'] == 0
            probe = json.loads((directory/'reaping.json').read_text())
            zombies = [p for p in probe['after']['processes'] if p['Name'].startswith('chrome') and p['State'].startswith('Z')]
            records.append({'init': enabled, 'image': IMAGE, 'zombie_count_after': len(zombies),
                            'render_count': len(probe['renders']), 'container_exit_code': 0})
        finally:
            if cid is not None:
                subprocess.run(['docker','rm','-f',cid], check=True, capture_output=True)
                absent = subprocess.run(['docker','inspect',cid], capture_output=True)
                assert absent.returncode != 0
    assert records[0]['zombie_count_after'] > 0
    assert records[1]['zombie_count_after'] == 0
    (evidence/'comparison.json').write_text(json.dumps(records, indent=2))
    print(json.dumps({'evidence_directory': str(evidence), 'comparison': records,
                     'production_touched': False}))


if __name__ == '__main__':
    main()
