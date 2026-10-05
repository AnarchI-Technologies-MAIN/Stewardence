"""Actual-role before/after probe, using immutable images and identical test."""
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from qualification_cleanup import cleanup_targets

ROOT = Path(__file__).resolve().parents[1]
IMAGES = [
    ('before', 'sha256:70fbdfa6d7a8eb1981f2181216900d95ecfbafe8b94d343ee5d9db74b98c2874'),
    ('after', sys.argv[1]),
]
TEST = 'tests/test_review_pack_lifecycle.py::test_head_lock_wait_cannot_reuse_pre_expiry_lease'


def docker(*args, **kwargs):
    return subprocess.run(['docker',*args], check=True, **kwargs)


def main():
    assert len(sys.argv)==2 and sys.argv[1].startswith('sha256:') and len(sys.argv[1])==71
    directory = ROOT/'evidence'/'review-head-wait-counterexample'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    directory.mkdir(parents=True)
    frozen = directory/'test_review_pack_lifecycle.py'
    frozen.write_bytes((ROOT/'source/tests/test_review_pack_lifecycle.py').read_bytes())
    harness = directory/'qualify_review_head_wait_counterexample.py'
    harness.write_bytes(Path(__file__).read_bytes())
    (directory/'source-manifest.json').write_text(json.dumps({
        path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in (frozen,harness)},indent=2))
    records = []
    for version, image in IMAGES:
        owner = uuid.uuid4().hex
        name = 'stewardence-review-head-wait-'+owner
        destination = directory/version
        destination.mkdir()
        network_created = False
        try:
            docker('network','create','--internal','--label','stewardence.qualification-run='+owner,name,capture_output=True)
            network_created = True
            docker('run','-d','--name',name+'-db','--network',name,'--network-alias','qualification-db',
                '--memory','512m','--pids-limit','128','--tmpfs','/var/lib/postgresql:rw,size=512m',
                '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=qualification','postgres:18.6',capture_output=True)
            for _ in range(60):
                ready = subprocess.run(['docker','exec',name+'-db','pg_isready','-h','127.0.0.1','-U','postgres','-d','qualification'],capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('Isolated database readiness failed')
            with (destination/'qualification.log').open('w') as log:
                result = subprocess.run(['docker','run','--name',name+'-app','--init','--network',name,
                    '--memory','1g','--pids-limit','512',
                    '--mount',f'type=bind,source={destination},target=/qualification-evidence',
                    '--mount',f'type=bind,source={frozen},target=/app/tests/test_review_pack_lifecycle.py,readonly',
                    '-e','DATABASE_ADMIN_URL=postgresql://postgres@qualification-db:5432/qualification',
                    '-e','DJANGO_SETTINGS_MODULE=agentledger.settings.development',image,
                    '/app/.venv/bin/python','scripts/verify_rls.py',TEST,'-q','-p','no:cacheprovider',
                    '--junitxml=/qualification-evidence/test-results.xml'],stdout=log,stderr=subprocess.STDOUT,timeout=180)
            cases = list(ET.parse(destination/'test-results.xml').getroot().iter('testcase'))
            assert len(cases)==1 and cases[0].get('name')=='test_head_lock_wait_cannot_reuse_pre_expiry_lease'
            failure = cases[0].find('failure')
            if version == 'before':
                assert result.returncode != 0 and failure is not None
                assert "['admitted']" in (failure.text or '') and "['denied']" in (failure.text or '')
            if version == 'after':
                assert result.returncode == 0 and failure is None and cases[0].find('error') is None
            records.append({'version':version,'image':image,'exit_code':result.returncode,
                'test_cases':1,'failed':int(failure is not None),'production_touched':False})
        finally:
            cleanup = cleanup_targets(docker,[name+'-app',name+'-db'],
                                      network=name if network_created else None,network_owner=owner)
            (destination/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
            assert cleanup['cleanup_passed']
    (directory/'comparison.json').write_text(json.dumps(records,indent=2))
    print(json.dumps({'evidence_directory':str(directory),'comparison':records}))


if __name__ == '__main__':
    main()
