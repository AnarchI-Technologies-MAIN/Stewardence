"""Offline adversarial controls for source membership and pre-start checks."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from package_qualification_contract import verify_source, verify_runtime, verify_fixture

rejections = []


def rejected(label, callback):
    try:
        callback()
    except (RuntimeError, OSError):
        rejections.append(label)
        return
    raise RuntimeError('Falsely accepted package control: ' + label)


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root/'templates').mkdir()
    for name in ['templates/report.html', 'uv.lock', 'Dockerfile']:
        (root/name).write_text('synthetic qualification input')
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    assert verify_source(root, manifest) == 3
    for name in ['templates/report.html', 'uv.lock']:
        path = root/name
        data = path.read_bytes()
        path.unlink()
        rejected('missing_' + name, lambda: verify_source(root, manifest))
        path.write_bytes(data)
    (root/'templates/unexpected.html').write_text('unexpected')
    rejected('unexpected_source', lambda: verify_source(root, manifest))
    (root/'templates/unexpected.html').unlink()
    (root/'uv.lock').write_text('changed')
    rejected('changed_source', lambda: verify_source(root, manifest))
    (root/'uv.lock').write_text('synthetic qualification input')
    with patch.object(Path, 'read_bytes', side_effect=PermissionError('mock unreadable')):
        rejected('unreadable_source', lambda: verify_source(root, manifest))

image = 'sha256:' + 'a'*64
network_id = 'b'*64
database_id = 'c'*64
preview = {'network': 'synthetic-network', 'database': 'synthetic-db',
           'postgres_image_id': image}
network = {'Id': network_id, 'Name': preview['network'], 'Internal': True,
           'Containers': {database_id: {'Name': preview['database']}}}
database = {'Id': database_id, 'Name': '/' + preview['database'], 'Image': image,
            'State': {'Running': True}, 'HostConfig': {'PortBindings': {}},
            'NetworkSettings': {'Networks': {preview['network']: {
                'NetworkID': network_id, 'Aliases': ['qualification-db']}}}}
assert verify_fixture(preview, network, database) == (network_id, database_id)
for label, key, value in [('public_network', 'Internal', False),
                           ('renamed_network', 'Name', 'foreign')]:
    changed = copy.deepcopy(network)
    changed[key] = value
    rejected(label, lambda: verify_fixture(preview, changed, database))
changed = copy.deepcopy(database)
changed['HostConfig']['PortBindings'] = {'5432/tcp': [{'HostPort': '5432'}]}
rejected('public_database', lambda: verify_fixture(preview, network, changed))
changed = copy.deepcopy(database)
changed['Image'] = 'sha256:' + 'd'*64
rejected('foreign_database_image', lambda: verify_fixture(preview, network, changed))

runtime = {'Image': image, 'Config': {'User': 'agentledger'},
           'State': {'Running': False, 'Status': 'created'},
           'HostConfig': {'NetworkMode': network_id, 'ReadonlyRootfs': True, 'PortBindings': {},
               'PublishAllPorts': False, 'Privileged': False, 'CapDrop': ['ALL'],
               'CapAdd': None, 'SecurityOpt': ['no-new-privileges'],
               'Memory': 512*1024*1024, 'PidsLimit': 128,
               'Tmpfs': {'/tmp': 'rw,size=32m'}},
           'NetworkSettings': {'Networks': {'synthetic-network': {'NetworkID': network_id}}}}
verify_runtime(runtime, image, network_id)
for key, value in [('ReadonlyRootfs', False), ('PortBindings', {'8000/tcp': []}),
                   ('PublishAllPorts', True), ('Privileged', True), ('CapDrop', []),
                   ('CapAdd', ['SYS_ADMIN']), ('SecurityOpt', []), ('Memory', 0),
                   ('PidsLimit', 0), ('Tmpfs', {})]:
    bad = copy.deepcopy(runtime)
    bad['HostConfig'][key] = value
    rejected('runtime_' + key, lambda: verify_runtime(bad, image, network_id))
for label, path, value in [('wrong_image', 'Image', 'foreign')]:
    bad = copy.deepcopy(runtime)
    bad[path] = value
    rejected(label, lambda: verify_runtime(bad, image, network_id))
bad = copy.deepcopy(runtime)
bad['NetworkSettings']['Networks']['synthetic-network']['NetworkID'] = 'foreign'
rejected('foreign_network_identity', lambda: verify_runtime(bad, image, network_id))
bad = copy.deepcopy(runtime)
bad['State']['Running'] = True
rejected('already_started', lambda: verify_runtime(bad, image, network_id))
print(json.dumps({'qualification_passed': True, 'rejections': rejections,
                  'scope': 'Filesystem controls and mocked inspection contracts; not daemon faults.'}))
