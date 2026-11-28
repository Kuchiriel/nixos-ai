/* LAB_MOBILE_BEGIN — controles touch para o /lab no celular.
   Fonte: tools/lab-timeline/mobile-controls.js (gerado/injetado por
   scripts/lab-view-sync.py). Nao editar a copia inline do index.html. */
(function () {
  const host = document.getElementById('lab3dCanvas');
  if (!host) return;
  host.style.touchAction = 'none';

  const pts = new Map();
  const dist = () => {
    const a = [...pts.values()];
    return a.length < 2 ? 0 : Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y);
  };
  let lastDist = 0;
  const zoom = (delta) => host.dispatchEvent(
    new WheelEvent('wheel', { deltaY: delta, bubbles: true, cancelable: true }));

  host.addEventListener('pointerdown', (e) => {
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) lastDist = dist();
  });
  host.addEventListener('pointermove', (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 2) {
      const d = dist();
      if (lastDist) zoom((lastDist - d) * 5);   // pinça: afasta ⇒ aproxima
      lastDist = d;
    }
  });
  const drop = (e) => { pts.delete(e.pointerId); if (pts.size < 2) lastDist = 0; };
  host.addEventListener('pointerup', drop);
  host.addEventListener('pointercancel', drop);

  const bar = document.createElement('div');
  bar.id = 'labMobileBar';
  bar.style.cssText = 'position:fixed;left:8px;right:8px;bottom:10px;z-index:99;' +
    'display:flex;gap:8px;justify-content:center;pointer-events:none;';
  const mk = (txt, fn, title) => {
    const b = document.createElement('button');
    b.textContent = txt; b.title = title || txt;
    b.style.cssText = 'pointer-events:auto;min-width:48px;min-height:44px;' +
      'font-size:18px;border-radius:10px;border:1px solid #30363d;' +
      'background:#161b22ee;color:#e6edf3;touch-action:manipulation;';
    b.addEventListener('click', fn);
    bar.appendChild(b);
    return b;
  };
  const slider = document.getElementById('machRange');
  const step = (n) => {
    if (!slider) return;
    const v = Math.max(0, Math.min(Number(slider.max || 0), Number(slider.value || 0) + n));
    slider.value = v;
    slider.dispatchEvent(new Event('input', { bubbles: true }));
  };
  mk('−', () => zoom(90), 'Afastar');
  mk('+', () => zoom(-90), 'Aproximar');
  mk('‹', () => step(-1), 'Marco anterior');
  mk('›', () => step(1), 'Próximo marco');
  mk('▶', () => {
    const play = document.getElementById('machPlay');
    if (play) play.click();
  }, 'Linha do tempo');
  document.body.appendChild(bar);
  window.labMobileReady = true;
})();
/* LAB_MOBILE_END */
