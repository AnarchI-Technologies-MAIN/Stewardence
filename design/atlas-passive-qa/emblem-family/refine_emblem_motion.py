from pathlib import Path
import re
OUT=Path.cwd()/'outputs'/'emblem-family'
motion='''// Local optional presentation motion. No network, tracking or data access.
const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
for (const host of document.querySelectorAll('[data-epistemic-motion]')) {
  const layer = host.querySelector('.meta');
  let angle = 0, velocity = 1.2, target = 1.2, last = null, frame = null;
  function draw(time) {
    if (last === null) last = time;
    const dt = Math.min((time-last)/1000, 0.05); last = time;
    velocity += (target-velocity)*(1-Math.exp(-dt/1.4));
    angle = (angle+velocity*dt)%360;
    layer.style.transform = `rotate(${angle}deg)`;
    frame = requestAnimationFrame(draw);
  }
  function start() { last=null; if (!preference.matches && frame===null) frame=requestAnimationFrame(draw); }
  function stop() { if(frame!==null) cancelAnimationFrame(frame); frame=null; last=null; }
  function setDirection(reverse) { target=reverse ? -1.2 : 1.2; layer.style.opacity=reverse ? '.028' : '.018'; }
  host.addEventListener('pointerenter',()=>setDirection(true));
  host.addEventListener('pointerleave',()=>setDirection(host.contains(document.activeElement)));
  host.addEventListener('focusin',()=>setDirection(true));
  host.addEventListener('focusout',()=>setDirection(false));
  preference.addEventListener('change',()=>{ if(preference.matches) stop(); if(!preference.matches) start(); });
  document.addEventListener('visibilitychange',()=>{if(document.hidden) stop(); if(!document.hidden) start();});
  start();
}
'''
(OUT/'motion.js').write_text(motion,encoding='utf-8')
p=OUT/'index.html';text=p.read_text(encoding='utf-8')
text=text.replace('class="motion" tabindex','class="motion" data-epistemic-motion tabindex')
text=text.replace('.meta{animation:rotateCW 300s linear infinite}', '.meta{animation:none;opacity:.018;transition:opacity 2s ease}')
text=text.replace('animation:rotateCCW 300s linear infinite;opacity:.005','animation:none;opacity:.028')
text=text.replace('Meta-layer opacity: idle 0.2%, hover/focus 0.5%.','Meta-layer opacity: idle 1.8%, hover/focus 2.8%.')
text=text.replace('It is intentionally almost invisible at these specified values.','Quiet drift; direction reverses gradually, without resetting the angle.')
text=text.replace('</main></html>','</main><script type="module" src="motion.js"></script></html>')
p.write_text(text,encoding='utf-8')
with (OUT/'implementation-notes.md').open('a',encoding='utf-8') as f:f.write('''

## Founder-approved interpretation — subtle living motion

Alexander subsequently delegated the conflicting motion choices and requested movement that is almost imperceptible. The review page now uses a local requestAnimationFrame controller: 1.2°/second, softly eased direction changes, continuous angle without a reset, 1.8% idle / 2.8% hover meta opacity. Reduced motion and hidden tabs stop frame updates. These small opacity increases replace the near-invisible literal percentage only in the living preview. No other layers pulse or move. Optional standalone motion SVGs retain the literal original specification; use the review component and motion.js for the preferred smooth behavior. Production integration remains pending.
''')
print('Smooth local motion preview prepared')
