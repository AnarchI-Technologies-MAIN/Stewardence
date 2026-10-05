"""Exact HTTP launcher controls: rejected pre-start inspections cannot start."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import qualify_production_package_http as launcher

network_id = 'b'*64
database_id = 'c'*64
container_id = 'd'*64
name = 'stewardence-visualqa-7e62efb888'
preview = {'name': name, 'network': name, 'database': name+'-db',
           'postgres_image_id': 'sha256:'+'a'*64}
network = {'Id': network_id, 'Name': name, 'Internal': True,
           'Containers': {database_id: {'Name': preview['database']}}}
database = {'Id': database_id, 'Name': '/'+preview['database'],
            'Image': preview['postgres_image_id'], 'State': {'Running': True},
            'HostConfig': {'PortBindings': {}},
            'NetworkSettings': {'Networks': {name: {
                'NetworkID': network_id, 'Aliases': ['qualification-db']}}}}
runtime = {'Id': container_id, 'Image': launcher.IMAGE, 'Config': {'User': 'agentledger'},
           'State': {'Running': False, 'Status': 'created'},
           'HostConfig': {'NetworkMode': network_id, 'ReadonlyRootfs': True, 'PortBindings': {},
               'PublishAllPorts': False, 'Privileged': False, 'CapDrop': ['ALL'],
               'CapAdd': None, 'SecurityOpt': ['no-new-privileges'],
               'Memory': 512*1024*1024, 'PidsLimit': 128,
               'Tmpfs': {'/tmp': 'rw,size=32m'}},
           'NetworkSettings': {'Networks': {name: {'NetworkID': network_id}}}}
results = []
for scenario in ['writable_root', 'public_port', 'foreign_image', 'foreign_network']:
    bad = copy.deepcopy(runtime)
    if scenario == 'writable_root':
        bad['HostConfig']['ReadonlyRootfs'] = False
    if scenario == 'public_port':
        bad['HostConfig']['PortBindings'] = {'8000/tcp': [{'HostPort': '8000'}]}
    if scenario == 'foreign_image':
        bad['Image'] = 'foreign'
    if scenario == 'foreign_network':
        bad['NetworkSettings']['Networks'][name]['NetworkID'] = 'foreign'
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        qualification = root/'pinned-qualification'
        qualification.mkdir()
        (root/'evidence').mkdir()
        (root/'source').mkdir()
        (root/'scripts').mkdir()
        (root/'scripts/production_package_http_probe.py').write_text('# mocked HTTP probe')
        (root/'source/uv.lock').write_text('synthetic')
        (qualification/'qualification-summary.json').write_text(json.dumps({
            'exit_code': 0, 'test_arguments': ['tests'], 'image_id': 'synthetic-reference'}))
        (qualification/'source-manifest.json').write_text(json.dumps({
            'uv.lock': hashlib.sha256(b'synthetic').hexdigest()}))
        (root/'evidence/visual-preview.json').write_text(json.dumps(preview))
        calls = []

        def docker(*args):
            calls.append(args)
            if args[:2] == ('network', 'inspect'):
                return CompletedProcess(args, 0, json.dumps([network]), '')
            if args == ('inspect', preview['database']):
                return CompletedProcess(args, 0, json.dumps([database]), '')
            if args[0] == 'create':
                return CompletedProcess(args, 0, container_id+'\n', '')
            if args == ('inspect', container_id):
                return CompletedProcess(args, 0, json.dumps([bad]), '')
            if args[0] == 'ps':
                return CompletedProcess(args, 0, '', '')
            raise RuntimeError('Unexpected Docker action: '+str(args))

        with patch.object(launcher, 'ROOT', root), patch.object(launcher, 'QUALIFICATION', qualification), \
             patch.object(launcher, 'docker', docker), patch.object(launcher.subprocess, 'run'):
            try:
                launcher.main()
            except RuntimeError as error:
                assert 'before start' in str(error), error
            else:
                raise RuntimeError('Exact caller accepted: '+scenario)
        assert not any(call[0] in {'start', 'exec'} for call in calls), calls
        assert not list((root/'evidence').rglob('qualification-summary.json'))
        results.append({'scenario': scenario, 'start_called': False, 'success_receipt_written': False})
print(json.dumps({'qualification_passed': True, 'controls': results,
                  'scope': 'Exact launcher mocked-Docker controls; no actual daemon fault.'}))
