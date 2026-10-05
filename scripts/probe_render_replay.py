"""Synthetic replay probe, run inside an isolated qualified renderer image."""
import hashlib,json,time
from pathlib import Path
from tests.test_renderer import valid_payload
from renderer.render import render_pdf
payload=valid_payload()
first=render_pdf(payload,output_directory=Path('/tmp/replay-first'))
time.sleep(1.1)
second=render_pdf(payload,output_directory=Path('/tmp/replay-second'))
print(json.dumps({'synthetic_only':True,'byte_identical':first==second,
 'first_sha256':hashlib.sha256(first).hexdigest(),'second_sha256':hashlib.sha256(second).hexdigest(),
 'first_bytes':len(first),'second_bytes':len(second)}))
