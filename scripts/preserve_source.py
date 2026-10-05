"""Read-only SSH source acquisition. No production configuration is collected."""
import hashlib
import io
import json
import pathlib
import shlex
import subprocess
import tarfile
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
SSH = ['ssh', '-o', 'StrictHostKeyChecking=yes', '-o', 'BatchMode=yes',
       '-o', 'IdentitiesOnly=yes', '-i', r'C:\Users\alexg\.ssh\anarchi-mainframe-ed25519',
       'anarchi@165.245.199.232']
REMOTE = r'''
import subprocess,pathlib,tarfile,io,json,hashlib,sys
root=pathlib.Path('/home/anarchi/stewardence')
files=subprocess.check_output(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard']).decode().split('\0')
files=sorted(set(p for p in files if p))
manifest={'head':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),'status':subprocess.check_output(['git','-C',str(root),'status','--short'],text=True),'files':{},'excluded':[]}
buf=io.BytesIO()
with tarfile.open(fileobj=buf,mode='w:gz') as tar:
 for name in files:
  p=root/name
  if p.is_symlink() or not p.is_file() or '.env' in p.name or p.suffix.lower() in {'.pem','.key','.p12','.pfx','.dump','.age'} or any(part in {'secrets','node_modules','.venv'} for part in p.parts[4:-1]):
   manifest['excluded'].append(name); continue
  raw=p.read_bytes()
  manifest['files'][name]=hashlib.sha256(raw).hexdigest()
  tar.add(p,arcname='source/'+name,recursive=False)
 data=json.dumps(manifest,indent=2).encode()
 entry=tarfile.TarInfo('baseline-manifest.json'); entry.size=len(data); tar.addfile(entry,io.BytesIO(data))
sys.stdout.buffer.write(buf.getvalue())
'''

def main():
    target = ROOT / 'baseline'
    if (target / 'baseline-manifest.json').exists():
        raise SystemExit('Existing preserved baseline: refusing replacement')
    raw = subprocess.check_output(SSH + ['python3 -c ' + shlex.quote(REMOTE)])
    archive = target / 'deployed-source.tar.gz'
    archive.write_bytes(raw)
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as tar:
        tar.extractall(target, filter='data')
    manifest = json.loads((target / 'baseline-manifest.json').read_text())
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((target / 'source' / name).read_bytes()).hexdigest() == expected, name
    manifest['acquired_at'] = datetime.now(timezone.utc).isoformat()
    manifest['archive_sha256'] = hashlib.sha256(raw).hexdigest()
    (target / 'baseline-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'head':manifest['head'],'files':len(manifest['files']), 'excluded':manifest['excluded'], 'archive_sha256':manifest['archive_sha256']}))

if __name__ == '__main__':
    main()
