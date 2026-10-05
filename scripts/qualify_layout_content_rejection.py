"""Actual synthetic PDF counterexamples plus failed-receipt controls."""
import copy
import io
import json
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from playwright.sync_api import sync_playwright
from report_layout_content import verify_content, verify_receipt

root = Path('/qa')
baseline = PdfReader(root/'long-input.pdf')
rejections = []


def must_reject(label, callback):
    try:
        callback()
    except RuntimeError:
        rejections.append(label)
        return
    raise RuntimeError('Counterexample falsely accepted: ' + label)


writer = PdfWriter()
writer.append(baseline)
writer.add_blank_page(width=595, height=842)
buffer = io.BytesIO()
writer.write(buffer)
must_reject('actual_blank_page', lambda: verify_content(PdfReader(buffer), 'long-input'))
with sync_playwright() as tools:
    browser = tools.chromium.launch(headless=True, chromium_sandbox=False)
    page = browser.new_page(java_script_enabled=False)
    page.set_content('<p>Page 6 of 6</p>')
    footer = page.pdf()
    writer = PdfWriter()
    writer.append(baseline)
    writer.append(PdfReader(io.BytesIO(footer)))
    buffer = io.BytesIO()
    writer.write(buffer)
    must_reject('actual_footer_only_page', lambda: verify_content(PdfReader(buffer), 'long-input'))
    page.set_content('<h2>AI and software inventory</h2><p>Monthly cost</p>'
                     '<h2>Overall risk overview</h2><h2>Individual tool risk</h2>'
                     '<p>Synthetic table tool 001 (Declared)</p>')
    poisoned = page.pdf()
    must_reject('actual_label_only_in_risk', lambda: verify_content(PdfReader(io.BytesIO(poisoned)), 'long-table'))
    browser.close()
receipt = json.loads((root/'layout-summary.json').read_bytes())
verify_receipt(receipt)
for field in ['nonempty_pages', 'inventory_section_complete']:
    bad = copy.deepcopy(receipt)
    bad['content_checks']['long-input'][field] = False
    must_reject('receipt_false_' + field, lambda: verify_receipt(bad))
bad = copy.deepcopy(receipt)
del bad['content_checks']['multi-tool']
must_reject('receipt_missing_specimen', lambda: verify_receipt(bad))
print(json.dumps({'rejections': rejections, 'healthy_receipt_passed': True,
                  'scope': 'Actual synthetic PDF controls; no customer or production data.'}))
