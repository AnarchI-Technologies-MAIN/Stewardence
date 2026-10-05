"""Read-only live dump -> encrypted local backup -> isolated tmpfs restore.

No plaintext dump file, production writes, host database port or app activation.
Private key stays in a user/SYSTEM-only directory; never print key or database data.
"""
import hashlib
import base64
import json
import shlex
import shutil
import subprocess
import uuid
from datetime import datetime, UTC
from pathlib import Path
from preserve_source import SSH

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def main():
    if not shutil.which('age') or not shutil.which('age-keygen'):
        raise SystemExit('Age encryption tools unavailable')
    folder = Path.home()/'.stewardence-recovery'
    folder.mkdir(exist_ok=True)
    shell = shutil.which('pwsh') or 'powershell'
    sid = subprocess.check_output([shell,'-NoProfile','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],text=True).strip()
    subprocess.run(['icacls',str(folder),'/inheritance:r','/grant:r',
        '*'+sid+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],check=True,capture_output=True)
    key = folder/'backup.agekey'
    if not key.exists():
        subprocess.run(['age-keygen','-o',str(key)],check=True,capture_output=True)
    recipient = subprocess.check_output(['age-keygen','-y',str(key)],text=True).strip()
    if not recipient.startswith('age1'):
        raise SystemExit('Backup key validation failed')
    run_dir = ROOT/'evidence'/'restore'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    run_dir.mkdir(parents=True)
    backup = run_dir/'live-database.dump.age'
    # Refuse an unset database identity or a source too large for the bounded target.
    identity_program = 'import django,json; django.setup(); from django.db import connection; c=connection.cursor(); c.execute("SELECT current_database(), pg_database_size(current_database())"); print(json.dumps(c.fetchone()))'
    preflight = 'sudo -n docker exec stewardence-web /app/.venv/bin/python -c '+shlex.quote(identity_program)
    database_name, source_bytes = json.loads(subprocess.check_output(SSH+[preflight],timeout=30,text=True))
    if not isinstance(database_name,str) or not database_name or not isinstance(source_bytes,int):
        raise SystemExit('Live database identity preflight invalid')
    if source_bytes > 200*1024*1024:
        raise SystemExit('Source exceeds the isolated restore size gate; review target capacity')
    # Credentials are resolved inside the existing database container, not printed.
    remote = 'sudo -n docker exec -u postgres stewardence-db pg_dump --format=custom --lock-wait-timeout=10s --dbname='+shlex.quote(database_name)
    dump = subprocess.Popen(SSH+[remote],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    encrypt = subprocess.Popen(['age','-r',recipient,'-o',str(backup)],stdin=dump.stdout,
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    dump.stdout.close()
    dump.stdout = None
    try:
        encrypt.communicate(timeout=180)
        dump.communicate(timeout=30)
        if encrypt.returncode or dump.returncode:
            raise RuntimeError('Encrypted read-only export failed; details suppressed')
    finally:
        if dump.poll() is None: dump.kill()
        if encrypt.poll() is None: encrypt.kill()
    # Alexander selected Ubuntu WSL2 ciphertext custody and Windows key custody.
    # This is separate from the Droplet, but not separate physical-host custody.
    custody_code = r'''
import pathlib,sys,os,hashlib,json,tempfile
root=pathlib.Path.home()/'stewardence-backups'
root.mkdir(mode=0o700,exist_ok=True)
os.chmod(root,0o700)
name=sys.argv[1]
if not name.endswith('.dump.age') or pathlib.Path(name).name!=name: raise SystemExit('Invalid encrypted backup identity')
source=pathlib.Path(sys.argv[2])
if source.stat().st_size>200*1024*1024: raise SystemExit('Encrypted backup exceeds custody bounds')
data=source.read_bytes()
if len(data)>200*1024*1024 or not data.startswith(b'age-encryption.org/v1'): raise SystemExit('Encrypted backup validation failed')
fd,tmp=tempfile.mkstemp(prefix='.backup-',dir=root)
try:
 with os.fdopen(fd,'wb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
 os.link(tmp,root/name)
finally: pathlib.Path(tmp).unlink(missing_ok=True)
print(json.dumps({'distribution':'Ubuntu','encrypted_path':str(root/name),'sha256':hashlib.sha256((root/name).read_bytes()).hexdigest(),'key_copied':False}))
'''
    wsl_source=subprocess.check_output(['wsl','-d','Ubuntu','--exec','wslpath','-u',str(backup)],timeout=15,text=True).strip()
    custody_loader='import base64;exec(base64.b64decode('+repr(base64.b64encode(custody_code.encode()).decode())+'))'
    wsl_backup = json.loads(subprocess.check_output(['wsl','-d','Ubuntu','--exec','python3','-c',custody_loader,
        run_dir.name+'.dump.age',wsl_source],timeout=30))
    if wsl_backup['sha256']!=hashlib.sha256(backup.read_bytes()).hexdigest():
        raise RuntimeError('WSL encrypted backup differs from source ciphertext')
    name = 'stewardence-restore-'+uuid.uuid4().hex[:10]
    network = name+'-network'
    network_created = False
    container_created = False
    try:
        docker('network','create','--internal',network,stdout=subprocess.DEVNULL)
        network_created = True
        docker('run','-d','--name',name,'--network',network,'--memory','512m',
            '--pids-limit','128','--tmpfs','/var/lib/postgresql:rw,size=512m',
            '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=restored',
            'postgres:18.6',stdout=subprocess.DEVNULL)
        container_created = True
        import time
        for _ in range(60):
            ready = subprocess.run(['docker','exec',name,'pg_isready','-h','127.0.0.1','-U','postgres','-d','restored'],capture_output=True)
            if ready.returncode == 0: break
            time.sleep(.5)
        else: raise RuntimeError('Isolated restore database not ready')
        roles = 'CREATE ROLE agentledger_owner; CREATE ROLE agentledger_app; CREATE ROLE agentledger_worker;'
        docker('exec',name,'psql','-U','postgres','-d','restored','-v','ON_ERROR_STOP=1','-c',roles,capture_output=True)
        cipher_read = subprocess.Popen(['wsl','-d','Ubuntu','--exec','python3','-c',
            'import pathlib,sys; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())',wsl_backup['encrypted_path']],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        decrypt = subprocess.Popen(['age','-d','-i',str(key)],stdin=cipher_read.stdout,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        cipher_read.stdout.close()
        cipher_read.stdout=None
        restore = subprocess.Popen(['docker','exec','-i',name,'pg_restore','-U','postgres',
            '-d','restored','--exit-on-error'],stdin=decrypt.stdout,
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        decrypt.stdout.close()
        decrypt.stdout = None
        try:
            restore.communicate(timeout=180)
            decrypt.communicate(timeout=30)
            cipher_read.communicate(timeout=30)
            if restore.returncode or decrypt.returncode or cipher_read.returncode:
                raise RuntimeError('Isolated restore failed; details suppressed')
        finally:
            if restore.poll() is None: restore.kill()
            if decrypt.poll() is None: decrypt.kill()
            if cipher_read.poll() is None: cipher_read.kill()
        sql = "SELECT json_build_object('migrations',(SELECT count(*) FROM django_migrations),'forced_rls_tables',(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r' AND c.relrowsecurity AND c.relforcerowsecurity),'database_bytes',pg_database_size(current_database()));"
        metadata = json.loads(docker('exec',name,'psql','-U','postgres','-d','restored','-Atqc',sql,capture_output=True,text=True).stdout)
        if metadata['migrations'] < 49 or metadata['forced_rls_tables'] < 25:
            raise RuntimeError('Restored schema does not meet recorded live baseline')
        # Compare catalog identities/ACLs without exporting customer values or role passwords.
        catalog_sql = "SELECT coalesce(json_agg(row_to_json(t) ORDER BY t.kind,t.name),'[]'::json) FROM (SELECT 'relation' kind,n.nspname||'.'||c.relname name,pg_get_userbyid(c.relowner) owner,c.relacl::text acl,c.relrowsecurity rls,c.relforcerowsecurity forced FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','app_private') AND c.relkind IN ('r','S','v') UNION ALL SELECT 'function',n.nspname||'.'||p.proname||'('||pg_get_function_identity_arguments(p.oid)||')',pg_get_userbyid(p.proowner),p.proacl::text,false,false FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','app_private')) t;"
        source_catalog = json.loads(subprocess.check_output(SSH+['sudo -n docker exec -u postgres stewardence-db psql -d '+shlex.quote(database_name)+' -Atqc '+shlex.quote(catalog_sql)],timeout=30,text=True))
        restored_catalog = json.loads(docker('exec',name,'psql','-U','postgres','-d','restored','-Atqc',catalog_sql,capture_output=True,text=True).stdout)
        if source_catalog != restored_catalog:
            raise RuntimeError('Restored ownership or catalog privileges differ from live source')
        metadata['catalog_ownership_acl_match']=True
        metadata['catalog_objects_checked']=len(source_catalog)
        role_sql="SELECT json_agg(row_to_json(t) ORDER BY t.rolname) FROM (SELECT rolname,rolsuper,rolbypassrls FROM pg_roles WHERE rolname IN ('agentledger_owner','agentledger_app','agentledger_worker')) t;"
        roles_restored=json.loads(docker('exec',name,'psql','-U','postgres','-d','restored','-Atqc',role_sql,capture_output=True,text=True).stdout)
        if len(roles_restored)!=3 or any(r['rolsuper'] or r['rolbypassrls'] for r in roles_restored):
            raise RuntimeError('Restored runtime role safety check failed')
        summary = {'verified_at':datetime.now(UTC).isoformat(),'restore_passed':True,
            'live_export_read_only':True,'production_writes':False,'isolated_target':True,
            'plaintext_dump_file_created':False,'source_database_bytes':source_bytes,'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),
            'encrypted_backup':str(backup),'wsl_ciphertext_custody':wsl_backup,
            'restore_ciphertext_source':'Ubuntu WSL2','private_key_file':str(key),'restored_metadata':metadata,
            'limits':'Schema/data archive restore from WSL2 ciphertext with Windows key; ownership/ACL comparison and no superuser/BYPASSRLS. Both custody locations share one physical Windows machine. Login authentication, tenant replay and report object recovery remain open.'}
        (run_dir/'restore-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary))
    finally:
        if container_created: subprocess.run(['docker','rm','-f',name],capture_output=True)
        if network_created: subprocess.run(['docker','network','rm',network],capture_output=True)


if __name__ == '__main__':
    main()
