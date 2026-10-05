"""Mock-only negative controls for exact-field and stale-receipt rejection."""
import json
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT/'scripts/renderer_package_probe.py'
SOURCE = PROBE.read_text(encoding='utf-8')
PAYLOAD = ROOT/'evidence/20261003T224123.550152Z/synthetic-render-payload.json'
GOOD = ['Monthly value Unknown Monthly total cost $110.00',
        'Monthly net value Unknown ROI Not available: Required assumptions are unknown']


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix='stewardence-renderer-probe-') as directory:
        qa = Path(directory)
        (qa/'synthetic-render-payload.json').write_bytes(PAYLOAD.read_bytes())
        asset = qa/'reports.svg'
        asset.write_bytes(b'<svg/>')
        render_module = types.ModuleType('renderer.render')
        render_module.render_pdf = lambda payload: b'mocked-pdf-only'
        template_module = types.ModuleType('renderer.template')
        template_module.BRAND_LOGO_PATH = asset

        def run(lines):
            pdf_module = types.ModuleType('pypdf')
            pdf_module.PdfReader = lambda stream: types.SimpleNamespace(pages=[
                types.SimpleNamespace(extract_text=lambda: 'Cover'),
                types.SimpleNamespace(extract_text=lambda: 'Policy'),
                types.SimpleNamespace(extract_text=lambda: 'Return on investment\nResults are Calculated from the captured assumptions.\n'+'\n'.join(lines)+'\nArithmetic'),
                types.SimpleNamespace(extract_text=lambda: 'Page 4 of 4\nAssessment and report metadata')])

            def mapped_path(value):
                original = Path(value)
                if str(value).startswith('/qa/'):
                    return qa/original.name
                return original

            with patch.dict('sys.modules', {'renderer':types.ModuleType('renderer'),
                   'renderer.render':render_module,'renderer.template':template_module,'pypdf':pdf_module}), \
                    patch('pathlib.Path', mapped_path), patch('os.getuid', return_value=10001, create=True), \
                    patch('time.sleep'):
                exec(compile(SOURCE, str(PROBE), 'exec'), {'__file__':str(PROBE)})

        cases = {
            'invented_value_net_and_roi': ['Monthly value $1000.00 Monthly total cost $110.00',
                'Monthly net value $890.00 ROI 809%', 'Required assumptions are unknown'],
            'cost_substring_decoy': [GOOD[0].replace('$110.00','$1110.00'), GOOD[1]],
            'unrelated_cost_decoy': [GOOD[0].replace('$110.00','Unknown'), GOOD[1], 'Other amount 110.00'],
            'zero_value_instead_of_unknown': [GOOD[0].replace('value Unknown','value $0.00'), GOOD[1]],
            'zero_net_instead_of_unknown': [GOOD[0], GOOD[1].replace('net value Unknown','net value $0.00')],
        }
        for label, lines in cases.items():
            run(GOOD)
            assert (qa/'renderer-package-summary.json').exists()
            assert (qa/'packaged-renderer.pdf').exists()
            try:
                run(lines)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Incorrect presentation was accepted: '+label)
            assert not (qa/'renderer-package-summary.json').exists()
            assert not (qa/'packaged-renderer.pdf').exists()
            checks.append(label)
    receipt = {'qualification_passed':True,'negative_cases':checks,'pass_then_fail_receipts_removed':True,
               'scope':'Mock-only exact probe execution; no real Chromium/PDF/Docker/provider/production execution.'}
    (ROOT/'evidence/renderer-probe-negative-controls.json').write_text(json.dumps(receipt,indent=2))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
