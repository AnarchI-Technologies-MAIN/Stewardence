"""Start a synthetic localhost-only preview; never contacts the Droplet."""
import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def docker(*args):
    return subprocess.run(['docker',*args],check=True,capture_output=True,text=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--image',required=True)
    options=parser.parse_args()
    if not options.image.startswith('stewardence-local-qualification:stewardence-local-'):
        raise SystemExit('A qualified local image is required')
    name='stewardence-visualqa-'+uuid.uuid4().hex[:10]
    image_id=docker('image','inspect','--format','{{.Id}}',options.image).stdout.strip()
    postgres_id=docker('image','inspect','--format','{{.Id}}','postgres:18.6').stdout.strip()
    network=False; preview_network=False; db=False; app=False
    try:
        docker('network','create','--internal',name); network=True
        docker('run','-d','--name',name+'-db','--network',name,'--network-alias','qualification-db',
            '--memory','256m','--pids-limit','128','--tmpfs','/var/lib/postgresql:rw,size=256m',
            '-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=qualification',postgres_id);db=True
        for _ in range(60):
            ready=subprocess.run(['docker','exec',name+'-db','pg_isready','-h','127.0.0.1','-U','postgres'],capture_output=True)
            if ready.returncode==0:break
            time.sleep(.5)
        docker('run','-d','--name',name+'-app','--network',name,'--memory','512m','--pids-limit','256',
            '-p','127.0.0.1:8765:8000','-e','STEWARDENCE_ISOLATED_QA=1',
            '-e','DJANGO_SETTINGS_MODULE=agentledger.settings.qualification',
            '-e','DATABASE_URL=postgresql://postgres@qualification-db:5432/qualification',
            image_id,'/app/.venv/bin/python','scripts/preview_bootstrap.py');app=True
        # Docker suppresses published ports on internal networks. A second
        # bridge exposes only the configured localhost binding; masquerading
        # is disabled. The database remains on its internal network alone.
        docker('network','create','--opt','com.docker.network.bridge.enable_ip_masquerade=false',name+'-preview');preview_network=True
        docker('network','connect',name+'-preview',name+'-app')
        summary={'name':name,'image_id':image_id,'postgres_image_id':postgres_id,'url':'http://127.0.0.1:8765/',
            'scope':'Synthetic visual qualification; isolated localhost, no live provider credentials or customer data',
            'database':name+'-db','application':name+'-app','network':name,'preview_network':name+'-preview'}
        (ROOT/'evidence/visual-preview.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary))
    except Exception:
        if app:subprocess.run(['docker','rm','-f',name+'-app'],capture_output=True)
        if db:subprocess.run(['docker','rm','-f',name+'-db'],capture_output=True)
        if preview_network:subprocess.run(['docker','network','rm',name+'-preview'],capture_output=True)
        if network:subprocess.run(['docker','network','rm',name],capture_output=True)
        raise


if __name__=='__main__': main()
