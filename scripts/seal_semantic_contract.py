"""Seal a NEW local contract candidate. Hashes are integrity, not approval."""
import hashlib
import json
from pathlib import Path
import sys

import rfc8785

ROOT = Path(__file__).resolve().parents[1] / 'source/apps/integrations/semantics'
existing = ROOT / 'registry-v1.json'
if existing.exists() and json.loads(existing.read_bytes()).get('status') != 'undeployed_candidate':
    raise RuntimeError('An adopted contract cannot be resealed under its old identity')
sys.path.insert(0, str(ROOT.parents[2]))
from apps.integrations.semantics.contracts import DEPENDENCIES, REQUIRED_FILES
files = {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
         for path in [ROOT / relative for relative in sorted(REQUIRED_FILES)]}
adapters = [
    {'id': 'quickbooks.sandbox.company-descriptor', 'version': '1.0.0', 'provider': 'quickbooks_online',
     'environment': 'sandbox', 'api_version': 'v3', 'namespace': 'quickbooks.company_info',
     'subject_kind': 'accounting_company', 'pointers': {'entity.provider_id': '/CompanyInfo/Id', 'entity.display_name': '/CompanyInfo/CompanyName'}},
    {'id': 'microsoft.organization-descriptor', 'version': '1.0.0', 'provider': 'microsoft_365',
     'environment': 'owner_preview', 'api_version': 'graph.v1.0', 'namespace': 'microsoft.directory',
     'subject_kind': 'directory_tenant', 'pointers': {'entity.provider_id': '/value/0/id', 'entity.display_name': '/value/0/displayName'}},
]
for adapter in adapters:
    adapter['mapping_digest'] = hashlib.sha256(rfc8785.dumps(adapter)).hexdigest()
    adapter['configuration'] = {}
    adapter['configuration_digest'] = hashlib.sha256(rfc8785.dumps({})).hexdigest()
artifact = {'files': files, 'adapters': adapters, 'dependencies': DEPENDENCIES}
manifest = {'schema': 'stewardence.semantic-registry.v1', 'status': 'undeployed_candidate', 'writes_enabled': False,
            'admission_enabled': False, 'files': files,
            'dependencies': DEPENDENCIES,
            'artifact_digest': hashlib.sha256(rfc8785.dumps(artifact)).hexdigest(), 'adapters': adapters}
(ROOT / 'registry-v1.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
print('Sealed local candidate; no signature, admission, activation or release approval implied')
