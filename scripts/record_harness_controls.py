"""Freeze passing standalone adversarial-control receipts for scoped review."""
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
results = []
for script in ['qualify_package_contract_rejection.py', 'qualify_package_caller_rejection.py',
               'qualify_layout_caller_rejection.py']:
    execution = subprocess.run(['python', str(root/'scripts'/script)],
                               capture_output=True, text=True, check=True)
    results.append({'script': script, 'script_sha256': hashlib.sha256(
        (root/'scripts'/script).read_bytes()).hexdigest(), 'exit_code': execution.returncode,
        'result': json.loads(execution.stdout)})
qa = root/'evidence/report-layout-qualified/20261003T234711.969251Z'
execution = subprocess.run(['docker', 'run', '--rm', '--network', 'none', '--read-only',
    '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
    '--memory', '512m', '--pids-limit', '256', '--tmpfs', '/tmp:rw,size=128m',
    '--mount', 'type=bind,source='+str(qa)+',target=/qa,readonly',
    'sha256:d4c73ead4d1c6bf16c77089a6837e039a0ab84c4a9a48d8b4f60852809e57a27',
    '/app/.venv/bin/python', '/qa/qualify_layout_content_rejection.py'],
    capture_output=True, text=True, check=True)
results.append({'script': 'qualify_layout_content_rejection.py', 'exit_code': execution.returncode,
                'result': json.loads(execution.stdout),
                'script_sha256': hashlib.sha256((qa/'qualify_layout_content_rejection.py').read_bytes()).hexdigest()})
target = root/'evidence/qualification-harness-negative-controls-20261003.json'
target.write_text(json.dumps(results, indent=2))
print(json.dumps({'receipt': str(target), 'passing_control_groups': len(results)}))
