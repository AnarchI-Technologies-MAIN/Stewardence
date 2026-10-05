"""Print-width DOM geometry plus independent PDF content completeness."""
import json
import os
from pathlib import Path
from pypdf import PdfReader
from playwright.sync_api import sync_playwright
from renderer.template import render_report_html

payload = json.loads(Path('/qa/long-input.json').read_bytes())
with sync_playwright() as browser_tools:
    browser = browser_tools.chromium.launch(headless=True,chromium_sandbox=False)
    context = browser.new_context(java_script_enabled=False,service_workers='block',
                                  viewport={'width':688,'height':1123})
    context.route('**/*',lambda route:route.abort())
    page = context.new_page()
    page.emulate_media(media='print')
    page.set_content(render_report_html(payload))
    geometry = page.evaluate('''() => ({viewport:innerWidth,
      document_width:document.documentElement.scrollWidth,
      table_columns:Array.from(document.querySelector('table').querySelectorAll('th'))
        .map(cell=>cell.getBoundingClientRect().width)})''')
    browser.close()
within_bounds = geometry['document_width'] <= geometry['viewport']+1 and min(geometry['table_columns']) >= 90
if os.getenv('EXPECT_LAYOUT_REJECTION') == '1':
    if within_bounds:
        raise RuntimeError('Predecessor unexpectedly passed the differential layout control')
    print(json.dumps({'predecessor_rejection_observed':True,'geometry':geometry,
                      'scope':'Actual Chromium print-width DOM control; not physical print pagination.'}))
else:
    if not within_bounds:
        raise RuntimeError('Long-input layout exceeds print width or squeezes columns')
    content_checks = {}
    for specimen in ['long-input','multi-tool','long-table']:
        reader = PdfReader('/qa/'+specimen+'.pdf')
        text = '\n'.join(page.extract_text() for page in reader.pages)
        if specimen == 'long-table':
            for number in range(1,81):
                if 'Synthetic table tool '+format(number,'03d') not in text:
                    raise RuntimeError('Long table lost a synthetic row')
            if text.count('Monthly cost') < 2:
                raise RuntimeError('Long table did not repeat its headers')
        if specimen == 'multi-tool':
            for number in range(1,9):
                if 'Synthetic tool '+str(number) not in text:
                    raise RuntimeError('Multi-tool report lost a synthetic tool')
        if specimen == 'long-input' and 'Müller & García' not in text:
            raise RuntimeError('Latin customer-name glyphs were lost')
        content_checks[specimen] = {'pages':len(reader.pages),'nonempty_pages':all(page.extract_text().strip() for page in reader.pages)}
    receipt = {'qualification_passed':True,'geometry':geometry,'content_checks':content_checks,
        'scope':'Synthetic renderer layout only; not source-derived assessment, international glyph coverage or production service proof.'}
    Path('/qa/layout-summary.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))
