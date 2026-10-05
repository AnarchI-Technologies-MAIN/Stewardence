from pathlib import Path
import shutil,json,re
BASE=Path.cwd()/'outputs';OUT=BASE/'atlas-v3';OUT.mkdir(exist_ok=True)
for name in ['assets','screens','boards','mockups','emblem-family']:
    shutil.copytree(BASE/name,OUT/name,dirs_exist_ok=True)
for f in BASE.iterdir():
    if f.is_file() and f.suffix in ['.html','.css','.md','.json','.csv']:shutil.copy2(f,OUT/f.name)
mapping={1:'overview',2:'overview',3:'pricing',4:'funnels',5:'funnels',6:'funnels',7:'funnels',8:'login',9:'signup',10:'admin',11:'admin',12:'inventory',13:'inventory',14:'inventory',15:'inventory',16:'inventory',17:'inventory',18:'inventory',19:'inventory',20:'evidence-library',21:'evidence-library',22:'evidence-library',23:'evidence-library',24:'evidence-library',25:'policies',26:'policies',27:'policies',28:'policies',29:'policies',30:'roi',31:'roi',32:'roi',33:'roi',34:'roi',35:'policies',36:'policies',37:'reports',38:'reports',39:'evidence-library',40:'evidence-library',41:'evidence-library',42:'admin',43:'admin',44:'billing',45:'billing',46:'policies',47:'policies',48:'contact',49:'overview',50:'admin',51:'funnels'}
catalog=json.loads((OUT/'screen-catalog.json').read_text())
for s in catalog:
    ident=s['id']; variant=mapping[int(ident[:2])]; p=OUT/'screens'/f'{ident}.html';text=p.read_text()
    text=re.sub(r'../assets/stewardence-helix-orbit-(?:dark|light)\.png','../emblem-family/overview.svg',text)
    text=text.replace('alt="Current Stewardence logo"','alt="Stewardence"')
    svg=(OUT/'emblem-family'/f'{variant}.svg').read_text()
    svg=svg.replace('opacity:.002','opacity:.018;transition:opacity 2s ease')
    # Emblem is decorative beside a meaningful page title; page labels never depend on icon recognition.
    svg=re.sub(r'role="img" aria-labelledby="title desc"','aria-hidden="true" focusable="false"',svg)
    text=re.sub(r'(<h1>.*?</h1><p class="subtitle">.*?</p>)',lambda m:f'<div class="page-heading"><div class="page-emblem" data-epistemic-motion>{svg}</div><div>{m.group(1)}</div></div>',text,count=1)
    text=text.replace('</body>','<script type="module" src="../emblem-family/motion.js"></script></body>')
    p.write_text(text,encoding='utf-8')
    s.update({'mockup_revision':'atlas-v3-2026-10-03','brand_variant':variant,'brand_asset':f'emblem-family/{variant}.svg','mockup_change':'Approved transparent purple emblem family in shared brand placement and page semantic header; existing maturity/data/authority contracts preserved.'})
    s['visual_review']['method']='V3 browser capture and review pending.'
    b=OUT/'boards'/f'{ident}.html';b.write_text(b.read_text().replace('Design reference','Atlas v3 · Design reference'),encoding='utf-8')
(OUT/'screen-catalog.json').write_text(json.dumps(catalog,indent=2),encoding='utf-8')
css='''
/* Atlas v3 approved semantic emblem layer */
:root{--brand-purple:#8651c9;--brand-purple-deep:#7441b7}
.brand img{width:44px;height:44px;object-fit:contain}
.page-heading{display:flex;gap:20px;align-items:center;margin:12px 0 22px}
.page-emblem{width:104px;height:104px;flex:0 0 104px}
.page-emblem svg{display:block;width:100%;height:100%}
.page-heading h1{margin:0 0 12px}.page-heading .subtitle{margin:0}
@media(max-width:700px){.page-heading{gap:12px;align-items:flex-start}.page-emblem{width:68px;height:68px;flex-basis:68px}.page-heading h1{font-size:28px}.page-heading .subtitle{font-size:16px}}
@media(prefers-reduced-motion:reduce){.page-emblem .meta{animation:none!important;transition:none!important}}
'''
with (OUT/'design-system.css').open('a') as f:f.write(css)
p=OUT/'index.html';text=p.read_text();text=text.replace('Design atlas v2','Design atlas v3').replace('reconciled design atlas','design atlas v3')
text=text.replace('Original51 boards inspected; revised text rendered from local HTML with original brand assets.','Atlas v3 uses the founder-approved transparent purple emblem family across all51 intended screens.')
text=re.sub(r'<section id="logos".*?</section>','<section id="logos"><h2>Approved visual semantic layer</h2><p>Transparent purple continuity emblem. Shared geometry, twelve page signatures plus Overview. Decorative identity, not a live evidence score.</p><p><a href="emblem-family/index.html">Living emblem family</a> · <a href="brand-semantic-layer.md">Brand mappings and integration contract</a></p></section>',text,flags=re.S)
text=re.sub(r'const screens=\[.*?\];const grid',lambda m:'const screens='+json.dumps(catalog)+';const grid',text,flags=re.S)
(OUT/'index.html').write_text(text,encoding='utf-8')
(OUT/'brand-semantic-layer.md').write_text('''# Atlas v3 — approved logo visual semantic layer

Founder selected the transparent purple emblem family on October 3, 2026. Apply the approved direction to this design atlas; production application asset replacement remains a separate coordinated implementation.

Overview master and twelve variants: Inventory, ROI, Policies, Reports, Evidence Library, Billing, Admin, Funnels, Contact, Pricing, Login and Signup. All share geometry and palette; deterministic gradient directions and tick signatures distinguish variants subtly. A page label carries the actual meaning. No icon implies feature availability, certification, active collection or authority. Ticks do not display measured completeness.

Shared brand placement uses Overview. Page headings use a mapped semantic variant; mappings are recorded in screen-catalog.json and brand-asset-mappings.json. Evidence covers integrations, source history and audit; Policies covers assessments and recommendations; Admin covers workspace and authority surfaces. Funnels includes internal lead review as an identity mapping only: internal operator navigation remains separate. Legal layouts retain unapproved content status.

Color highlights: #8651C9 core, #7441B7 outline, #9565D5 band highlight, #8955C6 ticks. Backgrounds are transparent. The page retains calm navy navigation, blue controls, white surfaces and light-blue state panels. Purple is an identity accent, not a severity color.

The page-header emblem is decorative and hidden from assistive technology beside the visible heading. Shared brand imagery has a meaningful Stewardence label. Motion is a faint outer-layer drift at 1.2 degrees/second, with eased direction change, no angle reset and reduced-motion support. No core, text or layout moves. Static assets remain the fallback. Tiny 16px samples lose lineage detail; use a reviewed compact derivative before replacing the production favicon.

Assets are self-contained/local. No new framework, font service, CDN, analytics or provider scripts. Actual Django template/static-file implementation, keyboard acceptance and production rendering remain pending. Preserve current filenames/contracts until coordinated replacement.
''',encoding='utf-8')
(OUT/'brand-asset-mappings.json').write_text(json.dumps([{'screen':s['id'],'variant':s['brand_variant'],'asset':s['brand_asset']} for s in catalog],indent=2),encoding='utf-8')
for name in ['design-handoff.md','refinement-notes.md']:
    p=OUT/name;old=p.read_text();p.write_text('''# Atlas v3 update — approved transparent purple identity

All 51 design references now use the approved emblem family in shared brand placement and semantic page headers. See brand-semantic-layer.md and brand-asset-mappings.json. All availability, maturity, authority, evidence and billing boundaries from the repaired atlas remain in force. Historical logo-pause/exploration notes below are superseded by the approved direction; the production application remains unchanged.

'''+old,encoding='utf-8')
(OUT/'logo-review.md').write_text('Approved direction: transparent purple continuity emblem family. Historical B/C drafts are superseded. See brand-semantic-layer.md. Production implementation and final favicon qualification remain pending.',encoding='utf-8')
(OUT/'build_atlas_v3.py').write_bytes(Path(__file__).read_bytes())
print('Atlas v3 source: 51 screen headers and brand mappings updated')
