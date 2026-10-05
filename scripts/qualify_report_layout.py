"""Fresh, isolated packaged-renderer stress qualification and artifact binding."""
import hashlib
import json
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from qualify_renderer_package import ROOT, IMAGE, PAYLOAD, docker
from report_layout_content import verify_receipt


def main():
    output = ROOT/'evidence/report-layout-qualified'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    output.mkdir(parents=True)
    shutil.copyfile(PAYLOAD, output/'synthetic-render-payload.json')
    for file in ['report_layout_probe.py','report_layout_geometry.py','report_layout_content.py']:
        shutil.copyfile(ROOT/'scripts'/file,output/file)
    name = 'stewardence-layout-qualification-'+uuid.uuid4().hex
    result = None
    try:
        docker('create','--name',name,'--network','none','--read-only','--user','10001:10001',
               '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--pids-limit','256',
               '--tmpfs','/tmp:rw,size=128m','--tmpfs','/work/output:rw,size=32m,mode=0700,uid=10001,gid=10001',
               '--mount','type=bind,source='+str(output)+',target=/qa', IMAGE,
               '/app/.venv/bin/python','-c',
               'import runpy,sys; sys.path.insert(0,"/qa"); runpy.run_path("/qa/report_layout_probe.py"); runpy.run_path("/qa/report_layout_probe.py"); runpy.run_path("/qa/report_layout_geometry.py")')
        state = json.loads(docker('inspect',name).stdout)[0]
        host = state['HostConfig']
        if (state['Image'] != IMAGE or state['Config']['User'] != '10001:10001'
                or host['NetworkMode'] != 'none' or not host['ReadonlyRootfs']
                or host['CapDrop'] != ['ALL'] or 'no-new-privileges' not in host['SecurityOpt']
                or host['Memory'] != 512*1024*1024 or host['PidsLimit'] != 256):
            raise RuntimeError('Layout runtime constraints changed')
        execution = subprocess.run(['docker','start','-a',name],capture_output=True,text=True)
        (output/'layout.log').write_text(execution.stdout+execution.stderr,encoding='utf-8')
        final_state = json.loads(docker('inspect',name).stdout)[0]['State']
        if execution.returncode or final_state['ExitCode'] or final_state['OOMKilled']:
            raise RuntimeError('Layout execution failed; inspect frozen run log')
        receipts = [json.loads(line) for line in execution.stdout.splitlines() if line.startswith('{')]
        if len(receipts) != 3 or receipts[0] != receipts[1] or not receipts[2]['qualification_passed']:
            raise RuntimeError('Layout repeated renders or geometry verification failed')
        verify_receipt(receipts[2])
        artifacts = []
        for item in receipts[0]['rendered']:
            name_part = item['specimen']
            if hashlib.sha256((output/(name_part+'.pdf')).read_bytes()).hexdigest() != item['pdf_sha256']:
                raise RuntimeError('Layout artifact digest mismatch')
            artifacts.append(dict(item,input_sha256=hashlib.sha256((output/(name_part+'.json')).read_bytes()).hexdigest()))
        result = dict(receipts[2],renderer_image_id=IMAGE,repeat_bytes_equal=True,
                      artifacts=artifacts,verified_at=datetime.now(UTC).isoformat(),
                      runtime_constraints={key:host[key] for key in
                          ['NetworkMode','ReadonlyRootfs','CapDrop','SecurityOpt','Memory','PidsLimit','Tmpfs']})
    finally:
        subprocess.run(['docker','rm','-f',name],capture_output=True)
        if docker('ps','-aq','--filter','name=^'+name+'$').stdout.strip():
            raise RuntimeError('Layout qualification cleanup incomplete')
    result['cleanup_verified'] = True
    (output/'qualification-summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(dict(result,evidence_directory=str(output))))


if __name__ == '__main__':
    main()
