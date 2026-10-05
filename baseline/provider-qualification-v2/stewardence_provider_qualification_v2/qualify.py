"""Qualify candidate in isolated containers; never mounts production data/config."""
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAME = 'stewardence-provider-check-' + uuid.uuid4().hex[:10]
DOCKER = ['docker'] if os.geteuid() == 0 else ['sudo', '-n', 'docker']


def command(*args, **kwargs):
    return subprocess.run(DOCKER + list(args), check=True, **kwargs)


def main():
    os.umask(0o077)
    created_network = False
    created_database = False
    built = False
    try:
        manifest = json.loads((ROOT / 'manifest.json').read_text())
        for relative, expected in manifest['source_sha256'].items():
            path = (ROOT / 'source' / relative).resolve()
            if not path.is_relative_to((ROOT / 'source').resolve()):
                raise RuntimeError('Unsafe source manifest')
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError('Candidate source hash mismatch')
        print('CANDIDATE_INTEGRITY=PASS', flush=True)
        with (ROOT / 'build.log').open('w') as log:
            command('build', '-t', NAME, '-f', str(ROOT / 'Dockerfile.check'),
                    str(ROOT), stdout=log, stderr=subprocess.STDOUT)
        built = True
        command('network', 'create', '--internal', NAME, stdout=subprocess.DEVNULL)
        created_network = True
        command('run', '-d', '--name', NAME + '-db', '--network', NAME,
                '--network-alias', 'qualification-db', '--memory', '256m',
                '--pids-limit', '128', '--tmpfs', '/var/lib/postgresql:rw,size=384m',
                '-e', 'POSTGRES_HOST_AUTH_METHOD=trust',
                '-e', 'POSTGRES_DB=qualification', 'postgres:18.6',
                stdout=subprocess.DEVNULL)
        created_database = True
        for _attempt in range(60):
            ready = subprocess.run(DOCKER + ['exec', NAME + '-db', 'pg_isready',
                '-U', 'postgres', '-d', 'qualification'], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Qualification database did not become ready')
        tests = sorted('tests/' + p.name for pattern in ('test_provider*.py', 'test_quickbooks*.py', 'test_billing*.py')
                       for p in (ROOT / 'source/tests').glob(pattern))
        tests += ['tests/test_integrations_analysis.py', 'tests/test_automation_pricing.py',
                  'tests/test_tenancy_context.py']
        with (ROOT / 'qualification.log').open('w') as log:
            result = subprocess.run(DOCKER + [
                'run', '--rm', '--network', NAME, '--memory', '512m',
                '--pids-limit', '256', '-e',
                'DATABASE_ADMIN_URL=postgresql://postgres@qualification-db:5432/qualification',
                '-e', 'DJANGO_SETTINGS_MODULE=agentledger.settings.development',
                NAME, '/app/.venv/bin/python', 'scripts/verify_rls.py',
                *tests, '-q', '-p', 'no:cacheprovider'], stdout=log, stderr=subprocess.STDOUT)
        print('\n'.join((ROOT / 'qualification.log').read_text().splitlines()[-110:]))
        print('PROVIDER_CONNECTION_QUALIFICATION=' + ('PASS' if result.returncode == 0 else 'FAIL'))
        print('LIVE_PROVIDER_AUTHENTICATION=NOT_TESTED')
        print('PROVIDER_CREDENTIALS=NOT_MOUNTED')
        print('RUNNING_APPLICATION=UNCHANGED')
        print('WORKER=UNCHANGED_NOT_STARTED')
        print('PRODUCTION_DATABASE=UNTOUCHED')
        print('AUTOMATION_PURCHASES=UNCHANGED_DISABLED')
        return result.returncode
    except (subprocess.CalledProcessError, RuntimeError, OSError, ValueError) as error:
        print(type(error).__name__ + ': qualification could not finish')
        if (ROOT / 'build.log').exists():
            print('\n'.join((ROOT / 'build.log').read_text().splitlines()[-40:]))
        print('PROVIDER_CONNECTION_QUALIFICATION=FAIL')
        return 1
    finally:
        if created_database:
            subprocess.run(DOCKER + ['rm', '-f', NAME + '-db'], capture_output=True)
        if created_network:
            subprocess.run(DOCKER + ['network', 'rm', NAME], capture_output=True)
        if built:
            subprocess.run(DOCKER + ['image', 'rm', NAME], capture_output=True)


if __name__ == '__main__':
    sys.exit(main())
