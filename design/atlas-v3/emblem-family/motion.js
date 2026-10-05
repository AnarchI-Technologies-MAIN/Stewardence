// Local optional presentation motion. No network, tracking or data access.
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
