"""Real isolated network creation followed by a simulated lost acknowledgement."""
import json
import subprocess
import uuid
from pathlib import Path
from qualification_cleanup import cleanup_targets

name = 'stewardence-cleanup-fault-' + uuid.uuid4().hex
def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)

try:
    docker('network', 'create', '--internal', '--label', 'stewardence.qualification-run='+name, name, capture_output=True, timeout=30)
    raise RuntimeError('Simulated acknowledgement loss after successful creation')
except RuntimeError:
    receipt = cleanup_targets(docker, [], name, network_owner=name)
    assert receipt['cleanup_passed']
    assert receipt['verified'] == [{'target': name, 'absence_verified': True}]
    receipt.update(qualification_passed=True, real_disposable_network=True,
                   simulated_acknowledgement_loss=True, production_touched=False)
    destination = Path(__file__).resolve().parents[1] / 'evidence/ambiguous-network-cleanup-qualification.json'
    destination.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))
finally:
    remaining = cleanup_targets(docker, [], name, network_owner=name)
    if not remaining['cleanup_passed']:
        raise RuntimeError('Disposable failure qualification cleanup incomplete')
