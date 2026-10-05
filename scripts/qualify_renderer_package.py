"""Credential-free, immutable-image renderer qualification with fresh outputs."""
import hashlib
import json
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:d4c73ead4d1c6bf16c77089a6837e039a0ab84c4a9a48d8b4f60852809e57a27'
PAYLOAD = ROOT/'evidence/20261003T224123.550152Z/synthetic-render-payload.json'


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True)


def main():
    run = ROOT/'evidence/renderer-package'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    run.mkdir(parents=True)
    shutil.copyfile(PAYLOAD, run/'synthetic-render-payload.json')
    shutil.copyfile(ROOT/'scripts/renderer_package_probe.py', run/'probe.py')
    name = 'stewardence-renderer-qualification-'+uuid.uuid4().hex
    result = None
    try:
        docker('create', '--name', name, '--network', 'none', '--read-only',
               '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
               '--memory', '512m', '--pids-limit', '256',
               '--tmpfs', '/tmp:rw,size=128m',
               '--tmpfs', '/work/output:rw,size=32m,mode=0700,uid=10001,gid=10001',
               '--mount', 'type=bind,source='+str(run)+',target=/qa',
               '--mount', 'type=bind,source='+str(run/'probe.py')+',target=/probe.py,readonly',
               IMAGE, '/app/.venv/bin/python', '/probe.py')
        state = json.loads(docker('inspect', name).stdout)[0]
        host = state['HostConfig']
        if (state['Image'] != IMAGE or state['Config']['User'] != '10001:10001'
                or host['NetworkMode'] != 'none' or not host['ReadonlyRootfs']
                or host['CapDrop'] != ['ALL'] or 'no-new-privileges' not in host['SecurityOpt']
                or host['Memory'] != 512*1024*1024 or host['PidsLimit'] != 256
                or host['Tmpfs'].get('/tmp') != 'rw,size=128m'
                or host['Tmpfs'].get('/work/output') != 'rw,size=32m,mode=0700,uid=10001,gid=10001'):
            raise RuntimeError('Renderer launch constraints differ from qualification')
        execution = subprocess.run(['docker','start','-a',name],capture_output=True,text=True)
        (run/'renderer.log').write_text(execution.stdout+execution.stderr, encoding='utf-8')
        status = json.loads(docker('inspect', name).stdout)[0]['State']
        if status['ExitCode'] != 0 or status['OOMKilled']:
            raise RuntimeError('Renderer probe did not exit successfully')
        result = json.loads((run/'renderer-package-summary.json').read_bytes())
        for file, field in [('packaged-renderer.pdf', 'pdf_sha256'),
                            ('synthetic-render-payload.json', 'input_sha256'), ('probe.py', 'probe_sha256')]:
            if hashlib.sha256((run/file).read_bytes()).hexdigest() != result[field]:
                raise RuntimeError('Renderer qualification output binding mismatch')
        result.update({'renderer_image_id': IMAGE, 'container_exit_code': status['ExitCode'],
                       'runtime_constraints': {key:host[key] for key in
                           ['NetworkMode','ReadonlyRootfs','CapDrop','SecurityOpt','Memory','PidsLimit','Tmpfs']},
                       'fresh_output_directory':str(run), 'verified_at':datetime.now(UTC).isoformat()})
    finally:
        removal = subprocess.run(['docker','rm','-f',name], capture_output=True, text=True)
        remaining = docker('ps','-aq','--filter','name=^'+name+'$').stdout.strip()
        if remaining:
            raise RuntimeError('Renderer qualification container cleanup incomplete')
    if result is not None:
        result['cleanup_verified'] = True
        (run/'launch-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))


if __name__ == '__main__':
    main()
