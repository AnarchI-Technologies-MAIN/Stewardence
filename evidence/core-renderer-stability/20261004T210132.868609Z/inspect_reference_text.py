import json
from pathlib import Path
import subprocess
from pypdf import PdfReader

root = Path('/qualification-evidence')
pdf = root/'synthetic-pack.pdf'
results = {}
payload = json.loads((root/'synthetic-payload.json').read_text())
links = payload['review_pack']['selected_decisions'][0]['payload']['links']
for option in ['-raw', '-layout']:
    text = subprocess.run(['pdftotext', option, str(pdf), '-'], check=True,
                          capture_output=True).stdout.decode()
    (root/(option[1:]+'-text.txt')).write_text(text)
    results[option] = {marker: marker in ''.join(text.split())
                      for marker in ['stability-ref-0','stability-ref-9']}
    results[option]['all_exact_reference_text'] = all(link in ''.join(text.split()) for link in links)
text = '\n'.join(page.extract_text() for page in PdfReader(pdf).pages)
(root/'pypdf-text.txt').write_text(text)
compact = ''.join(text.split())
results['pypdf'] = {'all_exact_reference_text': all(
    link in compact for link in links), 'missing_indices': [index for index,link in enumerate(links) if link not in compact]}
(root/'text-extraction-comparison.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results))
