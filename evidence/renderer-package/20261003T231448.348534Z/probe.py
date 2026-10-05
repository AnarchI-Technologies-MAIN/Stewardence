"""Execute within a credential-free renderer image using synthetic inputs only."""
import hashlib
import json
import os
import time
from io import BytesIO
from pathlib import Path
from pypdf import PdfReader
from renderer.render import render_pdf
from renderer.template import BRAND_LOGO_PATH

receipt_path = Path('/qa/renderer-package-summary.json')
pdf_path = Path('/qa/packaged-renderer.pdf')
# A failed rerun must never leave an earlier passing receipt or PDF behind.
receipt_path.unlink(missing_ok=True)
pdf_path.unlink(missing_ok=True)
input_bytes = Path('/qa/synthetic-render-payload.json').read_bytes()
payload = json.loads(input_bytes)
result = payload['roi']['result']
if (result['monthly_value'] is not None or result['monthly_net_value'] is not None
        or result['roi_percent'] is not None or result['monthly_total_cost'] != '110.00'
        or result['roi_unavailable_reason'] != 'Required assumptions are unknown'):
    raise RuntimeError('This qualification requires the exact unknown-ROI fixture')
if os.getuid() != 10001 or BRAND_LOGO_PATH.name != 'reports.svg':
    raise RuntimeError('Renderer package identity or asset invalid')
first = render_pdf(payload)
time.sleep(1.1)
second = render_pdf(payload)
if first != second:
    raise RuntimeError('Packaged renderer bytes are not repeatable')
reader = PdfReader(BytesIO(first))
text = '\n'.join(page.extract_text() for page in reader.pages)
roi_text = reader.pages[2].extract_text() if len(reader.pages) == 4 else ''
required_rows = [
    'Monthly value Unknown Monthly total cost $110.00',
    'Monthly net value Unknown ROI Not available: Required assumptions are unknown',
]
prefix = 'Results are Calculated from the captured assumptions.'
roi_body = roi_text.partition(prefix)[2].partition('Arithmetic')[0]
if ' '.join(roi_body.split()) != ' '.join(required_rows) or '$None' in text:
    raise RuntimeError('Packaged renderer lost unknown/value semantics')
final_lines = [line.strip() for line in reader.pages[-1].extract_text().splitlines() if line.strip()]
footer = 'Page ' + str(len(reader.pages)) + ' of ' + str(len(reader.pages))
final_body = [line for line in final_lines if line != footer]
if not final_body or final_body[0] != 'Assessment and report metadata':
    raise RuntimeError('Technical appendix is not on its deliberate page')
pdf_path.write_bytes(first)
receipt = {'qualification_passed':True,'uid':os.getuid(),'actual_chromium':True,
           'repeat_bytes_equal':True,'pages':len(reader.pages),
           'pdf_sha256':hashlib.sha256(first).hexdigest(),
           'input_sha256':hashlib.sha256(input_bytes).hexdigest(),
           'probe_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'exact_roi_table_rows_verified':True,
           'decorative_asset_sha256':hashlib.sha256(BRAND_LOGO_PATH.read_bytes()).hexdigest(),
           'synthetic_only':True,'provider_requests':False,'production_touched':False,
           'limits':'Direct packaged renderer execution without HTTP listener; not provider admission or production service qualification.'}
receipt_path.write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt))
