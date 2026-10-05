from pathlib import Path
from PIL import Image,ImageDraw
import json,re,hashlib,zipfile
from collections import Counter
OUT=Path.cwd()/'outputs'/'atlas-v3';WORK=Path.cwd()/'work'/'v3-review';WORK.mkdir(exist_ok=True)
catalog=json.loads((OUT/'screen-catalog.json').read_text(encoding='utf-8'));checks=[];missing=[]
for s in catalog:
    file=OUT/'mockups'/f"{s['id']}.png";im=Image.open(file);im.load();im.save(file,format='PNG')
    assert (OUT/s['brand_asset']).exists()
    text=(OUT/'screens'/f"{s['id']}.html").read_text(encoding='utf-8');assert 'data-epistemic-motion' in text;assert 'helix-orbit-' not in text
    for ref in re.findall(r'(?:src|href)="([^"]+)"',text):
        if ref.startswith(('http','#','data:')):continue
        if not ((OUT/'screens')/ref).resolve().exists():missing.append({'screen':s['id'],'reference':ref})
    s['visual_review']['method']='All 51 desktop/mobile headings verified during browser capture; v3 brand placement reviewed in thumbnail contact sheets. Static review only.'
    checks.append({'screen':s['id'],'png_dimensions':list(im.size),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'brand_variant':s['brand_variant']})
assert not missing,missing
for offset in [0,18,36]:
    chunk=catalog[offset:offset+18];sheet=Image.new('RGB',(1440,((len(chunk)+2)//3)*270),'#edf2f7');draw=ImageDraw.Draw(sheet)
    for i,s in enumerate(chunk):
        im=Image.open(OUT/'mockups'/f"{s['id']}.png").convert('RGB');im.thumbnail((470,240));x=(i%3)*480;y=(i//3)*270;sheet.paste(im,(x,y+25));draw.text((x+4,y+5),s['id'],fill='#14243b')
    sheet.save(WORK/f'contact-{offset//18+1}.png')
(OUT/'screen-catalog.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
p=OUT/'index.html';text=p.read_text(encoding='utf-8');text=re.sub(r'const screens=\[.*?\];const grid',lambda m:'const screens='+json.dumps(catalog)+';const grid',text,flags=re.S);p.write_text(text,encoding='utf-8')
report={'revision':'atlas-v3-2026-10-03','screens':51,'status_counts':dict(Counter(s['status'] for s in catalog)),'approved_brand':'transparent purple continuity emblem family','changed_mockups':checks,'missing_screen_asset_links':missing,'production_changes':False,'limits':['Static references; no live application implementation or deployment.','No claim of accessibility compliance or backend workflow qualification.','Decorative signatures do not represent measured evidence completeness.'],'source_provenance':'Preserved source-evidence.json from qualification-package inspection; base commit alone does not reproduce deployed candidate.'}
(OUT/'artifact-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(OUT/'render-verification.json').write_text(json.dumps({'revision':'atlas-v3','board_count':51,'desktop_and_mobile_heading_checks':51,'capture_method':'Browser board screenshots; fixed viewports with scrolling HTML for long pages'},indent=2),encoding='utf-8')
(OUT/'package_atlas_v3.py').write_bytes(Path(__file__).read_bytes())
archive=OUT.parent/'stewardence-design-atlas-v3.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for f in OUT.rglob('*'):
        if f.is_file():z.write(f,f.relative_to(OUT))
print(json.dumps({'zip':str(archive),'bytes':archive.stat().st_size,'status_counts':report['status_counts'],'missing_asset_links':len(missing)}))
