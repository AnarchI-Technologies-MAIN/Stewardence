"""Stage owner-preview credentials; never change running application configuration."""

import base64
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import date
from uuid import UUID
import warnings


ROOT = Path('/etc/stewardence')
DESTINATION = ROOT / 'provider_preview'
COMPOSE = Path('/home/anarchi/stewardence_migration/digitalocean/compose.json')
CADDY = Path('/etc/caddy/Caddyfile')
MICROSOFT_CLIENT = 'd6051326-8d93-4abf-b544-5bb2e9eb6e2f'
MICROSOFT_TENANT = '9739bc34-9cd9-4775-84f4-681531b8efcf'
MICROSOFT_EXPIRY = '2027-04-01'
EXPECTED_IMAGE = 'stewardence-app:4deac945-qbo5-reports'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True,
                            timeout=30, check=False)
    require(result.returncode == 0, 'Container preflight failed; details suppressed.')
    return result.stdout


def protected_file(path):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), 'Expected a regular configuration file.')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight():
    web = json.loads(docker('inspect', 'stewardence-web'))[0]
    expected = json.loads(docker('image', 'inspect', EXPECTED_IMAGE))[0]['Id']
    require(web['State']['Running'] and web['Image'] == expected,
            'Unexpected web image or state. Nothing changed.')
    bindings = web['HostConfig']['PortBindings'].get('8000/tcp', [])
    require(len(bindings) == 1 and bindings[0]['HostIp'] == '127.0.0.1'
            and bindings[0]['HostPort'] == '8000', 'Web binding differs.')
    env = dict(item.split('=', 1) for item in web['Config']['Env'])
    require(env.get('AUTOMATION_ENABLED') == '0'
            and env.get('QUICKBOOKS_SANDBOX_ENABLED') == '1',
            'Unexpected existing feature flags.')
    for name in ('MICROSOFT_PREVIEW_ENABLED', 'XERO_PREVIEW_ENABLED'):
        require(env.get(name, '0') == '0', 'Provider preview is already enabled.')
    owner = env.get('QUICKBOOKS_SANDBOX_USER_IDS', '').strip()
    require(str(UUID(owner)) == owner, 'Expected exactly one existing preview owner.')
    require('stewardence-worker' not in docker('ps', '--format', '{{.Names}}').splitlines(),
            'Expected worker to remain stopped.')
    db = json.loads(docker('inspect', 'stewardence-db'))[0]
    require(db['State']['Running'] and not db['HostConfig'].get('PortBindings'),
            'Database isolation differs.')
    return (web['Id'], web['Image'], owner, protected_file(COMPOSE),
            protected_file(CADDY), hashlib.sha256(
                json.dumps(web['Config'], sort_keys=True).encode()).hexdigest())


def validate_secret(value):
    require(isinstance(value, str) and re.fullmatch(r'[\x21-\x7e]{16,4096}', value),
            'Credential format rejected. No values printed.')
    return value


def confirmed_secret(label):
    first = validate_secret(getpass.getpass(label + ' value (hidden): '))
    second = getpass.getpass('Repeat ' + label + ' value (hidden): ')
    require(secrets.compare_digest(first, second),
            'The two secret entries did not match. Nothing installed.')
    return first


def documents(owner, microsoft_secret, xero_client, xero_secret):
    require(str(UUID(owner)) == owner, 'Invalid preview owner.')
    require(date.today() < date.fromisoformat(MICROSOFT_EXPIRY),
            'Recorded Microsoft credential has expired.')
    require(isinstance(xero_client, str)
            and re.fullmatch(r'[A-Za-z0-9_-]{16,128}', xero_client),
            'Invalid Xero client ID format.')
    microsoft_secret = validate_secret(microsoft_secret)
    xero_secret = validate_secret(xero_secret)
    common = {'schema': 'stewardence.provider-preview-credentials.v1',
              'enabled': False, 'owner_user_id': owner}
    return {
        'microsoft.json': {
            **common, 'provider': 'microsoft', 'client_id': MICROSOFT_CLIENT,
            'client_secret': microsoft_secret, 'tenant_id': MICROSOFT_TENANT,
            'client_secret_expires_on': MICROSOFT_EXPIRY,
            'redirect_uri': 'https://www.stewardence.com/integrations/microsoft/callback/',
            'scopes': ['openid', 'profile', 'offline_access', 'User.Read', 'Directory.Read.All'],
            'mode': 'owner_tenant_preview',
        },
        'xero.json': {
            **common, 'provider': 'xero', 'client_id': xero_client,
            'client_secret': xero_secret,
            'redirect_uri': 'https://www.stewardence.com/integrations/xero/callback/',
            'scopes': ['offline_access', 'accounting.settings.read',
                       'accounting.reports.profitandloss.read'],
            'require_demo_company': True,
        },
        'keyring.json': {
            'schema': 'stewardence.provider-preview-keyring.v1',
            'active_key_id': 'preview-v1',
            'keys': {'preview-v1': base64.b64encode(secrets.token_bytes(32)).decode()},
        },
    }


def write_documents(folder, payloads, uid=10001, gid=10001):
    for name, payload in payloads.items():
        require(name in ('microsoft.json', 'xero.json', 'keyring.json'),
                'Unexpected credential filename.')
        path = folder / name
        with path.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), uid, gid)
            stream.write(json.dumps(payload, sort_keys=True).encode())
            stream.flush()
            os.fsync(stream.fileno())
        require(json.loads(path.read_bytes()) == payload, 'Credential readback failed.')
        info = path.lstat()
        require(stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == uid and info.st_gid == gid,
                'Credential permissions failed.')


def main():
    require(os.geteuid() == 0 and sys.stdin.isatty(),
            'Run with sudo -n python3 in an interactive SSH terminal.')
    warnings.simplefilter('error', getpass.GetPassWarning)
    os.umask(0o077)
    root_info = ROOT.lstat()
    require(stat.S_ISDIR(root_info.st_mode) and root_info.st_uid == 0
            and not root_info.st_mode & 0o022, 'Credential parent is not protected.')
    lock_fd = os.open(ROOT / '.provider-preview.lock',
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not os.path.lexists(DESTINATION),
                'Provider credential directory already exists; nothing overwritten.')
        baseline = preflight()
        print('PRIVATE_RUNTIME_PREFLIGHT=PASS', flush=True)
        print('Inputs stay on this server. Paste credential VALUES, not secret IDs.', flush=True)
        microsoft = confirmed_secret('Microsoft client secret')
        xero_client = getpass.getpass('Xero client ID (hidden): ').strip()
        xero = confirmed_secret('Xero client secret')
        payloads = documents(baseline[2], microsoft, xero_client, xero)
        temporary = Path(tempfile.mkdtemp(prefix='.provider-preview-', dir=ROOT))
        try:
            write_documents(temporary, payloads)
            require(preflight() == baseline, 'Runtime changed during preparation.')
            require(not os.path.lexists(DESTINATION), 'Credential destination now exists.')
            os.rename(temporary, DESTINATION)
            directory_fd = os.open(ROOT, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        print('MICROSOFT_CREDENTIALS_STAGED=PASS')
        print('XERO_CREDENTIALS_STAGED=PASS')
        print('PRIVATE_FILE_PERMISSIONS=PASS')
        print('EXISTING_PREVIEW_OWNER_BINDING=PASS')
        print('APPLICATION_MOUNTS=NOT_CHANGED')
        print('MICROSOFT_AND_XERO=STAGED_DISABLED')
        print('LIVE_PROVIDER_AUTHENTICATION=NOT_TESTED')
        print('AUTOMATION_PURCHASES=DISABLED')
        print('WORKER=NOT_STARTED')
        print('DATABASE_WRITES=NONE_REQUESTED')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print('PROVIDER_CREDENTIAL_SETUP=STOPPED: ' + str(error))
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print('PROVIDER_CREDENTIAL_SETUP=CANCELLED')
        sys.exit(1)
    except Exception:
        print('PROVIDER_CREDENTIAL_SETUP=FAILED; details suppressed to protect credentials.')
        sys.exit(1)
