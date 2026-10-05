from pathlib import Path
import json, math, hashlib, random, shutil, zipfile

OUT=Path.cwd()/'outputs'/'emblem-family'; OUT.mkdir(parents=True,exist_ok=True)
PAGES=['Overview','Inventory','ROI','Policies','Reports','Evidence Library','Billing','Admin','Funnels','Contact','Pricing','Login','Signup']
NAVY='#0A0F1C'
def slug(s):return s.lower().replace(' ','-')
def hexpts(r):return ' '.join(f'{256+r*math.cos(math.radians(-90+i*60)):.3f},{256+r*math.sin(math.radians(-90+i*60)):.3f}' for i in range(6))
LEFT='M 88 256 C 166 145 278 128 368 194 C 300 162 216 199 155 256 C 217 318 294 350 369 316 C 273 384 160 369 88 256 Z'
RIGHT='M 424 256 C 346 145 234 128 144 194 C 212 162 296 199 357 256 C 295 318 218 350 143 316 C 239 384 352 369 424 256 Z'
def emblem(page,animated=False,mono=False):
    ident=slug(page); rng=random.Random('stewardence-emblem-v1:'+ident); idx=PAGES.index(page)
    # All geometry shared. Deterministic gradient direction and tick signature distinguish pages.
    angle=idx*13.0; dx=math.cos(math.radians(angle))*50;dy=math.sin(math.radians(angle))*50
    css='''<style>.meta{transform-origin:256px 256px;opacity:.002}'''
    if animated:css+='''.meta{animation:rotateCW 300s linear infinite}.emblem:hover .meta,.emblem:focus-within .meta{animation:rotateCCW 300s linear infinite;opacity:.005}@keyframes rotateCW{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}@keyframes rotateCCW{from{transform:rotate(0deg)}to{transform:rotate(-360deg)}}@media(prefers-reduced-motion:reduce){.meta{animation:none!important;transform:none!important}}'''
    css+='</style>'
    defs=f'''<defs><radialGradient id="cosmic"><stop stop-color="#1A0F2E"/><stop offset="1" stop-color="#1A0F2E" stop-opacity="0"/></radialGradient><linearGradient id="left" x1="{50-dx}%" y1="{50-dy}%" x2="{50+dx}%" y2="{50+dy}%"><stop stop-color="#0D1B3A"/><stop offset="1" stop-color="#3B1F6B"/></linearGradient><linearGradient id="right" x1="{50+dx}%" y1="{50-dy}%" x2="{50-dx}%" y2="{50+dy}%"><stop stop-color="#0F3A3A"/><stop offset="1" stop-color="#2CC7C7"/></linearGradient><linearGradient id="purple"><stop stop-color="#6D2AFF"/><stop offset="1" stop-color="#A45CFF"/></linearGradient><filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="2"/></filter><filter id="feather"><feGaussianBlur stdDeviation="1.2"/></filter><filter id="glow" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="6"/></filter><mask id="eye"><rect width="512" height="512" fill="white"/><path d="M146 256 Q256 116 366 256 Q256 396 146 256Z" fill="black" opacity=".7" filter="url(#feather)"/></mask></defs>'''
    bands=f'<g mask="url(#eye)" opacity=".92" style="isolation:isolate"><path d="{LEFT}" fill="url(#left)" filter="url(#soft)"/><path d="{RIGHT}" fill="url(#right)" filter="url(#soft)" style="mix-blend-mode:screen"/></g>'
    ticks=[];signature=[]
    for i in range(32):
        jitter=rng.uniform(-1.5,1.5);alpha=.7+rng.uniform(-.08,.08);a=math.radians(i*11.25+jitter-90);r=204
        ticks.append(f'<line x1="{256+r*math.cos(a):.3f}" y1="{256+r*math.sin(a):.3f}" x2="{256+(r+12)*math.cos(a):.3f}" y2="{256+(r+12)*math.sin(a):.3f}" stroke="#C8F8FF" stroke-width="2" opacity="{alpha:.4f}"/>')
        signature.append({'index':i,'angle_jitter_degrees':round(jitter,5),'opacity':round(alpha,5)})
    aperture=f'<polygon points="{hexpts(28)}" fill="#2CD9FF" filter="url(#glow)" opacity=".4"/><polygon points="{hexpts(42)}" fill="none" stroke="#4FF2FF" stroke-width="3"/><polygon points="{hexpts(28)}" fill="#2CD9FF"/>'
    for radius,alpha in [(18,.4),(12,.25),(7,.15)]:aperture+=f'<polygon points="{hexpts(radius)}" fill="none" stroke="#0A0F1C" stroke-width="1.5" opacity="{alpha}"/>'
    meta='<g class="meta"><circle cx="256" cy="256" r="110" fill="none" stroke="url(#purple)" stroke-width="14"/></g>'
    if mono:
        defs='';css='';bands=f'<path d="{LEFT}" fill="currentColor"/><path d="{RIGHT}" fill="currentColor"/>'
        aperture=f'<polygon points="{hexpts(42)}" fill="none" stroke="currentColor" stroke-width="8"/><polygon points="{hexpts(18)}" fill="currentColor"/>';ticks=[];meta=''
        bg=''
    else:bg='<rect width="512" height="512" fill="#0A0F1C"/><rect width="512" height="512" fill="url(#cosmic)"/>'
    result=f'<svg xmlns="http://www.w3.org/2000/svg" class="emblem" viewBox="0 0 512 512" width="512" height="512" role="img" aria-labelledby="title desc"><title id="title">Stewardence {page} emblem</title><desc id="desc">Continuity cradle and nested hexagonal aperture. Decorative deterministic page signature; not an evidence completeness measurement.</desc>{defs}{css}{bg}{meta}{bands}{aperture}{"".join(ticks)}</svg>'
    return result,signature
variants=[]
for page in PAGES:
    name=slug(page);svg,signature=emblem(page)
    (OUT/f'{name}.svg').write_text(svg,encoding='utf-8')
    (OUT/f'{name}-motion.svg').write_text(emblem(page,animated=True)[0],encoding='utf-8')
    (OUT/f'{name}-mono.svg').write_text(emblem(page,mono=True)[0],encoding='utf-8')
    variants.append({'page':page,'id':name,'gradient_angle_degrees':PAGES.index(page)*13,'tick_signature':signature,'sha256':hashlib.sha256(svg.encode()).hexdigest(),'status':'presentation asset; not wired to application or evidence data'})
    render=f'<!doctype html><html><meta charset="utf-8"><title>{page} emblem export</title><style>html,body{{margin:0;width:512px;height:512px;overflow:hidden}}svg{{display:block}}</style>{svg}</html>'
    (OUT/f'{name}-render.html').write_text(render,encoding='utf-8')
cards=''.join(f'<article><img src="{slug(p)}.svg" alt="Stewardence {p} emblem"><h2>{p}</h2><p><a href="{slug(p)}.svg">SVG</a> · <a href="{slug(p)}-motion.svg">Motion SVG</a> · <a href="{slug(p)}-mono.svg">Monochrome</a></p><div class="mono"><img src="{slug(p)}-mono.svg" alt="Monochrome {p} emblem"></div></article>' for p in PAGES)
html=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stewardence overview emblem family</title><style>*{{box-sizing:border-box}}body{{margin:0;background:#0A0F1C;color:#eef7ff;font:16px/1.6 "Segoe UI",sans-serif}}main{{max-width:1480px;margin:auto;padding:36px}}h1{{margin:0}}p{{color:#b5c9d9}}a{{color:#7cdded}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}}article{{border:1px solid #28304b;padding:20px;border-radius:8px;background:#101626}}article>img{{width:100%;height:auto}}h2{{margin:12px 0 0}}.mono{{background:white;color:black;padding:12px;border-radius:4px}}.mono img{{width:64px;height:64px}}.motion{{display:flex;gap:24px;align-items:center;flex-wrap:wrap}}.motion svg{{width:256px;height:256px}}:focus-visible{{outline:3px solid #4FF2FF;outline-offset:5px}}@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media(max-width:580px){{main{{padding:20px}}.grid{{grid-template-columns:1fr}}}}@media(prefers-reduced-motion:reduce){{.meta{{animation:none!important}}}}</style><main><h1>Stewardence · Overview emblem family</h1><p>Overview master + twelve page variants · Deterministic SVG studies · October 3, 2026</p><p>Shared geometry; page-specific gradient direction and reproducible tick signatures. These ticks are decorative—not live evidence coverage. Production branding is unchanged.</p><section><h2>Motion master</h2><div class="motion" tabindex="0" aria-label="Emblem motion preview; hover or focus to reverse direction">{emblem('Overview',animated=True)[0]}<p>1.2°/second · 300 seconds per revolution.<br>Meta-layer opacity: idle 0.2%, hover/focus 0.5%.<br>It is intentionally almost invisible at these specified values.<br>Reduced-motion preference stops rotation.</p></div></section><div class="grid">{cards}</div><p><a href="implementation-notes.md">Specification decisions and limits</a> · <a href="manifest.json">Deterministic manifest</a></p></main></html>'''
(OUT/'index.html').write_text(html,encoding='utf-8')
(OUT/'manifest.json').write_text(json.dumps({'revision':'overview-family-v1','canvas':[512,512],'seed_scheme':'stewardence-emblem-v1:<page-slug>','geometry_shared':True,'variant_count':12,'overview_master':True,'variants':variants},indent=2),encoding='utf-8')
(OUT/'implementation-notes.md').write_text('''# Overview emblem family — implementation notes

Overview master plus Inventory, ROI, Policies, Reports, Evidence Library, Billing, Admin, Funnels, Contact, Pricing, Login and Signup. Native SVG assets, not generated raster approximations. Production assets and templates remain unchanged.

## Specification resolutions

- Coordinates were not supplied for the bands. The renderer defines shared cubic Bézier ribbon contours; these are an interpretation requiring visual review. The filled contours approximate a 48px band; width varies with taper and interlock rather than a constant-width stroke.
- Eye: centered 220×140 quadratic almond, 1.2px mask feather, 70% knockout. This clears bands without painting an independent gaze graphic.
- Screen is used at the overlap. The conflicting overlay instruction is not applied simultaneously. Opacity .92; band blur 2px.
- The tick-ring radius was unspecified: chosen 204px. Base opacity .70, variance ±.08; angle jitter ±1.5°, deterministically seeded per page. The same seed regenerates each signature. These are decorative signatures and do not encode observed completeness, unknowns, or actual measurements. A data-driven version needs a denominator and explicit mapping before implementation.
- Radius 42 outline, 28 cyan filled core with glow, then 18/12/7 nested dark outline hexes at .40/.25/.15 opacity. Nested radii cannot be distinguished reliably at tiny icon sizes.
- Meta ring: radius 110, width 14; .002 idle and .005 hover opacity kept literally. These values are barely visible. No unrequested brightness increase was applied.
- 1.2°/second resolves to 300 seconds per revolution. The supplied 12-second CSS would be 30°/second. The motion SVG uses 300 seconds.
- CSS animation reversal restarts the animation phase; a smooth exit to 0° then clockwise resumption requires a coordinated motion controller. That exit behavior is not implemented here. Static SVGs are the default exports; motion SVGs are optional review artifacts.
- Reduced-motion preference disables rotation. Keyboard focus on the preview triggers the same style as hover. Embedded image SVGs cannot be assumed to inherit host-page hover/focus; inline the optional motion SVG in a reviewed component if used.
- Monochrome exports intentionally remove backdrop, blur, ticks, nested detail and motion; they are compact structural derivatives, not identical full-detail illustrations. Page signatures disappear in this derivative; page labels remain necessary.

## Integration boundary

These assets are reviewable vector artwork, not a complete production qualification. Before adoption: select the final contour, check actual 16/24/32px rendering, confirm motion/opacity intent, coordinate filenames and ownership, collect Django static files, and inspect real pages. No routes, billing logic, integration behavior, security policy, analytics or application flags changed. The revised visual brief allows glow and gradients for this emblem family; the calm application layout remains separate.
''',encoding='utf-8')
(OUT/'build_emblem_family.py').write_bytes(Path(__file__).read_bytes())
print(json.dumps({'folder':str(OUT),'overview_plus_variants':len(PAGES),'svg_files':len(list(OUT.glob('*.svg')))}))
