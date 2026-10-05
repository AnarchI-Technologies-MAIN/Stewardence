"""Synthetic rendering probe for an isolated immutable qualification image."""
import hashlib
import json
from pathlib import Path
import tempfile
import time

from renderer.render import render_pdf
from tests.test_renderer import valid_payload
from tests.renderer_qualification_diagnostics import resource_snapshot


def main():
    payload = valid_payload()
    facts = {'before': resource_snapshot(), 'renders': [],
             'synthetic_payload_only': True, 'timeout_seconds': 60}
    with tempfile.TemporaryDirectory(prefix='renderer-reaping-') as directory:
        for index in range(4):
            started = time.monotonic()
            pdf = render_pdf(payload, output_directory=Path(directory))
            facts['renders'].append({'index': index,
                'elapsed': time.monotonic()-started,
                'sha256': hashlib.sha256(pdf).hexdigest(),
                'resources': resource_snapshot()})
    facts['after'] = resource_snapshot()
    Path('/qualification-evidence/reaping.json').write_text(json.dumps(facts, indent=2))
    print(json.dumps({'render_count': len(facts['renders']),
                      'synthetic_payload_only': True}))


if __name__ == '__main__':
    main()
