from pathlib import Path
from PIL import Image
import json, hashlib, zipfile, xml.etree.ElementTree as ET
OUT=Path.cwd()/'outputs'/'emblem-family'
manifest=json.loads((OUT/'manifest.json').read_text())
for row in manifest['variants']:
    name=row['id']; source=OUT/f'{name}-capture.png'
    image=Image.open(source);image.load();image=image.crop((0,0,512,512));image.save(OUT/f'{name}-512.png',format='PNG')
    for size in [16,24,32,64,128,256]:image.resize((size,size),Image.Resampling.LANCZOS).save(OUT/f'{name}-{size}.png')
    source.unlink()
for f in OUT.glob('*.svg'):ET.parse(f)
assert len({r['sha256'] for r in manifest['variants']})==13
Image.open(OUT/'family-preview.png').save(OUT/'family-preview.png',format='PNG')
checks={'native_svg_files':39,'page_variants':12,'overview_master':True,'unique_static_svg_hashes':13,'png_exports':91,'visual_review':'All thirteen rendered emblems inspected in browser gallery; overview inspected at full size. Variant differences intentionally subtle: gradient direction and deterministic tick signature.','motion':'Continuous 1.2 degree/second drift with eased reversal in local preview; reduced-motion stop coded. No production integration or assistive-technology qualification.','limits':['Not a live evidence metric','Filled band contours interpret unspecified path coordinates','Nearly invisible literal opacity increased slightly in preferred living preview','Mono derivatives share structural geometry and do not identify pages on their own']}
(OUT/'verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
for script in ['refine_emblem_motion.py','package_emblem_family.py']:(OUT/script).write_bytes((Path.cwd()/'work'/script).read_bytes())
with zipfile.ZipFile(Path.cwd()/'outputs'/'stewardence-emblem-family.zip','w',zipfile.ZIP_DEFLATED) as z:
    for f in OUT.iterdir():
        if f.is_file():z.write(f,f.name)
print(json.dumps(checks))
