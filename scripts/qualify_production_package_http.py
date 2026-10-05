"""Local deployable-package HTTP proof; never contacts production or providers."""
import hashlib
import json
import subprocess
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from package_qualification_contract import selected, verify_source, verify_fixture, verify_runtime

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'sha256:4efeada9517347fe7424a6754a01d531b0f9a0b98f0abd4c452b6fc9ad45649f'
QUALIFICATION = ROOT/'evidence/20261004T011026.080005Z'


def docker(*args):
    return subprocess.run(['docker',*args],capture_output=True,text=True,check=True)


def main():
    preview = json.loads((ROOT/'evidence/visual-preview.json').read_bytes())
    if preview['name'] != 'stewardence-visualqa-7e62efb888':
        raise RuntimeError('Expected synthetic database fixture changed')
    full_result = json.loads((QUALIFICATION/'qualification-summary.json').read_bytes())
    if full_result['exit_code'] != 0 or full_result['test_arguments'] != ['tests']:
        raise RuntimeError('Pinned complete source qualification is not passing')
    manifest_bytes = (QUALIFICATION/'source-manifest.json').read_bytes()
    source_manifest = json.loads(manifest_bytes)
    source_count = verify_source(ROOT/'source', source_manifest)
    network = json.loads(docker('network','inspect',preview['network']).stdout)[0]
    database = json.loads(docker('inspect',preview['database']).stdout)[0]
    network_id, database_id = verify_fixture(preview, network, database)
    name = 'stewardence-package-http-'+uuid.uuid4().hex
    output = ROOT/'evidence/production-package-http'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    output.mkdir(parents=True)
    shutil.copyfile(ROOT/'scripts/production_package_http_probe.py', output/'http-probe.py')
    expected_image = {key.replace('\\', '/'): digest for key, digest in source_manifest.items()
                      if selected(key) and key != 'Dockerfile'
                      and '__pycache__' not in key and not key.endswith('.pyc')}
    (output/'expected-source.json').write_text(json.dumps(expected_image, sort_keys=True))
    result = None
    container_id = None
    configuration = {
        'DJANGO_SETTINGS_MODULE':'agentledger.settings.production',
        'DJANGO_SECRET_KEY':'qualification-only-no-production-authority-secret-20261003-aB7k9',
        'DATABASE_URL':'postgresql://agentledger_app@qualification-db:5432/qualification',
        'ALLOWED_HOSTS':'localhost','CSRF_TRUSTED_ORIGINS':'https://localhost',
        'REPORTS_BUCKET_NAME':'qualification-only','REPORTS_BUCKET_ENDPOINT':'https://127.0.0.1',
        'REPORTS_BUCKET_ACCESS_KEY_ID':'qualification-only',
        'REPORTS_BUCKET_SECRET_ACCESS_KEY':'qualification-only',
        'REPORT_RENDERER_URL':'http://127.0.0.1:8080','STEWARDENCE_ISOLATED_QA':'1',
        'AUTOMATION_ENABLED':'0','CORE_WORKFLOWS_ENABLED':'0','FOUNDER_OFFER_ENABLED':'0',
    }
    try:
        args = ['create','--name',name,'--network',network_id,'--read-only',
                '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m',
                '--pids-limit','128','--tmpfs','/tmp:rw,size=32m',
                '--mount','type=bind,source='+str(output/'http-probe.py')+',target=/probe.py,readonly',
                '--mount','type=bind,source='+str(output/'expected-source.json')+',target=/expected-source.json,readonly']
        for key,value in configuration.items():
            args.extend(['-e',key+'='+value])
        container_id = docker(*args, IMAGE).stdout.strip()
        runtime = json.loads(docker('inspect',container_id).stdout)[0]
        if runtime['Id'] != container_id:
            raise RuntimeError('Created HTTP container identity changed')
        verify_runtime(runtime, IMAGE, network_id, network_name=preview['network'])
        fresh_network = json.loads(docker('network','inspect',network_id).stdout)[0]
        fresh_database = json.loads(docker('inspect',database_id).stdout)[0]
        if verify_fixture(preview, fresh_network, fresh_database) != (network_id, database_id):
            raise RuntimeError('Synthetic fixture changed before start')
        docker('start',container_id)
        connected_runtime = json.loads(docker('inspect',container_id).stdout)[0]
        verify_runtime(connected_runtime, IMAGE, network_id,
                       network_name=preview['network'], started=True)
        execution = docker('exec',container_id,'/app/.venv/bin/python','/probe.py')
        result = json.loads(execution.stdout)
        if (result.get('qualification_passed') is not True
                or result.get('provider_requests') is not False
                or result.get('production_touched') is not False):
            raise RuntimeError('HTTP child did not produce a passing isolated receipt')
        result.update({'application_image_id':runtime['Image'],'full_tested_source_image_id':full_result['image_id'],
                       'source_manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),
                       'http_probe_sha256':hashlib.sha256((output/'http-probe.py').read_bytes()).hexdigest(),
                       'synthetic_database_id':database_id,'synthetic_network_id':network_id,
                       'source_files_matched':source_count,'runtime_read_only':runtime['HostConfig']['ReadonlyRootfs'],
                       'runtime_no_public_ports':not bool(runtime['HostConfig']['PortBindings']),
                       'verified_at':datetime.now(UTC).isoformat()})
        (output/'gunicorn.log').write_text(docker('logs',container_id).stdout,encoding='utf-8')
    finally:
        if container_id:
            subprocess.run(['docker','rm','-f',container_id],capture_output=True)
        if docker('ps','-aq','--filter','name=^'+name+'$').stdout.strip():
            raise RuntimeError('Packaged HTTP qualification cleanup incomplete')
    result['cleanup_verified'] = True
    (output/'qualification-summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
