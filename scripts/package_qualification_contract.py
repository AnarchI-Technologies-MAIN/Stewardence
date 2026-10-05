"""Fail-closed source and pre-start runtime checks for local HTTP qualification."""
import hashlib
import re


def selected(key):
    key = key.replace('\\', '/')
    return (key.startswith(('apps/', 'src/', 'templates/', 'static/', 'collector/'))
            or key in {'Dockerfile', 'manage.py', 'pyproject.toml', 'uv.lock'})


def verify_source(root, manifest):
    expected = {key.replace('\\', '/'): digest for key, digest in manifest.items()
                if selected(key) and '__pycache__' not in key and not key.endswith('.pyc')}
    current = {file.relative_to(root).as_posix(): file for file in root.rglob('*')
               if file.is_file() and selected(file.relative_to(root).as_posix())
               and '__pycache__' not in file.parts and file.suffix != '.pyc'}
    if set(expected) != set(current):
        raise RuntimeError('Deployable source membership differs from pinned manifest')
    for key, file in current.items():
        if hashlib.sha256(file.read_bytes()).hexdigest() != expected[key]:
            raise RuntimeError('Deployable source content differs: ' + key)
    return len(expected)


def verify_fixture(preview, network, database):
    network_id = network['Id']
    db_id = database['Id']
    link = database['NetworkSettings']['Networks'].get(preview['network'], {})
    if (network['Name'] != preview['network'] or not network['Internal']
            or not re.fullmatch(r'[0-9a-f]{64}', network_id)
            or database['Name'] != '/' + preview['database']
            or database['Image'] != preview['postgres_image_id']
            or not database['State']['Running']
            or database['HostConfig']['PortBindings']
            or set(database['NetworkSettings']['Networks']) != {preview['network']}
            or link.get('NetworkID') != network_id
            or 'qualification-db' not in link.get('Aliases', [])
            or db_id not in network.get('Containers', {})
            or network['Containers'][db_id]['Name'] != preview['database']):
        raise RuntimeError('Synthetic database/network fixture identity is unverified')
    return network_id, db_id


def verify_runtime(runtime, image, network_id, *, network_name=None, started=False):
    host = runtime['HostConfig']
    networks = runtime['NetworkSettings']['Networks']
    if (runtime['Image'] != image or runtime['Config']['User'] != 'agentledger'
            or runtime['State']['Running'] is not started
            or runtime['State']['Status'] != ('running' if started else 'created')
            or not host['ReadonlyRootfs'] or host['PortBindings']
            or host['PublishAllPorts'] or host['Privileged']
            or host['CapDrop'] != ['ALL'] or host.get('CapAdd')
            or 'no-new-privileges' not in (host['SecurityOpt'] or [])
            or host['Memory'] != 512 * 1024 * 1024 or host['PidsLimit'] != 128
            or host['Tmpfs'] != {'/tmp': 'rw,size=32m'}
            or host['NetworkMode'] != network_id
            or len(networks) != 1
            or (network_name is not None and set(networks) != {network_name})
            or next(iter(networks.values()))['NetworkID'] not in
               ({network_id} if started else {'', network_id})):
        raise RuntimeError('HTTP runtime constraints failed before start')
