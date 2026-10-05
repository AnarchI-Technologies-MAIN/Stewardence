"""Generate the first bundled schemas; local review artifact, never deployment."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'source/apps/integrations/semantics/schemas'
ROOT.mkdir(parents=True, exist_ok=True)
DIALECT = 'https://json-schema.org/draft/2020-12/schema'


def obj(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required,
            'additionalProperties': False}


def text(limit=200, **kw):
    return {'type': 'string', 'maxLength': limit, **kw}


UUID = text(36, format='uuid', pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
SHA = text(64, pattern=r'^[0-9a-f]{64}$')
TOKEN = text(80, pattern=r'^[a-z][a-z0-9_.-]{0,79}$')
UTC = text(27, format='date-time', pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$')
STATE = ['known', 'source_null', 'missing', 'unknown', 'unavailable', 'unsupported', 'redacted']
VALUE = {'oneOf': [obj({'type': {'const': 'text'}, 'data': text(200)}),
    obj({'type': {'const': 'boolean'}, 'data': {'type': 'boolean'}}),
    obj({'type': {'const': 'integer'}, 'data': {'type': 'integer', 'minimum': -9007199254740991,
         'maximum': 9007199254740991}, 'unit': {'enum': ['1', 'count']}}),
    obj({'type': {'const': 'decimal'}, 'data': text(80, pattern=r'^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$'),
         'unit': {'enum': ['1', 'h']}, 'source_scale': {'type': 'integer', 'minimum': 0, 'maximum': 18}}),
    obj({'type': {'const': 'money'}, 'data': text(80, pattern=r'^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$'),
         'currency': {'enum': ['USD', 'EUR', 'GBP', 'CAD']}, 'currency_registry': {'const': 'stewardence.currency-subset.v1'},
         'source_scale': {'type': 'integer', 'minimum': 0, 'maximum': 18}})]}
ASSERTION = obj({'concept_id': TOKEN, 'concept_version': {'const': 1},
    'evidence_kind': {'enum': ['declared', 'unknown']},
    'value_state': {'enum': STATE}, 'value': VALUE, 'reason': TOKEN,
    'source_pointer': text(512, pattern=r'^(/([^~/]|~[01])*)*$(?![\s\S])'),
    'effective_time': obj({'source_text': {'type': ['string', 'null'], 'maxLength': 80},
                           'utc': {'anyOf': [UTC, {'type': 'null'}]}})},
    ['concept_id', 'concept_version', 'evidence_kind', 'value_state', 'source_pointer', 'effective_time'])
ASSERTION['allOf'] = [
    {'if': {'properties': {'value_state': {'const': 'known'}}}, 'then': {'required': ['value'], 'not': {'required': ['reason']}}},
    {'if': {'properties': {'value_state': {'const': 'source_null'}}}, 'then': {'properties': {'value': {'type': 'null'}}, 'required': ['value', 'reason']}},
    {'if': {'properties': {'value_state': {'enum': STATE[2:]}}}, 'then': {'not': {'required': ['value']}, 'required': ['reason']}}
]
# source_null needs an explicit null value; known values are tagged objects.
ASSERTION['properties']['value'] = {'anyOf': [VALUE, {'type': 'null'}]}
ASSERTION['allOf'][0]['then']['properties'] = {'value': VALUE}
PAYLOAD = obj({'schema_id': {'const': 'urn:stewardence:evidence:read:v1'}, 'schema_digest': SHA,
    'semantic_profile_id': {'const': 'stewardence.entity-descriptor.v1'}, 'semantic_profile_digest': SHA,
    'organization_id': UUID,
    'source': obj({'provider': {'enum': ['quickbooks_online', 'microsoft_365']},
        'environment': {'enum': ['sandbox', 'owner_preview']}, 'api_version': text(40, minLength=1),
        'account_id': text(128, minLength=1), 'artifact_receipt_id': UUID, 'raw_bytes_sha256': SHA,
        'captured_at': UTC, 'media_type': {'const': 'application/json'}}),
    'adapter': obj({'id': TOKEN, 'version': text(30, pattern=r'^[0-9]+\.[0-9]+\.[0-9]+$'),
        'artifact_digest': SHA, 'mapping_digest': SHA, 'configuration_digest': SHA}),
    'subject': obj({'namespace': TOKEN, 'entity_id': text(128, minLength=1),
        'kind': {'enum': ['accounting_company', 'directory_tenant']}}),
    'assertions': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'items': {'$ref': 'urn:stewardence:evidence:assertion:v1'}},
    'coverage': obj({'state': {'enum': ['partial', 'unknown']},
        'requested': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'uniqueItems': True, 'items': TOKEN},
        'covered': {'type': 'array', 'maxItems': 64, 'uniqueItems': True, 'items': TOKEN},
        'gaps': {'type': 'array', 'minItems': 1, 'maxItems': 64, 'uniqueItems': True, 'items': TOKEN}}),
    'supersedes': {'anyOf': [SHA, {'type': 'null'}]}})
PAYLOAD.update({'$schema': DIALECT, '$id': 'urn:stewardence:evidence:read:v1'})
ENVELOPE = obj({'algorithm': {'const': 'sha256-rfc8785'}, 'payload_sha256': SHA,
                'payload': {'$ref': 'urn:stewardence:evidence:read:v1'}})
ENVELOPE.update({'$schema': DIALECT, '$id': 'urn:stewardence:evidence:read-envelope:v1'})
ASSERTION.update({'$schema': DIALECT, '$id': 'urn:stewardence:evidence:assertion:v1'})
PROFILE = {'id': 'stewardence.entity-descriptor.v1', 'version': 1,
    'concepts': {
        'entity.provider_id': {'version': 1, 'type': 'text', 'definition': 'Provider-namespaced object identifier, not legal or cross-provider identity.'},
        'entity.display_name': {'version': 1, 'type': 'text', 'definition': 'Provider-declared display name; no legal-name or uniqueness assertion.'}},
    'currency_registry': {'id': 'stewardence.currency-subset.v1', 'codes': ['USD', 'EUR', 'GBP', 'CAD'],
        'note': 'Explicit subset of ISO 4217 alphabetic identifiers; no minor-unit or conversion rule implied.'},
    'unit_registry': {'id': 'stewardence.units-subset.v1', 'units': {'1': 'dimensionless', 'h': 'hour', 'count': 'count'}}}
for name, data in [('assertion-v1.json', ASSERTION), ('read-payload-v1.json', PAYLOAD),
                   ('read-envelope-v1.json', ENVELOPE), ('entity-profile-v1.json', PROFILE)]:
    path = ROOT / name
    if path.exists():
        raise RuntimeError('Do not overwrite an existing versioned schema')
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('Created four local semantic-contract artifacts')
