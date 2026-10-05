"""Actual renderer stress specimens; synthetic layout inputs, no assessment claim."""
import copy
import hashlib
import json
from pathlib import Path
from renderer.render import render_pdf

base = json.loads(Path('/qa/synthetic-render-payload.json').read_bytes())
long = copy.deepcopy(base)
long['metadata']['organization_display_name'] = 'LONGNAME'+('Z'*220)
long['inventory'][0]['display_name'] = 'LONGTOOL'+('X'*220)
long['policy_findings'][0]['explanation'] = 'LONGSIGNAL'+('Y'*500)
long['recommendations'][0]['remediation'] = 'LONGPROPOSAL'+('W'*500)
long['roi']['assumptions']['loaded_hourly_rate']['provenance'] = 'Müller & García supplied'
many = copy.deepcopy(base)
many['metadata']['organization_display_name'] = 'Synthetic multi-tool layout firm'
many['inventory'] = []
many['individual_risk_findings'] = []
many['policy_findings'] = []
many['recommendations'] = []
for number in range(8):
    label = 'Synthetic tool '+str(number+1)
    row = copy.deepcopy(base['inventory'][0])
    row['display_name'] = label
    many['inventory'].append(row)
    risk = copy.deepcopy(base['individual_risk_findings'][0])
    risk['tool_name'] = label
    many['individual_risk_findings'].append(risk)
    for finding in base['policy_findings'][:3]:
        row = copy.deepcopy(finding)
        row['tool_name'] = label
        many['policy_findings'].append(row)
    for recommendation in base['recommendations'][:3]:
        row = copy.deepcopy(recommendation)
        row['tool_name'] = label
        many['recommendations'].append(row)
many['executive_summary']['inventory_count'] = 8
many['executive_summary']['finding_count'] = 24
table = copy.deepcopy(base)
table['metadata']['organization_display_name'] = 'Synthetic long-table layout firm'
table['inventory'] = []
for number in range(80):
    row = copy.deepcopy(base['inventory'][0])
    row['display_name'] = 'Synthetic table tool '+format(number+1, '03d')
    table['inventory'].append(row)
table['executive_summary']['inventory_count'] = 80
results = []
for name,payload in [('long-input',long),('multi-tool',many),('long-table',table)]:
    data = render_pdf(payload)
    Path('/qa/'+name+'.pdf').write_bytes(data)
    Path('/qa/'+name+'.json').write_text(json.dumps(payload,ensure_ascii=False))
    results.append({'specimen':name,'pdf_sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
print(json.dumps({'rendered':results,'scope':'Synthetic layout stress only; not valid source-derived multi-tool assessment or admission qualification.'}))
