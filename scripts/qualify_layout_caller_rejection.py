"""Exact layout launcher must withhold success for failed child subchecks."""
import copy
import json
import tempfile
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import qualify_report_layout as launcher

baseline = {'qualification_passed': True,
    'geometry': {'viewport': 688, 'document_width': 688, 'table_columns': [137]*5},
    'content_checks': {specimen: {'pages': 1, 'nonempty_pages': True,
                                'inventory_section_complete': True}
                       for specimen in ['long-input', 'multi-tool', 'long-table']}}
controls = []
for field in ['nonempty_pages', 'inventory_section_complete', 'pages']:
    bad = copy.deepcopy(baseline)
    bad['content_checks']['long-input'][field] = False
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root/'scripts').mkdir()
        payload = root/'payload.json'
        payload.write_text('{}')
        for file in ['report_layout_probe.py','report_layout_geometry.py','report_layout_content.py']:
            (root/'scripts'/file).write_text('# mock frozen probe')
        state = {'Image': launcher.IMAGE, 'Config': {'User': '10001:10001'},
            'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'CapDrop': ['ALL'],
                'SecurityOpt': ['no-new-privileges'], 'Memory': 512*1024*1024, 'PidsLimit': 256},
            'State': {'ExitCode': 0, 'OOMKilled': False}}

        def docker(*args):
            if args[0] == 'inspect':
                return CompletedProcess(args, 0, json.dumps([state]), '')
            return CompletedProcess(args, 0, '', '')

        def run(args, **kwargs):
            if args[:3] == ['docker','start','-a']:
                return CompletedProcess(args, 0, '\n'.join(map(json.dumps,
                    [{'rendered': []}, {'rendered': []}, bad])), '')
            return CompletedProcess(args, 0, '', '')

        with patch.object(launcher, 'ROOT', root), patch.object(launcher, 'PAYLOAD', payload), \
             patch.object(launcher, 'docker', docker), patch.object(launcher.subprocess, 'run', run):
            try:
                launcher.main()
            except RuntimeError as error:
                assert 'failed content checks' in str(error), error
            else:
                raise RuntimeError('Exact layout caller accepted false field: '+field)
        assert not list(root.rglob('qualification-summary.json'))
        controls.append({'field': field, 'success_receipt_written': False})
print(json.dumps({'qualification_passed': True, 'controls': controls,
                  'scope': 'Exact launcher mocked child receipts; not a daemon failure.'}))
