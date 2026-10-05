"""Compare Python RFC8785 with ECMAScript in the restricted v1 wire domain."""
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'source'))
from apps.integrations.semantics.contracts import canonical_bytes

# This ECMAScript oracle covers the v1 domain only: safe integers, booleans,
# null, strings, arrays and objects. It is not a general floating-point JCS SDK.
JS = r'''
const fs = require('node:fs');
function canonical(value) {
  if (value === null || typeof value === 'boolean' || typeof value === 'string')
    return JSON.stringify(value);
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new Error('unsafe numeric oracle input');
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (typeof value === 'object') return '{' + Object.keys(value).sort().map(
    key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
  throw new Error('unsupported oracle input');
}
const vectors = JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify({node:process.version,
  canonical: vectors.map(value => Buffer.from(canonical(value),'utf8').toString('hex'))}));
'''
VECTORS = [
    {'\ue000': 'private', '\U0001f600': 'emoji', 'a': ['e\u0301', '\u00e9']},
    {'safe_max': 9007199254740991, 'safe_min': -9007199254740991, 'zero': 0,
     'money': '9007199254740993.0001', 'source_scale': 4},
    {'false': False, 'null': None, 'empty': '', 'control': '\n\t\r\b\f\x00',
     'quote': '\\"', 'nested': [{'z': 2, 'a': 1}, ['b', 'a']]},
    {'\r': 'CR', '\u0080': 'control', 'ö': 'latin', '€': 'euro', 'דּ': 'hebrew',
     '\U0001f600': 'emoji', '1': 'digit'},
]


def main():
    reference = json.loads(subprocess.check_output(['node', '-e', JS],
        input=json.dumps(VECTORS, ensure_ascii=False).encode('utf-8'), timeout=30))
    python = [canonical_bytes(value).hex() for value in VECTORS]
    if python != reference['canonical']:
        raise RuntimeError('Python/ECMAScript canonicalization mismatch')
    record = {'verified_at': datetime.now(UTC).isoformat(), 'python': sys.version.split()[0],
              'node': reference['node'], 'vectors': len(VECTORS), 'matched': True,
              'domain': 'v1 safe integers/strings/booleans/null/arrays/objects; no float claim',
              'vector_digests': [hashlib.sha256(bytes.fromhex(value)).hexdigest() for value in python],
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (ROOT / 'evidence/semantic-jcs-cross-language.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
