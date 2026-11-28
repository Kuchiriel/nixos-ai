/* LAB_LIVE_BEGIN — painel de execução ao vivo e caixa de geração legível.
   Fonte: tools/lab-timeline/lab-live.js (injetado por scripts/lab-view-sync.py).
   Dados: window.LAB_LIVE, escrito pelo poller em live-status.json. */
(function () {
  const css = document.createElement('style');
  css.textContent = `
    #labLive{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin:14px 0}
    #labLive .job{background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:11px 12px;min-width:0}
    #labLive .job b{display:block;font:600 12px ui-monospace,monospace;color:#79c0ff;overflow-wrap:anywhere}
    #labLive .st{font:11px ui-monospace,monospace;color:#8b949e;overflow-wrap:anywhere}
    #labLive .ok{color:#3fb950}.run{color:#d29922}.wait{color:#8b949e}
    #labLive .bar{height:4px;background:#21262d;border-radius:4px;margin-top:7px;overflow:hidden}
    #labLive .bar i{display:block;height:100%;background:#238636}
    #prompt,#out{width:100%;max-width:100%;box-sizing:border-box;overflow-wrap:anywhere}
    #out{white-space:pre-wrap;max-height:240px;overflow:auto;background:#0d1117;padding:12px;border-radius:8px;border:1px solid #30363d}
    #genTags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
    #genTags button{font-size:12px;padding:4px 9px}
    #genTags .tag{color:#3fb950;border-color:#238636}
  `;
  document.head.appendChild(css);

  const L = window.LAB_LIVE || {};
  const host = document.getElementById('labLiveHost');
  if (host) {
    const jobs = (L.jobs || []).map(j => {
      const k = (j.kaggle || '');
      const state = j.done ? '<span class="ok">concluído</span>'
        : k.includes('RUNNING') ? '<span class="run">Kaggle RUNNING</span>'
        : k.includes('QUEUED') ? '<span class="wait">Kaggle QUEUED</span>'
        : j.kaggle === '' ? '<span class="run">local / fila</span>'
        : '<span class="wait">—</span>';
      const pct = j.done ? 100 : (k.includes('RUNNING') ? 55 : k.includes('QUEUED') ? 12 : 35);
      return `<div class="job"><b>${j.id}</b><div class="st">${state}</div>` +
        `<div class="st">${(j.kaggle || '').replace(/^.*status /, '').slice(0, 70)}</div>` +
        `<div class="bar"><i style="width:${pct}%"></i></div></div>`;
    }).join('');
    const local = L.local || {};
    const extra = `<div class="job"><b>poller / relógio</b><div class="st">${L.ts || 'sem heartbeat'}</div>` +
      `<div class="st">F166 ${local.f166 ? 'medido' : '—'} · F167 ${(local.f167 || {}).step || (local.f167 || {}).seed || '—'} · F168 ${(local.f168 || {}).corpus || (local.f168 || {}).seed || '—'}</div>` +
      `<div class="st">atualiza sozinho a cada 15 s</div></div>`;
    host.innerHTML = jobs + extra;
  }

  // Caixa de geração: quebra linha, nao vaza para a direita, e aceita tag humana.
  const out = document.getElementById('out');
  if (out) {
    const tags = document.createElement('div');
    tags.id = 'genTags';
    const saved = JSON.parse(localStorage.getItem('lab-gen-tags') || '[]');
    const paint = () => {
      tags.innerHTML = saved.slice(-5).map(t => `<span class="tag">${t}</span>`).join('');
    };
    ['boa', 'ruim', 'neutra', 'repetitiva', 'criativa'].forEach(label => {
      const b = document.createElement('button');
      b.textContent = label;
      b.onclick = () => {
        saved.push(new Date().toISOString().slice(11, 16) + ' ' + label + ' :: ' + out.textContent.slice(0, 60));
        localStorage.setItem('lab-gen-tags', JSON.stringify(saved.slice(-50)));
        paint();
      };
      tags.appendChild(b);
    });
    out.parentNode.insertBefore(tags, out.nextSibling);
    paint();
  }

  // Remove texto inútil / view legada do rodapé.
  document.querySelectorAll('p').forEach(p => {
    const t = p.textContent || '';
    if (t.includes('Inspiração de visualização') || t.includes('Frentes anteriores a F32')) p.remove();
  });
  document.querySelectorAll('details').forEach(d => {
    if ((d.textContent || '').includes('Ver visão antiga')) d.remove();
  });
})();
/* LAB_LIVE_END */
