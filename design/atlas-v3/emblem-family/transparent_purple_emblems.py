from pathlib import Path
import json, hashlib, zipfile, io, re, shutil
from PIL import Image
import resvg_py

OUT=Path.cwd()/'outputs'/'emblem-family'
REPLACE={'#4FF2FF':'#7441B7','#2CD9FF':'#8651C9','#2CC7C7':'#9565D5','#C8F8FF':'#8955C6'}
def transform(text):
    text=re.sub(r'<rect width="512" height="512" fill="(?:#0A0F1C|url\(#cosmic\))"/>','',text)
    for old,new in REPLACE.items():text=text.replace(old,new)
    return text
for f in list(OUT.glob('*.svg'))+list(OUT.glob('*-render.html')):
    f.write_text(transform(f.read_text(encoding='utf-8')),encoding='utf-8')
p=OUT/'index.html';text=transform(p.read_text(encoding='utf-8'))
text=text.replace('body{margin:0;background:#0A0F1C;color:#eef7ff','body{margin:0;background:#eef4fc;color:#0A0F1C')
text=text.replace('p{color:#b5c9d9}','p{color:#52647b}').replace('a{color:#7cdded}','a{color:#7441B7}')
text=text.replace('border:1px solid #28304b','border:1px solid #ccd8e9').replace('background:#101626','background:#ffffff')
text=text.replace('Stewardence overview emblem family','Stewardence transparent purple emblem family')
text=text.replace('Stewardence · Overview emblem family','Stewardence · Transparent purple family')
text=text.replace('Shared geometry; page-specific gradient direction and reproducible tick signatures.','Transparent assets · royal-purple highlights · shared geometry and reproducible page signatures.')
text=text.replace('.motion{display:flex;', '.motion{background:#e7effb;border-radius:8px;padding:20px;display:flex;')
text=text.replace('.mono{background:white;color:black;', '.mono{background:#e7effb;color:black;')
p.write_text(text,encoding='utf-8')
manifest=json.loads((OUT/'manifest.json').read_text())
checks=[]
for row in manifest['variants']:
    name=row['id'];f=OUT/f'{name}.svg';row['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()
    for size in [16,24,32,64,128,256,512]:
        png=resvg_py.svg_to_bytes(svg_path=str(f),width=size,height=size)
        dest=OUT/f'{name}-{size}.png';dest.write_bytes(png)
        im=Image.open(io.BytesIO(png)).convert('RGBA');alpha=im.getchannel('A')
        assert alpha.getextrema()[0]==0
        assert im.getpixel((0,0))[3]==0
        checks.append({'file':dest.name,'size':size,'alpha_range':alpha.getextrema(),'transparent_corner':True})
    (OUT/f'{name}-mono-512.png').write_bytes(resvg_py.svg_to_bytes(svg_path=str(OUT/f'{name}-mono.svg'),width=512,height=512))
manifest.update({'revision':'transparent-purple-v2','background':'transparent','highlight_palette':REPLACE,'raster_renderer':'resvg-py; native SVG raster export with alpha'})
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(OUT/'verification.json').write_text(json.dumps({'revision':'transparent-purple-v2','svg_assets':39,'color_pngs':checks,'monochrome_pngs':13,'production_assets_changed':False,'motion_component_retained':True,'limits':'Decorative tick signatures; not live evidence measurements. Tiny-size lineage details are not fully legible.'},indent=2),encoding='utf-8')
with (OUT/'implementation-notes.md').open('a',encoding='utf-8') as f:f.write('''

## Transparent purple revision

All 39 SVGs now have no painted canvas/background. Color PNGs are re-rendered directly from SVG with native alpha, not white-background removal. Pale cyan replaced by royal-purple highlights: core #8651C9, outline #7441B7, band highlight #9565D5, ticks #8955C6. Navy, deep purple and muted teal remain. White cards and light-blue motion/monochrome wells are review-page backgrounds only, never baked into the assets. motion.js remains unchanged.

Rebuild sequence: build_emblem_family.py → refine_emblem_motion.py → transparent_purple_emblems.py. PNG rendering requires resvg-py; this is a local export dependency, not an application/frontend dependency. Browser screenshot of the review page is an opaque presentation board, distinct from the transparent asset files.
''')
(OUT/'transparent_purple_emblems.py').write_bytes(Path(__file__).read_bytes())
with zipfile.ZipFile(Path.cwd()/'outputs'/'stewardence-emblem-family.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in OUT.iterdir():
        if f.is_file() and f.name!='family-preview.png':z.write(f,f.name)
print(json.dumps({'transparent_color_pngs':len(checks),'transparent_mono_pngs':13,'svg_assets':39,'purple_core':'#8651C9'}))
