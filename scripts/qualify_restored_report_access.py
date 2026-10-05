"""Isolated restored database + real PDF request-boundary qualification.

No production calls/writes. Ciphertext comes from Ubuntu WSL; key stays Windows.
All restored plaintext exists only in memory/container tmpfs. Containers/network
are explicitly named and verified absent before an overall passing receipt.
"""
import hashlib
import json
import os
import re
import secrets
import struct
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from qualify_report_object_restore import docker, pipeline

ROOT = Path(__file__).resolve().parents[1]
OBJECT_RECEIPT = ROOT/'evidence/report-object-restore/20261003T212039.504272Z/restore-summary.json'
DATABASE_RECEIPT = ROOT/'evidence/restore/20261003T190142.291805Z/restore-summary.json'
IMAGE_RECEIPT = ROOT/'evidence/20261004T011026.080005Z/qualification-summary.json'


def ciphertext(path, maximum, digest):
    program = 'import hashlib,pathlib,sys; d=pathlib.Path(sys.argv[1]).open("rb").read(int(sys.argv[2])+1); assert len(d)<=int(sys.argv[2]); assert hashlib.sha256(d).hexdigest()==sys.argv[3]; sys.stdout.buffer.write(d)'
    return subprocess.Popen(['wsl','-d','Ubuntu','--exec','python3','-c',program,path,str(maximum),digest],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def plaintext(path, maximum, digest, key):
    reader = ciphertext(path, maximum, digest)
    decoder = subprocess.Popen(['age','-d','-i',str(key)], stdin=reader.stdout,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    reader.stdout.close(); reader.stdout = None
    try:
        data, _ = decoder.communicate(timeout=40)
        reader.communicate(timeout=15)
        if decoder.returncode or reader.returncode or len(data)>maximum:
            raise RuntimeError('Pinned private backup read failed')
        return data
    finally:
        for process in [decoder, reader]:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)


def absent_container(name):
    exists = docker('container','ls','-aq','--filter','name=^/'+name+'$',capture_output=True,text=True).stdout.strip()
    if exists:
        docker('rm','-f',name,capture_output=True,timeout=30)
    if docker('container','ls','-aq','--filter','name=^/'+name+'$',capture_output=True,text=True).stdout.strip():
        raise RuntimeError('Private restored target cleanup failed')


def main():
    objects=json.loads(OBJECT_RECEIPT.read_bytes()); database=json.loads(DATABASE_RECEIPT.read_bytes())
    candidate=json.loads(IMAGE_RECEIPT.read_bytes())
    if not objects['restore_passed'] or not objects['cleanup_passed'] or candidate['exit_code']!=0:
        raise RuntimeError('Required prior qualification is absent')
    key=Path(database['private_key_file']); image=candidate['image_id']; pg_image=objects['postgres_image_id']
    for value in [image,pg_image]:
        if docker('image','inspect','--format','{{.Id}}',value,capture_output=True,text=True).stdout.strip()!=value:
            raise RuntimeError('Pinned local image differs')
    run=ROOT/'evidence/restored-report-access'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    run.mkdir(parents=True)
    probe=run/'restored-report-probe.py'
    probe.write_bytes((ROOT/'scripts/restored_report_access_probe.py').read_bytes())
    probe_digest=hashlib.sha256(probe.read_bytes()).hexdigest()
    prefix='stewardence-restored-access-'+uuid.uuid4().hex
    names=[prefix+'-db',prefix+'-migrations',prefix+'-app']
    network_created=False; result=None
    try:
        docker('network','create','--internal','--label','stewardence.qualification-run='+prefix,prefix,stdout=subprocess.DEVNULL)
        network_created=True
        docker('run','-d','--name',names[0],'--network',prefix,'--network-alias','restored-db',
               '--memory','512m','--pids-limit','128','--tmpfs','/var/lib/postgresql:rw,size=512m',
               '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=restored',pg_image,
               stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(60):
            if subprocess.run(['docker','exec',names[0],'pg_isready','-h','127.0.0.1','-U','postgres','-d','restored'],capture_output=True).returncode==0:
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Isolated stable database readiness failed')
        docker('exec',names[0],'psql','-U','postgres','-d','restored','-v','ON_ERROR_STOP=1','-c',
               'CREATE ROLE agentledger_owner; CREATE ROLE agentledger_app; CREATE ROLE agentledger_worker;',capture_output=True)
        cipher=ciphertext(database['wsl_ciphertext_custody']['encrypted_path'],200*1048576,database['backup_sha256'])
        decrypt=subprocess.Popen(['age','-d','-i',str(key)],stdin=cipher.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        cipher.stdout.close(); cipher.stdout=None
        restore=subprocess.Popen(['docker','exec','-i',names[0],'pg_restore','-U','postgres','-d','restored','--exit-on-error'],
                                 stdin=decrypt.stdout,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        decrypt.stdout.close(); decrypt.stdout=None
        try:
            pipeline(decrypt,restore,timeout=120)
            cipher.communicate(timeout=15)
            if cipher.returncode: raise RuntimeError('Pinned source database ciphertext unavailable')
        finally:
            if cipher.poll() is None: cipher.kill(); cipher.wait(timeout=10)
        passwords={role:secrets.token_urlsafe(24) for role in ['agentledger_owner','agentledger_app','agentledger_worker']}
        if any(not re.fullmatch('[A-Za-z0-9_-]+',value) for value in passwords.values()):
            raise RuntimeError('Local credential generation invalid')
        ddl='\n'.join("ALTER ROLE "+role+" LOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT PASSWORD '"+value+"';" for role,value in passwords.items())
        docker('exec','-i',names[0],'psql','-U','postgres','-d','restored','-v','ON_ERROR_STOP=1',
               input=ddl.encode(),capture_output=True)
        environment=os.environ.copy()
        environment.update({'DJANGO_SETTINGS_MODULE':'agentledger.settings.development',
                            'DJANGO_SECRET_KEY':secrets.token_urlsafe(48),
                            'DATABASE_URL':'postgresql://postgres@restored-db:5432/restored'})
        for variable,role in [('OWNER_DATABASE_URL','agentledger_owner'),('APP_DATABASE_URL','agentledger_app'),('WORKER_DATABASE_URL','agentledger_worker')]:
            environment[variable]='postgresql://'+role+':'+passwords[role]+'@restored-db:5432/restored'
        arguments=[]
        for variable in ['DJANGO_SETTINGS_MODULE','DJANGO_SECRET_KEY','DATABASE_URL','OWNER_DATABASE_URL','APP_DATABASE_URL','WORKER_DATABASE_URL']:
            arguments.extend(['-e',variable])
        # Upgrade only the isolated restored clone, using the exact candidate ID.
        migrated=subprocess.run(['docker','run','--rm','--name',names[1],'--network',prefix,'--memory','512m',
            '--pids-limit','128',*arguments,image,'/app/.venv/bin/python','manage.py','migrate','--noinput'],
            env=environment,capture_output=True,timeout=120)
        (run/'migration.log').write_bytes(migrated.stdout)
        if migrated.returncode:
            raise RuntimeError('Candidate migration on isolated restored data failed; details suppressed')
        environment['DATABASE_URL']=environment['APP_DATABASE_URL']
        manifest_file=next(item for item in objects['wsl_ciphertext_custody']['files'] if item['file']=='manifest.json.age')
        manifest=plaintext(objects['wsl_ciphertext_custody']['directory']+'/manifest.json.age',1048576,manifest_file['sha256'],key)
        if hashlib.sha256(manifest).hexdigest()!=objects['source_manifest_sha256']:
            raise RuntimeError('Restored source manifest differs from accepted binding')
        rows=json.loads(manifest)
        if len(rows)!=objects['objects_restored'] or len(rows)>100:
            raise RuntimeError('Restored artifact inventory mismatch')
        framed=bytearray(struct.pack('!I',len(manifest))+manifest)
        total=0
        for index,item in enumerate(rows):
            receipt=next(value for value in objects['wsl_ciphertext_custody']['files'] if value['file']==str(index)+'.pdf.age')
            pdf=plaintext(objects['wsl_ciphertext_custody']['directory']+'/'+receipt['file'],17*1048576,receipt['sha256'],key)
            if len(pdf)!=item['size_bytes'] or len(pdf)>16*1048576 or hashlib.sha256(pdf).hexdigest()!=item['sha256']:
                raise RuntimeError('Restored PDF bytes differ from immutable database metadata')
            total+=len(pdf)
            if total>128*1048576: raise RuntimeError('Private request restore exceeds total resource bound')
            framed.extend(struct.pack('!I',len(pdf))+pdf)
        tested=subprocess.run(['docker','run','--rm','--name',names[2],'--network',prefix,'--memory','512m',
            '--pids-limit','128','--tmpfs','/recovered-reports:rw,noexec,nosuid,size=128m,mode=700,uid=10001,gid=10001',
            '--mount','type=bind,source='+str(probe)+',target=/tmp/restored-report-probe.py,readonly',
            '-i',*arguments,image,'/app/.venv/bin/python','/tmp/restored-report-probe.py'],
            env=environment,input=framed,capture_output=True,timeout=120)
        try:
            outcome=json.loads(tested.stdout)
        except (ValueError,TypeError):
            raise RuntimeError('Restored request qualification response invalid; diagnostics suppressed') from None
        (run/'request-probe.json').write_text(json.dumps(outcome,indent=2),encoding='utf-8')
        if tested.returncode or outcome.get('qualified') is not True:
            raise RuntimeError('Restored request qualification failed; see sanitized probe')
        result={'verified_at':datetime.now(UTC).isoformat(),'qualification_passed':True,'request_probe':outcome,
                'source_object_receipt':str(OBJECT_RECEIPT),'source_backup_sha256':database['backup_sha256'],
                'candidate_image_id':image,'postgres_image_id':pg_image,'probe_sha256':probe_digest,
                'total_plaintext_bytes_verified':total,'host_plaintext_files_created':False,'production_writes':False,
                'candidate_migrations_on_isolated_clone':True,'same_physical_host_custody':True}
    finally:
        from qualification_cleanup import cleanup_targets
        cleanup = cleanup_targets(docker, names, prefix, network_owner=prefix)
        if not cleanup['cleanup_passed']:
            (run/'cleanup-failure.json').write_text(json.dumps(cleanup),encoding='utf-8')
            raise RuntimeError('Isolated request cleanup incomplete; overall qualification withheld')
        if result is not None:
            result['cleanup_passed']=True
            result['cleanup']=cleanup['verified']
            (run/'qualification-summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            print(json.dumps(result))


if __name__=='__main__':
    main()
