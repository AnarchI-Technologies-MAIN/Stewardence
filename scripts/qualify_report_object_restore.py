"""Read existing private reports, age-encrypt, restore from WSL to isolated tmpfs.

Never writes production DB/bucket, prints credentials/content/tenant identifiers,
or creates a plaintext dump/PDF on the host. Uses the prior encrypted DB snapshot
to require an exact artifact-metadata match before fetching any object.
"""
import base64
import hashlib
import json
import re
import shlex
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from preserve_source import SSH

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / 'evidence/restore/20261003T190142.291805Z/restore-summary.json'
MAX_OBJECT = 16 * 1048576
MAX_TOTAL = 128 * 1048576
SQL = """SELECT coalesce(json_agg(row_to_json(t) ORDER BY t.id),'[]'::json)
FROM (SELECT a.id,a.organization_id,a.report_id,a.assessment_snapshot_id,a.object_key,
a.sha256,a.size_bytes,a.content_type,
(r.organization_id=a.organization_id AND r.assessment_snapshot_id=a.assessment_snapshot_id
AND s.organization_id=a.organization_id) AS bindings_valid
FROM report_artifacts a LEFT JOIN reports r ON r.id=a.report_id
LEFT JOIN assessment_snapshots s ON s.id=a.assessment_snapshot_id ORDER BY a.id LIMIT 101) t;"""


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def pipeline(source, sink, *, timeout=90):
    """Bounded pipeline completion; suppress sensitive upstream diagnostics."""
    try:
        sink.communicate(timeout=timeout)
        source.communicate(timeout=30)
        if sink.returncode or source.returncode:
            raise RuntimeError('Private qualification pipeline failed; diagnostics suppressed')
    finally:
        for process in [sink, source]:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


def remote(command):
    return subprocess.check_output(SSH + [command], timeout=40)


def wsl_path(path):
    return subprocess.check_output(['wsl', '-d', 'Ubuntu', '--exec', 'wslpath', '-u', str(path)],
                                   timeout=15, text=True).strip()


def main():
    previous = json.loads(BACKUP.read_bytes())
    key = Path(previous['private_key_file'])
    if not previous['restore_passed'] or not key.is_file():
        raise RuntimeError('Prior qualified encrypted backup/key unavailable')
    recipient = subprocess.check_output(['age-keygen', '-y', str(key)], text=True).strip()
    if not recipient.startswith('age1'):
        raise RuntimeError('Backup recipient invalid')
    run = ROOT / 'evidence/report-object-restore' / datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    run.mkdir(parents=True)
    name = 'stewardence-object-restore-' + uuid.uuid4().hex[:10]
    targets = [name]
    summary = None
    postgres_image = docker('image', 'inspect', '--format', '{{.Id}}', 'postgres:18.6', capture_output=True, text=True).stdout.strip()
    image = json.loads((ROOT / 'evidence/20261003T205521.426662Z/qualification-summary.json').read_bytes())['image_id']
    actual_verifier = docker('image', 'inspect', '--format', '{{.Id}}', image, capture_output=True, text=True).stdout.strip()
    if image != actual_verifier or not postgres_image.startswith('sha256:'):
        raise RuntimeError('Immutable restore image identity invalid')
    try:
        docker('run', '-d', '--name', name, '--network', 'none', '--memory', '512m',
               '--pids-limit', '128', '--tmpfs', '/var/lib/postgresql:rw,size=512m',
               '-e', 'POSTGRES_HOST_AUTH_METHOD=trust', '-e', 'POSTGRES_DB=restored',
               postgres_image, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(60):
            # The initialization-only server accepts Unix sockets before its
            # restart. TCP readiness distinguishes the final stable server.
            result = subprocess.run(['docker', 'exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', '-d', 'restored'], capture_output=True)
            if result.returncode == 0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Isolated restore target did not become ready')
        docker('exec', name, 'psql', '-U', 'postgres', '-d', 'restored', '-v', 'ON_ERROR_STOP=1', '-c',
               'CREATE ROLE agentledger_owner; CREATE ROLE agentledger_app; CREATE ROLE agentledger_worker;', capture_output=True)
        cipher = subprocess.Popen(['wsl', '-d', 'Ubuntu', '--exec', 'python3', '-c',
            'import hashlib,pathlib,sys; p=pathlib.Path(sys.argv[1]); d=p.open("rb").read(200*1024*1024+1); assert len(d)<=200*1024*1024; assert hashlib.sha256(d).hexdigest()==sys.argv[2]; sys.stdout.buffer.write(d)',
            previous['wsl_ciphertext_custody']['encrypted_path'], previous['backup_sha256']], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        decrypt = subprocess.Popen(['age', '-d', '-i', str(key)], stdin=cipher.stdout,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        cipher.stdout.close()
        cipher.stdout = None
        restore = subprocess.Popen(['docker', 'exec', '-i', name, 'pg_restore', '-U', 'postgres', '-d', 'restored', '--exit-on-error'],
                                   stdin=decrypt.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        decrypt.stdout.close()
        decrypt.stdout = None
        try:
            pipeline(decrypt, restore, timeout=120)
            cipher.communicate(timeout=30)
            if cipher.returncode:
                raise RuntimeError('WSL backup read failed')
        finally:
            if cipher.poll() is None:
                cipher.kill()
                cipher.wait(timeout=10)
        archived = json.loads(docker('exec', name, 'psql', '-U', 'postgres', '-d', 'restored', '-Atqc', SQL,
                                    capture_output=True).stdout)
        if not 0 < len(archived) <= 100:
            raise RuntimeError('Report snapshot count outside qualification bounds')
        live = json.loads(remote('sudo -n docker exec -u postgres stewardence-db psql -d stewardence_restore -Atqc ' + shlex.quote(SQL)))
        if archived != live:
            raise RuntimeError('Live artifact metadata differs from encrypted DB snapshot; recapture required')
        total = 0
        for artifact in archived:
            for field in ['id', 'organization_id', 'report_id', 'assessment_snapshot_id']:
                uuid.UUID(artifact[field])
            expected_key = ('organizations/' + artifact['organization_id'] + '/assessments/' +
                            artifact['assessment_snapshot_id'] + '/reports/' + artifact['report_id'] + '.pdf')
            if artifact['object_key'] != expected_key or artifact['bindings_valid'] is not True:
                raise RuntimeError('Restored artifact ownership/report/snapshot binding invalid')
            if artifact['content_type'] != 'application/pdf' or not re.fullmatch('[0-9a-f]{64}', artifact['sha256']):
                raise RuntimeError('Restored artifact media/hash invalid')
            if type(artifact['size_bytes']) is not int or not 0 < artifact['size_bytes'] <= MAX_OBJECT:
                raise RuntimeError('Artifact outside qualification size bound')
            total += artifact['size_bytes']
        if total > MAX_TOTAL:
            raise RuntimeError('Report snapshot exceeds total restore bound')

        # The private manifest contains tenant/object bindings; only ciphertext is
        # stored outside the isolated database. Public summary contains counts only.
        manifest = json.dumps(archived, sort_keys=True, separators=(',', ':')).encode()
        subprocess.run(['age', '-r', recipient, '-o', str(run / 'manifest.json.age')],
                       input=manifest, check=True, capture_output=True)
        getter = r'''
import base64,hashlib,json,sys
import django
django.setup()
from django.conf import settings
import boto3
from botocore.config import Config
a=json.loads(base64.b64decode(sys.argv[1]))
c=boto3.client('s3',endpoint_url=settings.REPORTS_BUCKET_ENDPOINT,region_name=settings.REPORTS_BUCKET_REGION,
 aws_access_key_id=settings.REPORTS_BUCKET_ACCESS_KEY_ID,aws_secret_access_key=settings.REPORTS_BUCKET_SECRET_ACCESS_KEY,
 config=Config(connect_timeout=10,read_timeout=30,retries={'max_attempts':1},s3={'addressing_style':settings.REPORTS_BUCKET_URL_STYLE}))
r=c.get_object(Bucket=settings.REPORTS_BUCKET_NAME,Key=a['object_key'])
body=r['Body']
try:
 if r.get('ContentLength') != a['size_bytes']: raise RuntimeError('Source size mismatch')
 data=body.read(16*1048576+1)
 if len(data)!=a['size_bytes'] or not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest()!=a['sha256']:
  raise RuntimeError('Source artifact integrity mismatch')
 sys.stdout.buffer.write(data)
finally: body.close()
'''
        object_files = []
        for index, artifact in enumerate(archived):
            output = run / (str(index) + '.pdf.age')
            argument = base64.b64encode(json.dumps(artifact).encode()).decode()
            command = 'sudo -n docker exec stewardence-web /app/.venv/bin/python -c ' + shlex.quote(getter) + ' ' + shlex.quote(argument)
            source = subprocess.Popen(SSH + [command], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            encrypt = subprocess.Popen(['age', '-r', recipient, '-o', str(output)], stdin=source.stdout,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            source.stdout.close()
            source.stdout = None
            pipeline(source, encrypt)
            object_files.append(output)

        custody = r'''
import hashlib,json,os,pathlib,sys,tempfile
source=pathlib.Path(sys.argv[1]); name=sys.argv[2]
if pathlib.Path(name).name!=name: raise SystemExit('Invalid custody identity')
root=pathlib.Path.home()/'stewardence-backups'/'report-objects'/name
root.mkdir(parents=True,mode=0o700,exist_ok=False)
os.chmod(root.parent,0o700); os.chmod(root,0o700)
result=[]
for p in sorted(source.glob('*.age')):
 data=p.open('rb').read(17*1048576+1)
 if len(data)>17*1048576 or not data.startswith(b'age-encryption.org/v1'): raise SystemExit('Invalid cipher')
 fd,tmp=tempfile.mkstemp(prefix='.encrypted-',dir=root)
 try:
  with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
  os.link(tmp,root/p.name)
 finally: pathlib.Path(tmp).unlink(missing_ok=True)
 result.append({'file':p.name,'sha256':hashlib.sha256(data).hexdigest()})
print(json.dumps({'directory':str(root),'files':result,'key_copied':False}))
'''
        copied = json.loads(subprocess.check_output(['wsl', '-d', 'Ubuntu', '--exec', 'python3', '-c', custody,
                                                     wsl_path(run), run.name], timeout=30))
        if len(copied['files']) != len(archived) + 1:
            raise RuntimeError('WSL custody inventory mismatch')
        for item in copied['files']:
            if hashlib.sha256((run / item['file']).read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('WSL ciphertext identity mismatch')
        manifest_reader = subprocess.Popen(['wsl', '-d', 'Ubuntu', '--exec', 'python3', '-c',
            'import pathlib,sys; d=pathlib.Path(sys.argv[1]).open("rb").read(1048576+1); assert len(d)<=1048576; sys.stdout.buffer.write(d)',
            copied['directory'] + '/manifest.json.age'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        manifest_decrypt = subprocess.Popen(['age', '-d', '-i', str(key)], stdin=manifest_reader.stdout,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        manifest_reader.stdout.close(); manifest_reader.stdout = None
        try:
            recovered_manifest, _ = manifest_decrypt.communicate(timeout=30)
            manifest_reader.communicate(timeout=15)
            if manifest_decrypt.returncode or manifest_reader.returncode or len(recovered_manifest)>1048576:
                raise RuntimeError('Encrypted object manifest restore failed')
            if json.loads(recovered_manifest) != archived:
                raise RuntimeError('Recovered manifest differs from archived report bindings')
        finally:
            for process in [manifest_decrypt, manifest_reader]:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=10)
        verifier = r'''
import hashlib,json,os,pathlib,sys
expected=int(sys.argv[1]); digest=sys.argv[2]
data=sys.stdin.buffer.read(16*1048576+1)
if len(data)!=expected or not data.startswith(b'%PDF-') or hashlib.sha256(data).hexdigest()!=digest:
 raise SystemExit('Recovered object integrity mismatch')
path=pathlib.Path('/recovered-reports/report.pdf')
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
if path.stat().st_mode & 0o077: raise SystemExit('Recovered object permission mismatch')
if hashlib.sha256(path.read_bytes()).hexdigest()!=digest: raise SystemExit('Restored file integrity mismatch')
print(json.dumps({'restored':True,'hash_matches':True,'private_mode':True}))
'''
        recovered = 0
        for index, artifact in enumerate(archived):
            reader = subprocess.Popen(['wsl', '-d', 'Ubuntu', '--exec', 'python3', '-c',
                'import pathlib,sys; d=pathlib.Path(sys.argv[1]).open("rb").read(17*1048576+1); assert len(d)<=17*1048576; sys.stdout.buffer.write(d)',
                copied['directory'] + '/' + str(index) + '.pdf.age'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            clear = subprocess.Popen(['age', '-d', '-i', str(key)], stdin=reader.stdout,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            reader.stdout.close(); reader.stdout = None
            target_name = name + '-pdf-' + str(index)
            targets.append(target_name)
            target = subprocess.Popen(['docker', 'run', '--rm', '--name', target_name, '--network', 'none', '--memory', '256m', '--pids-limit', '32',
                '--tmpfs', '/recovered-reports:rw,noexec,nosuid,size=32m,mode=700,uid=10001,gid=10001',
                '-i', image, '/app/.venv/bin/python', '-c', verifier, str(artifact['size_bytes']), artifact['sha256']],
                stdin=clear.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            clear.stdout.close(); clear.stdout = None
            try:
                result, _ = target.communicate(timeout=60)
                clear.communicate(timeout=20); reader.communicate(timeout=20)
                if target.returncode or clear.returncode or reader.returncode or json.loads(result).get('restored') is not True:
                    raise RuntimeError('Isolated private object restore failed; diagnostics suppressed')
            finally:
                for process in [target, clear, reader]:
                    if process.poll() is None:
                        process.kill(); process.wait(timeout=10)
            recovered += 1
        summary = {'verified_at': datetime.now(UTC).isoformat(), 'restore_passed': True,
            'objects_restored': recovered, 'total_plaintext_bytes_verified': total,
            'source_backup_identity_verified': True, 'manifest_restored_from_wsl': True,
            'archived_live_metadata_exact_match': True, 'source_backup_sha256': previous['backup_sha256'],
            'host_plaintext_files_created': False, 'production_writes': False, 'credentials_printed': False,
            'wsl_ciphertext_custody': copied, 'source_manifest_sha256': hashlib.sha256(manifest).hexdigest(),
            'private_key_copied': False, 'isolated_network': 'none', 'target_storage': 'private600 tmpfs',
            'byte_verification_passed': True, 'verifier_image_id': image, 'postgres_image_id': postgres_image,
            'limits': 'Existing report objects matched archived ownership/report/snapshot metadata and immutable SHA/size. Does not prove web authorization, full-system tenant replay or device-loss survival; WSL and Windows key share one physical host.'}
    finally:
        from qualification_cleanup import cleanup_targets
        cleanup = cleanup_targets(docker, targets)
        if not cleanup['cleanup_passed']:
            (run / 'cleanup-failure.json').write_text(json.dumps(cleanup), encoding='utf-8')
            raise RuntimeError('Private restore cleanup incomplete; overall qualification withheld')
        if summary is not None:
            summary['cleanup_passed'] = True
            summary['cleanup'] = cleanup['verified']
            (run / 'restore-summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
            print(json.dumps(summary))


if __name__ == '__main__':
    main()
