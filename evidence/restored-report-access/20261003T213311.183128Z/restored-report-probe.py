"""Run inside the disposable candidate container, against restored data only.

Receives length-framed restored PDFs over stdin. Does not print customer content,
identifiers, credentials or underlying exceptions. No listening server/network
provider calls. Django's real request middleware/views use agentledger_app.
"""
import hashlib
import json
import logging
import os
import struct
import sys
from pathlib import Path
from uuid import uuid4

import django

django.setup()
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import Client, override_settings
from django.urls import reverse
from apps.billing.models import BillingCustomer, Subscription
from apps.organizations.models import Organization, OrganizationMember
from apps.reports.models import ReportArtifact

for name in ['django.request', 'agentledger.tenancy.middleware']:
    logging.getLogger(name).disabled = True


def exact_read(size):
    if not 0 <= size <= 16*1048576:
        raise RuntimeError('Restore frame size outside bound')
    data = sys.stdin.buffer.read(size)
    if len(data) != size:
        raise RuntimeError('Restore frame truncated')
    return data


def main():
    with connections['default'].cursor() as cursor:
        cursor.execute("SELECT current_user,current_setting('transaction_isolation')")
        role, isolation = cursor.fetchone()
    if role != 'agentledger_app' or isolation != 'read committed':
        raise RuntimeError('Restored application authority identity invalid')
    manifest_length = struct.unpack('!I', exact_read(4))[0]
    manifest = json.loads(exact_read(manifest_length))
    root = Path('/recovered-reports')
    for item in manifest:
        size = struct.unpack('!I', exact_read(4))[0]
        data = exact_read(size)
        if size != item['size_bytes'] or hashlib.sha256(data).hexdigest() != item['sha256'] or not data.startswith(b'%PDF-'):
            raise RuntimeError('Restored object does not match immutable manifest')
        destination = root / item['object_key']
        if root not in destination.resolve().parents:
            raise RuntimeError('Unsafe private restore path')
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        fd = os.open(destination, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    if sys.stdin.buffer.read(1):
        raise RuntimeError('Unexpected restore frame tail')
    # Fresh synthetic paid tenant exists only in this clone. It exercises real
    # middleware + forced RLS while guessing actual restored report UUIDs.
    user_model = get_user_model()
    denied_user = user_model.objects.db_manager('owner_runtime').create_user(str(uuid4())+'@restore.example.invalid')
    denied_org = Organization.objects.using('owner_runtime').create(name='Isolated restore negative tenant')
    OrganizationMember.objects.using('owner_runtime').create(user=denied_user, organization=denied_org, role='owner')
    customer = BillingCustomer.objects.using('owner_runtime').create(user=denied_user)
    Subscription.objects.using('owner_runtime').create(billing_customer=customer, organization=denied_org,
                                                     status='active', portfolio='core', current_price_cents=9900)
    cross = Client()
    cross.force_login(denied_user)
    session = cross.session; session['active_organization_id'] = str(denied_org.id); session.save()
    counts = {'authorized_downloads': 0, 'anonymous_denials': 0, 'cross_tenant_denials': 0,
              'corrupt_object_denials': 0, 'missing_object_denials': 0, 'repaired_copy_downloads': 0,
              'download_attempts_with_current_clone_entitlement': 0}
    counts['unentitled_clone_denials'] = 0
    counts['isolated_entitlement_mutations'] = 0
    anonymous = Client()
    with override_settings(DEBUG=False, ALLOWED_HOSTS=['testserver'], REPORTS_STORAGE_BACKEND='local',
                           REPORTS_LOCAL_STORAGE_ROOT=root, CORE_WORKFLOWS_ENABLED=False,
                           QUICKBOOKS_PREVIEW_ENABLED=False, MICROSOFT_PREVIEW_ENABLED=False,
                           XERO_PREVIEW_ENABLED=False, AUTOMATION_ENABLED=False):
        for item in manifest:
            artifact = ReportArtifact.objects.using('owner_runtime').get(pk=item['id'])
            if any(str(getattr(artifact, name)) != str(item[name]) for name in
                   ['id','organization_id','report_id','assessment_snapshot_id','object_key','sha256','size_bytes','content_type']):
                raise RuntimeError('Restored database artifact binding changed')
            owner = OrganizationMember.objects.using('owner_runtime').filter(organization_id=item['organization_id'], role='owner').get()
            entitled = Subscription.objects.using('owner_runtime').filter(organization_id=item['organization_id'],
                billing_customer__user_id=owner.user_id, status__in=['active','canceling']).exists()
            viewer = Client()
            viewer.force_login(user_model.objects.using('owner_runtime').get(pk=owner.user_id))
            session = viewer.session; session['active_organization_id'] = item['organization_id']; session.save()
            path = reverse('reports:download', args=[item['report_id']])
            if not entitled:
                denied = viewer.get(path)
                if denied.status_code != 302 or denied.get('Content-Type') == 'application/pdf':
                    raise RuntimeError('Unentitled snapshot owner was not denied')
                counts['unentitled_clone_denials'] += 1
                fixture_customer, _ = BillingCustomer.objects.using('owner_runtime').get_or_create(user_id=owner.user_id)
                Subscription.objects.using('owner_runtime').update_or_create(billing_customer=fixture_customer,
                    defaults={'organization_id':item['organization_id'], 'status':'active', 'portfolio':'core', 'current_price_cents':9900})
                counts['isolated_entitlement_mutations'] += 1
                session = viewer.session; session['active_organization_id'] = item['organization_id']; session.save()
            else:
                counts['download_attempts_with_current_clone_entitlement'] += 1
            response = viewer.get(path)
            if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != item['sha256']:
                raise RuntimeError('Authorized restored-object download failed')
            if response.get('Cache-Control') != 'private, no-store' or response.get('Content-Type') != 'application/pdf':
                raise RuntimeError('Authorized private response policy invalid')
            counts['authorized_downloads'] += 1
            response = anonymous.get(path)
            if response.status_code not in [302,401,403] or response.get('Content-Type') == 'application/pdf':
                raise RuntimeError('Anonymous restored-object access admitted')
            counts['anonymous_denials'] += 1
            response = cross.get(path)
            if response.status_code != 404 or response.get('Content-Type') == 'application/pdf':
                raise RuntimeError('Cross-tenant restored-object access admitted')
            counts['cross_tenant_denials'] += 1
            file = root/item['object_key']
            original = file.read_bytes()
            file.write_bytes(b'%PDF-corrupt-isolated-restore-fixture')
            response = viewer.get(path)
            if response.status_code != 503 or response.get('Content-Type') == 'application/pdf' or response.get('Content-Disposition') or response.get('Cache-Control') != 'private, no-store':
                raise RuntimeError('Corrupt restored object was served')
            counts['corrupt_object_denials'] += 1
            file.unlink()
            response = viewer.get(path)
            if response.status_code != 503 or response.get('Content-Type') == 'application/pdf' or response.get('Content-Disposition') or response.get('Cache-Control') != 'private, no-store':
                raise RuntimeError('Missing restored object was served')
            counts['missing_object_denials'] += 1
            fd = os.open(file, os.O_CREAT|os.O_EXCL|os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(original); stream.flush(); os.fsync(stream.fileno())
            response = viewer.get(path)
            if response.status_code != 200 or hashlib.sha256(response.content).hexdigest() != item['sha256']:
                raise RuntimeError('Restored copy did not recover without metadata rewrite')
            counts['repaired_copy_downloads'] += 1
    print(json.dumps({'qualified': True, 'application_role': role, 'transaction_isolation': isolation,
                      'objects': len(manifest), 'counts': counts, 'listening_server_started': False,
                      'production_writes': False, 'provider_requests': False,
                      'entitlement_evidence': 'Clone entitlements can be changed by explicitly synthetic fixtures during this probe. Current-clone counts are not original-snapshot or live entitlement facts.',
                      'limits': 'In-process Django request pipeline with actual app role, restored existing rows/objects, explicitly synthetic clone entitlements where absent, and isolated negative tenant; no live entitlement, production HTTP or cutover proof.'}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'qualified': False, 'failure_type': type(error).__name__,
                          'safe_reason': str(error) if type(error) is RuntimeError else 'Underlying diagnostics suppressed'}))
        raise SystemExit(1) from None
