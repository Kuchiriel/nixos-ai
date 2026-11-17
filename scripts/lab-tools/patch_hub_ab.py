#!/usr/bin/env python3
"""Evolucao do hub (17/11): A/B com escada, GPU ao vivo e controles de nivel.

Aplica mudancas cirurgicas e falha se qualquer ancora sumir (o arquivo muda
com frequencia; substituicao silenciosa seria pior que erro).
"""
import sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else
         "/home/nixos/projects/nixos-ai/scripts/agent-hub.mjs")
s = p.read_text(encoding="utf-8")
feitas = []


def troca(antigo, novo, nome):
    global s
    if antigo not in s:
        print(f"ERRO: ancora ausente: {nome}", file=sys.stderr)
        raise SystemExit(2)
    s = s.replace(antigo, novo, 1)
    feitas.append(nome)


# ── 1. abLoopState: ciclo, modelo E nivel ────────────────────────────────
troca(
    """    for (const l of lines.reverse()) {
      let m = l.match(/CICLO\\s+(\\d+)/);
      if (m && out.cycle === null) { out.cycle = parseInt(m[1], 10); continue; }
      m = l.match(/A\\/B para (\\S+)/);
      if (m && out.current === null) { out.current = m[1]; continue; }""",
    """    for (const l of lines.reverse()) {
      // (17/11) formato novo: "CICLO 12 (nivel L2)" e "A/B bonsai @ L2"
      let m = l.match(/CICLO\\s+(\\d+)(?:\\s*\\(nivel\\s+(\\w+)\\))?/);
      if (m && out.cycle === null) {
        out.cycle = parseInt(m[1], 10);
        if (m[2]) out.nivel = m[2];
        continue;
      }
      m = l.match(/A\\/B (?:para )?(\\S+?)(?:\\s+@\\s+(\\w+))?$/);
      if (m && out.current === null) {
        out.current = m[1];
        if (m[2]) out.nivel = m[2];
        continue;
      }""",
    "abLoopState nivel")

# ── 2. abStats: escada, erros e patch vazio ──────────────────────────────
inicio = s.index("function abStats() {")
fim = s.index("function abPatches() {")
antigo_stats = s[inicio:fim]
novo_stats = '''const AB_NIVEIS = ['L1', 'L2', 'L3'];

// (17/11) O veredito honesto: linha com "erro" (swap/checker/timeout) NAO e
// medida do modelo. "N failed" == reprovado; so "0 failed" aprova. O regex
// antigo (/\\d+ passed/) marcava "1 failed, 3 passed" como aprovado.
function abVeredito(r) {
  if (r.erro) return 'erro';
  const chk = String(r.checker || '');
  if (!chk) return 'erro';
  const f = /(\\d+) failed/.exec(chk);
  if (f) return parseInt(f[1], 10) === 0 ? 'pass' : 'fail';
  return /(\\d+) passed/.test(chk) ? 'pass' : 'erro';
}

function abStats() {
  const rows = abResults().filter(r => r.ck === 'v2' || r.ck === 'v3');
  const legacy = abResults().length - rows.length;
  const modelos = new Map();
  const porNivel = {};            // {modelo: {L1:{pass,fail,erro}}}
  const stats = { ciclos: 0, pass: 0, fail: 0, erro: 0, legacy, dur_med: 0, vazio: 0 };
  const durs = [];

  for (const r of rows) {
    const v = abVeredito(r);
    const nivel = r.nivel || 'L3';
    const m = modelos.get(r.modelo) || {
      modelo: r.modelo, ciclos: 0, pass: 0, fail: 0, erro: 0,
      durs: [], patch_bytes: 0, ultimo: null, niveis: {},
    };
    m.ciclos++; stats.ciclos++;
    if (r.dur > 0) durs.push(r.dur);
    if (v === 'pass') { m.pass++; stats.pass++; }
    else if (v === 'fail') { m.fail++; stats.fail++; }
    else { m.erro++; stats.erro++; }
    const nv = m.niveis[nivel] || { pass: 0, fail: 0, erro: 0, ciclos: 0 };
    nv.ciclos++;
    if (v === 'pass') nv.pass++; else if (v === 'fail') nv.fail++; else nv.erro++;
    m.niveis[nivel] = nv;
    porNivel[r.modelo] = porNivel[r.modelo] || {};
    porNivel[r.modelo][nivel] = nv;
    if (!r.patch_bytes) stats.vazio++;
    if (r.patch_bytes) m.patch_bytes = r.patch_bytes;
    m.ultimo = { checker: String(r.checker || r.erro || ''), dur: r.dur, ts: r.ts, nivel, veredito: v };
    modelos.set(r.modelo, m);
  }

  const arr = [...modelos.values()].map(m => {
    const d = m.durs.filter(x => x > 0).sort((a, b) => a - b);
    m.dur_med = d.length ? d[Math.floor(d.length / 2)] : 0;
    delete m.durs;
    m.taxa = m.ciclos ? Math.round(100 * m.pass / m.ciclos) : 0;
    return m;
  }).sort((a, b) => a.modelo.localeCompare(b.modelo));

  const ds = durs.sort((a, b) => a - b);
  stats.dur_med = ds.length ? Math.round(ds[Math.floor(ds.length / 2)]) : 0;
  return { models: arr, stats, niveis: AB_NIVEIS, matriz: porNivel };
}

// GPU ao vivo: quem ocupa a VRAM agora e quem esta no ar no laboratorio.
// O painel precisa mostrar POR QUE um ciclo falhou (VRAM cheia), nao so que
// falhou — foi exatamente o buraco de 62 ciclos em "swap falhou".
function abGpu() {
  const out = { total: null, usado: null, livre: null, apps: [], portas: {}, residente: false, swap: '?' };
  try {
    const r = spawnSync('nvidia-smi', ['--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'], { encoding: 'utf8', timeout: 4000 });
    const m = /(\\d+)\\s*,\\s*(\\d+)/.exec(r.stdout || '');
    if (m) { out.usado = +m[1]; out.total = +m[2]; out.livre = out.total - out.usado; }
  } catch { /* sem gpu */ }
  try {
    const r = spawnSync('nvidia-smi', ['--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'], { encoding: 'utf8', timeout: 4000 });
    out.apps = (r.stdout || '').split('\\n').filter(Boolean).map(l => {
      const [pid, mb] = l.split(',').map(x => parseInt(x.trim(), 10));
      return { pid, mb };
    }).filter(x => x.pid);
  } catch { /* sem gpu */ }
  try {
    const r = spawnSync('ss', ['-ltnH'], { encoding: 'utf8', timeout: 3000 });
    for (const l of (r.stdout || '').split('\\n')) {
      for (const port of [8080, 8092, 8095, 8096]) {
        if (new RegExp(':' + port + '\\\\b').test(l)) out.portas[port] = true;
      }
    }
  } catch { /* sem ss */ }
  out.residente = !!out.portas[8092];
  out.swap = out.portas[8080] ? 'bonsai' : out.portas[8096] ? 'mtp' : (out.residente ? 'residente' : 'livre');
  return out;
}

'''
s = s[:inicio] + novo_stats + s[fim:]
feitas.append("abStats escada")

# ── 3. /api/ab/live: gpu + niveis + ultimas linhas ──────────────────────
troca(
    """    const loop = abLoopState();
    const { models, stats } = abStats();
    let log = [];
    try { log = readFileSync(AB_LOG, 'utf8').split('\\n').filter(Boolean).slice(-40); } catch { /* sem log */ }
    return send(200, JSON.stringify({ loop, models, stats, patches: abPatches(), log }), 'application/json');""",
    """    const loop = abLoopState();
    const { models, stats, niveis, matriz } = abStats();
    let log = [];
    try { log = readFileSync(AB_LOG, 'utf8').split('\\n').filter(Boolean).slice(-40); } catch { /* sem log */ }
    const resultados = abResults().slice(-14).reverse().map(r => ({
      modelo: r.modelo, nivel: r.nivel || 'L3', dur: r.dur, ts: r.ts,
      veredito: abVeredito(r), checker: r.checker || r.erro || '',
      patch_bytes: r.patch_bytes || 0,
    }));
    return send(200, JSON.stringify({ loop, models, stats, niveis, matriz, gpu: abGpu(),
      resultados, patches: abPatches(), log }), 'application/json');""",
    "rota ab/live")

# ── 4. controle: nivel forcado ──────────────────────────────────────────
troca(
    """      if (action === 'run') {
        if (model) writeFileSync(AB_CTL, 'run:' + model);
        else writeFileSync(AB_CTL, 'now');
        return send(200, JSON.stringify({ ok: true, message: model ? ('rodando ' + model) : 'rodando agora' }), 'application/json');
      }""",
    """      if (action === 'run') {
        if (model) writeFileSync(AB_CTL, 'run:' + model);
        else writeFileSync(AB_CTL, 'now');
        return send(200, JSON.stringify({ ok: true, message: model ? ('rodando ' + model) : 'rodando agora' }), 'application/json');
      }
      // (17/11) degrau da escada: o painel escolhe onde o proximo ciclo mede.
      if (action === 'level') {
        const nivel = String(body.level || '').toUpperCase();
        if (!AB_NIVEIS.includes(nivel)) {
          return send(400, JSON.stringify({ error: 'nivel invalido: ' + (nivel || '(vazio)') }), 'application/json');
        }
        writeFileSync(AB_CTL, 'level:' + nivel);
        evPush('ab', 'proximo ciclo forcado no nivel ' + nivel, { src: 'cmd' });
        return send(200, JSON.stringify({ ok: true, message: 'proximo ciclo em ' + nivel }), 'application/json');
      }""",
    "controle level")

# ── 5. pollAB: veredito honesto + nivel no evento ───────────────────────
troca(
    """  const res = tailFrom(AB_RES, tails.abRes);
  for (const line of res.split('\\n').filter(Boolean)) {
    let r; try { r = JSON.parse(line); } catch { continue; }
    const ok = /(\\d+) passed/.test(String(r.checker || ''));
    evPush(ok ? 'ok' : 'fail',
      `A/B ${r.modelo}: ${r.checker || 'sem veredito'} (${r.dur || 0}s)`,
      { src: 'ab', modelo: r.modelo, checker: r.checker });
  }""",
    """  const res = tailFrom(AB_RES, tails.abRes);
  for (const line of res.split('\\n').filter(Boolean)) {
    let r; try { r = JSON.parse(line); } catch { continue; }
    const v = abVeredito(r);
    evPush(v === 'pass' ? 'ok' : 'fail',
      `A/B ${r.modelo} @ ${r.nivel || 'L3'}: ${r.erro ? 'ERRO ' + r.erro : (r.checker || 'sem veredito')} (${r.dur || 0}s)`,
      { src: 'ab', modelo: r.modelo, nivel: r.nivel, veredito: v, checker: r.checker });
  }""",
    "pollAB veredito")

p.write_text(s, encoding="utf-8")
print("OK:", ", ".join(feitas))
