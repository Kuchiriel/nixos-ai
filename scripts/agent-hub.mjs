#!/usr/bin/env node
// Agent Hub — mission control do opencode no nitro-v15.
// Autossuficiente: só node 24 + filesystem. Serve em 127.0.0.1:8091.
// Rotas:
//   GET  /                          -> página (self-contained)
//   GET  /api/agents                -> roster + busy/última msg (cacheado 3s)
//   GET  /api/transcript?session=S  -> últimas 12 partes da sessão (via API loopback)
//   POST /api/wake                  -> {"name":"...","text":"..."} injeta user-turn na sessão
// Nada de credencial exposta: o token fica só no lado do servidor (loopback).

import { readFileSync, writeFileSync, readdirSync, existsSync, statSync, openSync, readSync, closeSync, mkdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const HOME = process.env.HOME;
// (16/11) A UI saiu do corpo do .mjs para um arquivo proprio: 39 KB de
// HTML inline era impossivel de evoluir com seguranca. O arquivo e' lido do
// disco a cada request (barato) e o HTML inline segue como fallback.
const __DIR = dirname(fileURLToPath(import.meta.url));
const UI_FILE = join(__DIR, 'agent-hub-ui.html');
const OC = 'http://100.121.100.103:4599';
const ENV = HOME + '/.config/opencode/server.env';
const ROSTER = HOME + '/projects/.agents/roster.json';
const TASKS_FILE = HOME + '/.local/state/jarvis/agent-hub-tasks.json';
const CWD = '/home/nixos';

let pw;
function password() {
  if (pw) return pw;
  const raw = readFileSync(ENV, 'utf8');
  const m = raw.match(/^OPENCODE_SERVER_PASSWORD=(.*)$/m);
  pw = m ? m[1].trim().replace(/^["']|["']$/g, '') : '';
  return pw;
}
const AUTH = () => 'Basic ' + Buffer.from('opencode:' + password()).toString('base64');

// (14/11) TOKEN PROPRIO DO HUB. O hub le transcripts e injeta user-turn em
// sessoes da frota: sem token, quem alcanca a porta da LAN/tailnet le
// qualquer transcript e escreve em qualquer agente. O token vem do env
// AGENT_HUB_TOKEN ou do arquivo ~/.config/opencode/agent-hub.token (0600).
// FAIL-CLOSED: sem token configurado, as rotas sensiveis recusam.
const TOKEN_FILE = HOME + '/.config/opencode/agent-hub.token';
let tok;
function hubToken() {
  if (tok !== undefined) return tok;
  let t = (process.env.AGENT_HUB_TOKEN || '').trim();
  if (!t) { try { t = readFileSync(TOKEN_FILE, 'utf8').trim(); } catch { t = ''; } }
  tok = t;
  return tok;
}
function sameSecret(a, b) {
  const x = Buffer.from(String(a || '')), y = Buffer.from(String(b || ''));
  if (x.length !== y.length || x.length === 0) return false;
  return timingSafeEqual(x, y);
}
function authorized(req) {
  const t = hubToken();
  if (!t) return false;
  const h = String(req.headers['x-agent-hub-token'] || '');
  const b = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  return sameSecret(h, t) || sameSecret(b, t);
}

let sessionCache = { at: 0, map: new Map() };
async function sessions() {
  const now = Date.now();
  if (now - sessionCache.at < 3000) return sessionCache.map;
  const r = await fetch(OC + '/api/session', { headers: { Authorization: AUTH() }, signal: AbortSignal.timeout(8000) });
  const list = await r.json().catch(() => []);
  const map = new Map();
  for (const s of Array.isArray(list) ? list : (list.data || [])) map.set(s.id, s);
  sessionCache = { at: now, map };
  return map;
}
async function oc(path) {
  const r = await fetch(OC + path, { headers: { Authorization: AUTH() }, signal: AbortSignal.timeout(10000) });
  const body = await r.text();
  try { return { status: r.status, json: JSON.parse(body) }; } catch { return { status: r.status, body }; }
}
function roster() {
  try { return JSON.parse(readFileSync(ROSTER, 'utf8')).agents || []; } catch { return []; }
}
async function agentsJSON() {
  let map = new Map();
  let oc_ok = false;
  try { map = await sessions(); oc_ok = true; } catch (e) { oc_ok = false; }
  const rows = roster().map(a => {
    const s = a.session ? map.get(a.session) : null;
    // (14/11) A API /api/session NAO devolve 'busy' (medido: as chaves reais
    // sao agent, cost, id, location, model, outcome, projectID, time, title,
    // tokens). Ler 'busy' dava 0 para todo mundo e todo agente aparecia
    // 'idle' mesmo trabalhando. A fonte real e' time.updated (ultimo
    // movimento da sessao) comparado com agora.
    const upd = s ? (s.time?.updated ?? null) : null;
    const busy = upd ? (Date.now() - upd < BUSY_MS) : null;
    const status = s ? (busy ? 'busy' : 'idle') : 'ghost';
    // (16/11) O painel precisa mostrar QUEM e cada agente: a persona (MBTI),
    // o modelo, a lane e o contexto. O roster ja tinha esses campos e o hub
    // jogava fora.
    const sessModel = s ? (s.model ? (typeof s.model === 'object' ? (s.model.modelID || s.model.id) : s.model) : null) : null;
    return { name: a.name, codename: a.codename || '?', lane: a.lane || '-',
             session: a.session || null, busy, updated: upd, status,
             persona: a.mbti || null, model: a.model || sessModel || null,
             note: a.note || null, context: a.context || null, host: a.host || null,
             aliases: a.aliases || null };
  });
  // (19/11, medido) A API /api/session devolve TODAS as sessoes (50), mas o
  // hub so mostrava as que estao no roster (6): agentsJSON mapeava roster().
  // Quem abre 50 sessoes nao via 44 delas no painel. Agora as sessoes sem
  // dono no roster entram como linha propria (unclaimed), com o titulo como
  // nome, para o painel refletir o servidor.
  const cobertas = new Set(roster().map((a) => a.session).filter(Boolean));
  for (const [sid, s] of map) {
    if (cobertas.has(sid)) continue;
    const upd = s.time?.updated ?? null;
    const busy = upd ? (Date.now() - upd < BUSY_MS) : null;
    const m = s.model ? (typeof s.model === 'object' ? (s.model.modelID || s.model.id) : s.model) : null;
    rows.push({
      name: s.title || sid, codename: null, lane: '-', session: sid,
      busy, updated: upd, status: busy ? 'busy' : 'idle',
      persona: null, model: m, note: 'sessao sem dono no roster',
      context: null, host: s.location?.directory || null, aliases: null,
      unclaimed: true,
    });
  }
  rows.sort((x, y) => (y.busy ? 1 : 0) - (x.busy ? 1 : 0) || String(x.codename || x.name).localeCompare(String(y.codename || y.name)));
  return { servers: { opencode: oc_ok }, agents: rows };
}
const TEXT_MAX = 2000;
// janela de 'atividade recente' que conta como busy (o dono pedalava com
// 600s no watcher; aqui e' menor porque o hub so mostra estado)
const BUSY_MS = Number(process.env.AGENT_HUB_BUSY_MS || 90000);
// corpo maximo do POST /api/wake (o texto do dono cabe em folgado)
const BODY_MAX = 64 * 1024;
// (16/11) leitor de body unico: as rotas novas (comandos) reaproveitam.
async function readBody(req) {
  let raw = '';
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > BODY_MAX) throw new Error('body grande demais');
  }
  return raw;
}

// (15/11) RATE LIMIT do spawn: o hub cria agentes que consomem modelo e
// VRAM (o router tem maxResident=1). Sem teto, um celular pode encher a
// casa de sessoes. A2A v1.0: entrada externa e nao confiavel e precisa
// de politica e rate limit.
const SPAWN_RATE = { windowMs: 10 * 60 * 1000, max: 6, maxConcurrent: 3 };
const _spawnLog = [];   // {ts, origin}

function spawnAllowed(origin) {
  const now = Date.now();
  while (_spawnLog.length && now - _spawnLog[0].ts > SPAWN_RATE.windowMs) {
    _spawnLog.shift();
  }
  if (_spawnLog.length >= SPAWN_RATE.max) {
    return { ok: false, error: 'rate limit: ${SPAWN_RATE.max} spawns em ${SPAWN_RATE.windowMs / 60000} min (tente depois)' };
  }
  _spawnLog.push({ ts: now, origin });
  return { ok: true };
}
async function wake(name, text) {
  // (15/11, crouton-alpha) SEM DUPLICAR: o hub NAO injeta prompt por conta
  // propria. Usa o caminho CANONICO da casa (jarvis.core.comms.deliver ->
  // coord_roster.send_message -> bus + wake pela API), que e o mesmo do
  // /to do Telegram e o mesmo do plugin agent-wake. Antes o hub fazia POST
  // direto em /api/session/<id>/prompt (3o caminho de injecao) — o que
  // duplicava guard, cooldown, dedupe e registro no bus.
  const j = await pyJSON("deliver.py", [String(name || ""), String(text || "")], 120000)
    .catch(e => ({ ok: false, error: String(e) }));
  return { status: j && j.ok ? 200 : 500, body: j };
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const HTML = `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Hub — nitro-v15</title>
<style>
:root { color-scheme: dark; --bg:#0d1117; --card:#161b22; --line:#30363d; --acc:#7ee787; --warn:#f0c674; --bad:#ff7b72; --idx:#58a6ff; }
* { box-sizing:border-box; }
body { font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; background:var(--bg); color:#c9d1d9; margin:0; }
a { color:var(--idx); }
header { display:flex; gap:12px; align-items:center; padding:12px 18px; border-bottom:1px solid var(--line); background:#0a0f17; position:sticky; top:0; z-index:9; }
h1 { font-size:16px; margin:0; letter-spacing:.04em; }
#hud { margin-left:auto; color:#8b949e; font-size:12px; }
main { padding:18px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; }
.card.ghost { opacity:.55; }
.row { display:flex; align-items:center; gap:8px; }
.dot { width:10px; height:10px; border-radius:50%; background:var(--acc); }
.dot.idle { background:var(--warn); } .dot.ghost { background:var(--bad); }
.name { font-weight:700; } .muted { color:#8b949e; font-size:12px; }
.turn { margin-top:8px; display:flex; gap:6px; } input,textarea { background:#0d1117; border:1px solid var(--line); color:#c9d1d9; border-radius:6px; padding:6px 8px; font:inherit; width:100%; } textarea{min-height:52px;resize:vertical;}
button { background:#21262f; color:#c9d1d9; border:1px solid var(--line); border-radius:6px; padding:6px 10px; cursor:pointer; font:inherit; } button:hover { border-color:var(--idx); color:#fff; }
pre { background:#0d1117; border:1px solid var(--line); border-radius:6px; padding:8px; max-height:260px; overflow:auto; font-size:11px; }
.section-title { color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:.1em; margin:18px 0 8px; }
.spawnbox { margin-bottom:14px; }
.spawnbox .turn { display:flex; gap:8px; align-items:center; margin-top:6px; }
.spawnbox select, .spawnbox input { background:#0d1117; border:1px solid var(--line); color:#c9d1d9; border-radius:6px; padding:6px 8px; font:inherit; }
.busbox { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px; max-height:340px; overflow:auto; font-size:12px; }
.busline { padding:4px 0; border-bottom:1px dashed #21262f; }
.busline:last-child { border-bottom:0; }
.busline .who { color:var(--idx); font-weight:700; }
.busline .kind { color:var(--warn); }
.busline .ts { color:#8b949e; margin-right:6px; }
</style></head><body>
<header><h1>🤖 AGENT HUB <span class="muted">nitro-v15</span></h1>
<input id="tok" type="password" placeholder="token do hub" style="max-width:220px">
<button id="tokSave">salvar</button><span id="hud">conectando…</span></header>
<main>
<div class="section-title">agentes</div>
<div id="grid" class="grid"></div>
<div class="section-title">estado da casa</div>
<div class="card spawnbox">
  <div class="row"><span class="muted" id="stSum">carregando…</span>
    <button id="stRefresh" style="margin-left:auto">atualizar</button></div>
  <div id="stBox" class="muted" style="margin-top:6px"></div>
</div>
<div class="section-title">dungeon A/B (bonsai vs qwen 4b mtp) - dentro do sistema novo</div>
<div class="card spawnbox">
  <div class="row"><button id="abGo">rodar A/B (2 modelos)</button>
    <span id="abSum" class="muted" style="margin-left:10px">sem veredito ainda</span></div>
  <div id="abOut" class="muted" style="margin-top:8px"></div>
</div>
<div class="section-title">criar agente</div>
<div class="card spawnbox">
  <div class="turn"><input id="spTask" placeholder="tarefa do agente novo (a persona e o modelo sao escolhidos)"></div>
  <div class="turn"><select id="spModel"><option value="">modelo: auto (dificuldade + cooldown)</option></select>
    <select id="spProfile"><option value="">perfil: auto</option><option value="redteam">redteam (INTP, baixa recusa)</option></select>
    <input id="spName" placeholder="nome (opcional)" style="max-width:160px">
    <button id="spGo">criar</button></div>
  <div id="spOut" class="muted" style="margin-top:8px"></div>
</div>
<div class="section-title">conversa da frota (bus)</div>
<div id="bus" class="busbox">carregando…</div>
<div id="drawer" class="section-title" style="display:none">transcript de <span id="drawerName"></span> — <a id="drawerToggle" href="#">fechar</a></div>
<pre id="transcript" style="display:none"></pre>
</main>
<script>
const $ = (s, el=document) => el.querySelector(s);
const $$ = (s, el=document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const now = () => new Date().toLocaleTimeString('pt-BR');
const TOKEN = () => localStorage.getItem('hubToken') || '';
async function fetchAgents() {
  try { return await (await fetch('/api/agents', { headers: { 'x-agent-hub-token': TOKEN() } })).json(); } catch (e) { return { servers: { opencode: false }, agents: [] }; }
}
$('#tok').value = TOKEN();
$('#tokSave').addEventListener('click', () => { localStorage.setItem('hubToken', $('#tok').value.trim()); refresh(); });
async function refresh() {
  const d = await fetchAgents();
  $('#hud').textContent = 'opencode=' + (d.servers.opencode ? 'OK' : 'OFFLINE') + ' · ' + now();
  $('#grid').innerHTML = d.agents.map(a => \`<div class="card \${a.status==='ghost'?'ghost':''}">
      <div class="row"><span class="dot \${a.status}"></span><span class="name">\${esc(a.codename)}</span> <span class="muted">\${esc(a.name)}</span></div>
      <div class="muted">lane=\${esc(a.lane)} · \${a.status}\${a.busy ? ' · há ' + Math.round((Date.now()-a.busy/1)/1000) + 's ativo' : ''}</div>
      <div class="muted" style="margin-top:4px">model=\${esc(a.model||'-')} · sess=\${esc((a.session||'ghost').slice(0,18))}…</div>
      <div class="turn"><button onclick="openTranscript('\${esc(a.session)}', this)">transcript</button> <button class="closeSession" data-session="\${esc(a.session || '')}" data-name="\${esc(a.codename || a.name || '')}" title="fechar sessao">fechar</button></div>
      <div class="turn"><input placeholder="dizer algo para \${esc(a.codename)}…" class="say"><button class="send">↵</button></div>
    </div>\`).join('');
  $$('.card').forEach((card, i) => {
    const say = $('.say', card), send = $('.send', card);
    send.addEventListener('click', async () => {
      const t = say.value.trim(); if (!t) return;
      send.disabled = true; say.disabled = true;
      const r = await fetch('/api/wake', { method: 'POST', headers: {'Content-Type': 'application/json','x-agent-hub-token':TOKEN()}, body: JSON.stringify({ name: $('.name', card).textContent, text: t }) });
      say.value = r.ok ? '(enviado)' : '(falhou)';
      setTimeout(() => { say.value = ''; send.disabled = false; say.disabled = false; }, 1200);
    });
  });
}
async function openTranscript(session, btn) {
  const t = $('#transcript'), d = $('#drawer'), n = $('#drawerName');
  t.style.display = 'block'; d.style.display = 'block'; n.textContent = session.slice(0, 18);
  t.textContent = 'carregando…';
  try {
    const r = await fetch('/api/transcript?session=' + encodeURIComponent(session), { headers: { 'x-agent-hub-token': TOKEN() } });
    const d2 = await r.json();
    t.textContent = d2.lines.join('\\n\\n');
  } catch (e) { t.textContent = 'erro ao ler: ' + e; }
}
$('#drawerToggle').addEventListener('click', e => { e.preventDefault(); $('#transcript').style.display = 'none'; $('#drawer').style.display = 'none'; });
// (19/11) fechar sessao com confirmacao; so atua na sessao do card.
document.addEventListener('click', async (e) => {
  const b = e.target.closest('.closeSession');
  if (!b) return;
  const sid = b.dataset.session;
  if (!sid || !confirm('Fechar a sessao de ' + (b.dataset.name || sid.slice(0, 8)) + '? (o historico fica no DB)')) return;
  try {
    const r = await fetch('/api/session/close', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-agent-hub-token': TOKEN() },
      body: JSON.stringify({ session: sid }) });
    const d = await r.json();
    b.textContent = d.ok ? 'fechada' : 'erro';
    if (!d.ok) alert(d.error || ('HTTP ' + r.status));
  } catch (err) { b.textContent = 'erro'; }
});
async function loadModels() {
  const sel = document.getElementById('spModel');
  if (!sel) return;
  try {
    const d = await (await fetch('/api/models')).json();
    const groups = [];
    const rt = d.redteam_candidates || [];
    if (rt.length) {
      groups.push('redteam (baixa recusa)');
      for (const m of rt) groups.push('  ' + m.id + '  ctx=' + (m.context || '?') + ' · ' + (m.tier || ''));
    }
    const seen = new Set();
    for (const p of (d.providers || [])) {
      for (const m of p.models || []) {
        if (seen.has(m.id)) continue;
        seen.add(m.id);
        groups.push('  ' + m.id + '  ctx=' + (m.context || '?') + ' · ' + (m.tier || ''));
      }
    }
    sel.innerHTML = '<option value="">modelo: auto (dificuldade + cooldown)</option>'
      + groups.map(g => g.startsWith('  ') ? '<option value="' + g.trim().split(' ')[0] + '">' + g + '</option>' : '<optgroup label="' + g + '"></optgroup>').join('');
  } catch (e) { /* sem catalogo: segue com auto */ }
}
async function doSpawn() {
  const out = document.getElementById('spOut');
  const task = document.getElementById('spTask').value.trim();
  if (!task) { out.textContent = 'descreva a tarefa'; return; }
  out.textContent = 'criando… (pode levar ~1-2 min)';
  try {
    const r = await fetch('/api/spawn', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'x-agent-hub-token': TOKEN_FIELD.value },
      body: JSON.stringify({
        task: task,
        model: document.getElementById('spModel').value || undefined,
        profile: document.getElementById('spProfile').value || undefined,
        name: document.getElementById('spName').value || undefined,
      }),
    });
    const d = await r.json();
    out.textContent = (d.ok ? 'criado: ' + (d.session || '') + ' · ' + (d.model || '') + ' · ' + ((d.persona || {}).mbti || '') : 'falhou: ' + (d.error || JSON.stringify(d).slice(0, 200)));
    if (d.ok) document.getElementById('spTask').value = '';
    refresh();
  } catch (e) { out.textContent = 'erro: ' + e; }
}
async function refreshState() {
  const sum = document.getElementById('stSum'), box = document.getElementById('stBox');
  if (!sum) return;
  try {
    const d = await (await fetch('/api/state')).json();
    const ag = d.agentes || [], sp = d.spawns || [], sv = d.servicos || {};
    const up = Object.values(sv).filter(v => v === 'active').length;
    sum.textContent = ag.length + ' agentes · ' + (d.board?.claims || []).length + ' claims · '
      + sp.length + ' spawns · ' + up + '/' + Object.keys(sv).length + ' servicos ativos';
    const kan = (d.kanban && (d.kanban.lista || '')).split('\n').slice(0, 4).join(' | ').slice(0, 220);
    const fila = (d.fila || []).slice(0, 2).join(' / ').slice(0, 200);
    box.innerHTML = '<div>fila: ' + esc(fila || '-') + '</div><div>kanban: ' + esc(kan || '-') + '</div>';
  } catch (e) { sum.textContent = 'estado indisponivel: ' + e; }
}
async function refreshAB() {
  const sum = document.getElementById('abSum'), out = document.getElementById('abOut');
  if (!sum) return;
  try {
    const d = await (await fetch('/api/dungeon-ab')).json();
    const linhas = [];
    for (const [modelo, tasks] of Object.entries(d.modelos || {})) {
      for (const t of (tasks || [])) {
        linhas.push(modelo + ' -> ' + t.status + (t.attempts ? ' (tentativas ' + t.attempts + ')' : ''));
        if (t.validacao) linhas.push('    ' + String(t.validacao).slice(0, 160));
        if (t.erro) linhas.push('    erro: ' + String(t.erro).slice(0, 160));
      }
    }
    sum.textContent = linhas.length ? ('ultimo: ' + linhas.slice(0, 2).join(' | ')) : 'sem veredito ainda';
    out.textContent = linhas.join('\n') || ('checker: ' + (d.checker || '?'));
  } catch (e) { sum.textContent = 'erro: ' + e; }
}
async function runAB() {
  const sum = document.getElementById('abSum');
  if (sum) sum.textContent = 'rodando (o harness vai executar a task na fila)...';
  for (const m of ['bonsai', 'mtp']) {
    await fetch('/api/dungeon-ab?model=' + m, { method: 'POST' });
  }
  setTimeout(refreshAB, 3000);
}
async function refreshBus() {
  const el = document.getElementById('bus');
  if (!el) return;
  try {
    const r = await fetch('/api/bus?limit=40');
    const d = await r.json();
    if (!d.items || !d.items.length) {
      el.textContent = d.err ? ('bus indisponível: ' + d.err) : 'sem mensagens coord-json no bus (ainda)';
      return;
    }
    el.innerHTML = d.items.map(function (i) {
      var arrow = (i.to && i.to !== '-') ? ('\u2192 ' + esc(i.to) + ' ') : '';
      return '<div class="busline"><span class="ts">' + esc(i.ts) + '</span>'
        + '<span class="who">' + esc(i.from) + '</span> '
        + '<span class="kind">[' + esc(i.kind) + ']</span> '
        + arrow + esc(i.text) + '</div>';
    }).join('');
  } catch (e) { el.textContent = 'erro ao ler o bus: ' + e; }
}
setInterval(refresh, 5000); refresh();
setInterval(refreshBus, 10000); refreshBus();
setInterval(refreshState, 60000); refreshState();
document.addEventListener('DOMContentLoaded', function () {
  const b = document.getElementById('stRefresh');
  if (b) b.addEventListener('click', refreshState);
});
document.addEventListener('DOMContentLoaded', function () {
  const ab = document.getElementById('abGo');
  if (ab) ab.addEventListener('click', runAB);
  refreshAB();
  const go = document.getElementById('spGo');
  if (go) go.addEventListener('click', doSpawn);
  loadModels();
});
</script></body></html>`;

// ── BUS: a conversa da frota (issue #12 do repo Kuchiriel/mt5) ────────────
// (15/11, crouton-alpha) O dono pediu "ver como eles estao conversando".
// As mensagens entre agentes vao pro bus como comment com bloco ```coord-json.
// Le com o gh (autenticado no host) e cacheia 90s para nao estourar o
// rate-limit do GitHub (a UI faz poll a cada 10s).
let busCache = { at: 0, items: [], err: "" };
let stateCache = { at: 0, value: null };

function parseCoordJson(body) {
  const out = [];
  const blocks = String(body || "").match(/```coord-json\n([\s\S]*?)```/g) || [];
  for (const b of blocks) {
    const raw = b.replace(/```coord-json\n?/, "").replace(/```\s*$/, "");
    try {
      const j = JSON.parse(raw);
      if (j && typeof j === "object") out.push(j);
    } catch { /* bloco nao-json: ignora */ }
  }
  return out;
}

// token do GitHub (o mesmo do `gh` da casa) — lido do hosts.yml
function ghToken() {
  try {
    const y = readFileSync(HOME + '/.config/gh/hosts.yml', 'utf8');
    const m = y.match(/oauth_token:\s*(\S+)/);
    if (m) return m[1];
  } catch { /* sem token: a API publica ainda da o basico */ }
  return '';
}

async function busViaApi(limit) {
  const headers = { 'User-Agent': 'agent-hub', 'Accept': 'application/vnd.github+json' };
  const tok = ghToken();
  if (tok) headers.Authorization = 'Bearer ' + tok;
  // (15/11) o issue tem MILHARES de comentarios: per_page=1 na ultima
  // pagina traz os MAIS RECENTES (per_page=60 na primeira traz os de
  // 06/11 — medido). Pega as 2 ultimas paginas (60 cada) para ter o
  // presente e o passado recente.
  // (15/11) O issue tem 2033 comentarios: o GitHub ordena por criacao, entao
  // o PRESENTE esta no FIM. Descobre a ultima pagina com per_page=1 (o header
  // link traz rel=last) e le as 2 ultimas paginas com per_page=60 — a conta
  // de pagina muda com o per_page, entao recalcula: lastPage(per_page=1) e o
  // TOTAL de itens; com per_page=60 a ultima pagina e ceil(total/60).
  const base = 'https://api.github.com/repos/Kuchiriel/mt5/issues/100/comments';
  const head = await fetch(base + '?per_page=1', { headers, signal: AbortSignal.timeout(25000) });
  if (!head.ok) throw new Error('api.github.com ' + head.status);
  const link = head.headers.get('link') || '';
  const totalItems = Number(link.match(/[?&]page=(\d+)[^>]*>; rel="last"/)?.[1] || 1);
  const perPage = 60;
  const lastPage = Math.max(1, Math.ceil(totalItems / perPage));
  const pages = [Math.max(1, lastPage - 1), lastPage];
  const lists = await Promise.all(pages.map(async (pg) => {
    const r = await fetch(base + '?per_page=' + perPage + '&page=' + pg, { headers, signal: AbortSignal.timeout(30000) });
    if (!r.ok) throw new Error('api.github.com ' + r.status);
    return r.json();
  }));
  const list = lists.flat();
  const out = [];
  for (const c of list) {
    for (const j of parseCoordJson(c.body || '')) {
      out.push({
        ts: String(j.ts || '').slice(0, 19).replace('T', ' '),
        from: j.agent || j.from || '?',
        to: j.to || '-',
        kind: j.kind || 'msg',
        lane: j.lane || '',
        text: String(j.message || j.intent || j.note || '').replace(/\s+/g, ' ').slice(0, 400),
      });
    }
  }
  return out.slice(-limit);
}

async function busMessages(limit = 40) {
  const now = Date.now();
  // (20/11) 10s, nao 90s: o botao Bus tem de refletir a conversa da frota
  // em tempo real. Cada item traz `path` dizendo de onde veio.
  if (now - busCache.at < 10000) return { items: busCache.items.slice(-limit), cached: true, err: busCache.err };
  try {
    const j = await pyJSON('bus-paths.py', [String(limit)], 60000);
    const items = Array.isArray(j.items) ? j.items : [];
    busCache = { at: now, items, err: (j.errs || []).join(' | ') };
    return { items: items.slice(-limit), cached: false, err: busCache.err };
  } catch (e) {
    try {
      const items = await busViaApi(limit);
      busCache = { at: now, items, err: 'fallback gh#100: ' + String(e).slice(0, 120) };
      return { items: items.slice(-limit), cached: false, err: busCache.err };
    } catch (e2) {
      busCache = { at: now, items: busCache.items, err: String(e2).slice(0, 200) };
      return { items: busCache.items.slice(-limit), cached: true, err: busCache.err };
    }
  }
}

// ── CATALOGO DE MODELOS + RATE LIMIT + SPAWN (15/11, crouton-alpha) ────────
// Tudo via python da casa (o node deste unit nao executa binarios do nix
// store — medido), lido por HTTP nos endpoints 127.0.0.1.
async function pyJSON(script, args = [], timeoutMs = 60000) {
  const PY = process.env.PY_BIN || "/etc/profiles/per-user/nixos/bin/python3";
  const S = "/home/nixos/projects/nixos-ai/scripts/";
  const r = spawnSync(PY, [S + script, ...args], { encoding: "utf8", timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 });
  if (r.error) throw new Error(String(r.error.message || r.error));
  try { return JSON.parse(r.stdout || "{}"); } catch { return { raw: (r.stdout || "").slice(0, 300) }; }
}

async function pyMod(mod, args = [], timeoutMs = 60000) {
  const PY = process.env.PY_BIN || '/etc/profiles/per-user/nixos/bin/python3';
  const ROOT = '/home/nixos/projects/nixos-ai';
  const env = { ...process.env, PYTHONPATH: ROOT + '/modules/ai/jarvis/src' };
  const r = spawnSync(PY, ['-m', mod, ...args], { encoding: 'utf8', timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024, cwd: ROOT, env });
  if (r.error) throw new Error(String(r.error.message || r.error));
  try { return JSON.parse(r.stdout || '{}'); } catch { return { raw: (r.stdout || '').slice(0, 400) }; }
}

/* ══════════════════════════════════════════════════════════════════
   (16/11) MISSION CONTROL v2 — eventos ao vivo, estado do A/B e
   comandos. O painel anterior mostrava snapshots; o dono pediu para
   VER o happening: quem nasceu, quem falou, qual modelo trocou, o que
   falhou, o que deu certo — e mandar em tudo por botao.
   ══════════════════════════════════════════════════════════════════ */

const AB_DIR = '/home/nixos/logs/ab_loop';
const AB_LOG = AB_DIR + '/ab_loop.log';
const AB_RES = AB_DIR + '/results.jsonl';
const AB_CTL = HOME + '/.local/state/jarvis/nightwatch/ab_loop.control';
const AB_PID = HOME + '/.local/state/jarvis/nightwatch/ab_loop.pid';

// ── barramento de eventos (SSE) ────────────────────────────────
const evClients = new Set();
// (16/11) Buffer de historico: o poller roda sempre, mesmo sem cliente.
// Sem isso, quem abrisse o painel perdia tudo que aconteceu antes (medido).
const EVBUF = [];
const EVBUF_MAX = 400;
function evPush(kind, text, meta) {
  const ev = { kind: String(kind || 'say'), text: String(text ?? '').slice(0, 800), ts: Date.now(), meta: meta || null };
  EVBUF.push(ev);
  if (EVBUF.length > EVBUF_MAX) EVBUF.shift();
  const line = `data: ${JSON.stringify(ev)}\n\n`;
  for (const res of evClients) { try { res.write(line); } catch { evClients.delete(res); } }
  return ev;
}

let TASKS = [];
function loadTasks() {
  try { TASKS = JSON.parse(readFileSync(TASKS_FILE, 'utf8')); if (!Array.isArray(TASKS)) TASKS = []; } catch { TASKS = []; }
}
function saveTasks() {
  try { mkdirSync(dirname(TASKS_FILE), { recursive: true }); } catch {}
  try { writeFileSync(TASKS_FILE, JSON.stringify(TASKS.slice(-500), null, 2)); } catch {}
}
loadTasks();
function taskPush(patch) {
  const now = Date.now();
  const t = {
    id: patch.id || ('task_' + now + '_' + Math.random().toString(36).slice(2,8)),
    title: String(patch.title || '').slice(0,200),
    agent: String(patch.agent || '').slice(0,120),
    status: ['pending','doing','done','blocked'].includes(patch.status) ? patch.status : 'pending',
    note: String(patch.note || '').slice(0,500),
    createdAt: patch.createdAt || now,
    updatedAt: now,
    by: String(patch.by || 'hub').slice(0,80),
  };
  const i = TASKS.findIndex(x => x.id === t.id);
  if (i >= 0) TASKS[i] = { ...TASKS[i], ...t, createdAt: TASKS[i].createdAt }; else TASKS.unshift(t);
  saveTasks();
  evPush('task', `${t.status}: ${t.title}${t.agent ? ' -> '+t.agent : ''}`, { taskId: t.id, agent: t.agent, status: t.status });
  return TASKS.find(x => x.id === t.id) || t;
}

// ── leitura de arquivo com offset (tail incremental) ──────────
function tailFrom(path, state, maxBytes = 64 * 1024) {
  if (!existsSync(path)) return '';
  let size = 0;
  try { size = statSync(path).size; } catch { return ''; }
  let off = state.off || 0;
  if (off > size) off = 0;               // arquivo truncado/rotacionado
  if (size === off) return '';
  const from = Math.max(0, size - maxBytes);
  if (off < from) off = from;
  let fd;
  try {
    fd = openSync(path, 'r');
    const buf = Buffer.alloc(size - off);
    readSync(fd, buf, 0, buf.length, off);
    state.off = size;
    return buf.toString('utf8');
  } catch { return ''; } finally { try { if (fd !== undefined) closeSync(fd); } catch { /* ignore */ } }
}

// ── estado do A/B ─────────────────────────────────────────────
function abLoopState() {
  const out = { alive: false, pid: null, cycle: null, current: null, last_ts: null, control: 'run' };
  let pid = null;
  try { pid = parseInt(readFileSync(AB_PID, 'utf8').trim(), 10) || null; } catch { /* sem pidfile */ }
  out.pid = pid;
  if (pid) {
    try { process.kill(pid, 0); out.alive = true; } catch { out.alive = false; }
  }
  try { out.control = readFileSync(AB_CTL, 'utf8').trim() || 'run'; } catch { /* sem controle */ }
  // ultimas linhas do log: ciclo atual + modelo em curso
  try {
    const txt = readFileSync(AB_LOG, 'utf8');
    const lines = txt.split('\n').filter(Boolean).slice(-80);
    for (const l of lines.reverse()) {
      // (17/11) formato novo: "CICLO 12 (nivel L2)" e "A/B bonsai @ L2"
      let m = l.match(/CICLO\s+(\d+)(?:\s*\(nivel\s+(\w+)\))?/);
      if (m && out.cycle === null) {
        out.cycle = parseInt(m[1], 10);
        if (m[2]) out.nivel = m[2];
        continue;
      }
      m = l.match(/A\/B (?:para )?(\S+)(?:\s+@\s+(\w+))?/);
      if (m && out.current === null) {
        out.current = m[1];
        if (m[2]) out.nivel = m[2];
        continue;
      }
      m = l.match(/^\[(\d{2}:\d{2}:\d{2})\]/);
      if (m && out.last_ts === null) { out.last_ts = m[1]; continue; }
      if (out.cycle !== null && out.current !== null) break;
    }
  } catch { /* sem log */ }
  return out;
}

function abResults() {
  let txt = '';
  try { txt = readFileSync(AB_RES, 'utf8'); } catch { return []; }
  const rows = [];
  for (const l of txt.split('\n')) {
    if (!l.trim()) continue;
    try { rows.push(JSON.parse(l)); } catch { /* linha ruim */ }
  }
  return rows;
}

const AB_NIVEIS = ['L1', 'L2', 'L3'];

// (17/11) O veredito honesto: linha com "erro" (swap/checker/timeout) NAO e
// medida do modelo. "N failed" == reprovado; so "0 failed" aprova. O regex
// antigo (/\d+ passed/) marcava "1 failed, 3 passed" como aprovado.
function abVeredito(r) {
  if (r.erro) return 'erro';
  const chk = String(r.checker || '');
  if (!chk) return 'erro';
  const f = /(\d+) failed/.exec(chk);
  if (f) return parseInt(f[1], 10) === 0 ? 'pass' : 'fail';
  return /(\d+) passed/.test(chk) ? 'pass' : 'erro';
}

function abStats() {
  // (17/11) SO v3 conta. As linhas v2 sairam de um checker que exigia o
  // IMPOSSIVEL (a parede fechava o mapa) — contar aquilo como "0 aprovados
  // em 202 ciclos" era mentira duas vezes: nem o modelo nem o teste valiam.
  const rows = abResults().filter(r => r.ck === 'v3');
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
    if (r.dur > 0) { durs.push(r.dur); m.durs.push(r.dur); }
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
    const m = /(\d+)\s*,\s*(\d+)/.exec(r.stdout || '');
    if (m) { out.usado = +m[1]; out.total = +m[2]; out.livre = out.total - out.usado; }
  } catch { /* sem gpu */ }
  try {
    const r = spawnSync('nvidia-smi', ['--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'], { encoding: 'utf8', timeout: 4000 });
    out.apps = (r.stdout || '').split('\n').filter(Boolean).map(l => {
      const [pid, mb] = l.split(',').map(x => parseInt(x.trim(), 10));
      return { pid, mb };
    }).filter(x => x.pid);
  } catch { /* sem gpu */ }
  try {
    const r = spawnSync('ss', ['-ltnH'], { encoding: 'utf8', timeout: 3000 });
    for (const l of (r.stdout || '').split('\n')) {
      for (const port of [8080, 8092, 8095, 8096]) {
        if (new RegExp(':' + port + '\\b').test(l)) out.portas[port] = true;
      }
    }
  } catch { /* sem ss */ }
  out.residente = !!out.portas[8092];
  out.swap = out.portas[8080] ? 'bonsai' : out.portas[8096] ? 'mtp' : (out.residente ? 'residente' : 'livre');
  return out;
}

function abPatches() {
  try {
    const files = readdirSync(AB_DIR).filter(f => f.startsWith('patch-') && f.endsWith('.diff'));
    return files.map(f => {
      const st = statSync(AB_DIR + '/' + f);
      const m = f.match(/^patch-(.+?)-\d+\.diff$/);
      return { file: f, modelo: m ? m[1] : '?', bytes: st.size, ts: st.mtimeMs };
    }).sort((a, b) => b.ts - a.ts).slice(0, 12);
  } catch { return []; }
}

// ── pollers: transformam arquivos/processos em eventos ────────
const tails = { abLog: { off: 0 }, abRes: { off: 0 }, spawns: { off: 0 }, bus: { seen: new Set() }, sess: new Map() };

function pollAB() {
  const chunk = tailFrom(AB_LOG, tails.abLog);
  let lines = chunk.split('\n').filter(Boolean);
  // primeira leitura: o log pode ter centenas de KB de historico. Emite so
  // o fim, senao o buffer de eventos fica so com passado e o painel abre
  // ja "velho".
  if (tails.abLog.first !== false) {
    tails.abLog.first = false;
    lines = lines.slice(-60);
  }
  for (const line of lines) {
    let kind = 'ab', text = line.replace(/^\[[^\]]+\]\s*/, '');
    if (/ERRO|falh|failed|erro/i.test(text)) kind = 'fail';
    else if (/pronto|Result|passou|ok/i.test(text)) kind = 'ok';
    else if (/swap|VRAM|servidor/i.test(text)) kind = 'swap';
    evPush(kind, text, { src: 'ab' });
  }
  const res = tailFrom(AB_RES, tails.abRes);
  for (const line of res.split('\n').filter(Boolean)) {
    let r; try { r = JSON.parse(line); } catch { continue; }
    const v = abVeredito(r);
    evPush(v === 'pass' ? 'ok' : 'fail',
      `A/B ${r.modelo} @ ${r.nivel || 'L3'}: ${r.erro ? 'ERRO ' + r.erro : (r.checker || 'sem veredito')} (${r.dur || 0}s)`,
      { src: 'ab', modelo: r.modelo, nivel: r.nivel, veredito: v, checker: r.checker });
  }
}

function pidAlive(pid) {
  const n = Number(pid);
  if (!Number.isInteger(n) || n <= 0) return false;
  try { process.kill(n, 0); return true; } catch (e) { return e && e.code === 'EPERM'; }
}

// (25/11, medido) Estado EFETIVO de um spawn. O status gravado no checkpoint
// (starting/done/failed) nao diz se o trabalho ainda anda: medido no host, 4
// dos 29 state files estavam presos em "starting" ha 2,6 dias, sem processo
// vivo. O PID do opencode run (child_pid, novo no checkpoint) permite
// distinguir:
//   starting + pid vivo  -> running  (a work continua)
//   starting + pid morto -> dead     (morreu sem fechar o arquivo)
//   done/failed          -> o que foi gravado
//   sem pid (arquivo antigo) -> unknown (nao se presume nada)
function effectiveSpawnStatus(j) {
  const st = j && j.status;
  if (st === 'done' || st === 'failed') return st;
  if (st === 'starting') {
    return pidAlive(j.child_pid) ? 'running' : 'dead';
  }
  if (st === 'running') return 'running';
  if (st === 'idle') return 'idle';
  return 'unknown';
}

function pollSpawns() {
  const dir = HOME + '/.local/state/jarvis/spawns';
  let files = [];
  try { files = readdirSync(dir).filter(f => f.endsWith('.json')).sort(); } catch { return; }
  for (const f of files.slice(-6)) {
    if (tails.spawns.seen.has(f)) continue;
    tails.spawns.seen.add(f);
    let j; try { j = JSON.parse(readFileSync(dir + '/' + f, 'utf8')); } catch { continue; }
    const nome = j.name || j.codename || f.replace(/\.json$/, '');
    evPush('birth', `nasceu: ${nome}${j.model ? ' (modelo ' + j.model + ')' : ''}`, { src: 'spawn' });
    if (j.persona || j.profile) evPush('persona', `${nome} assumiu a persona ${j.persona || j.profile}`, { src: 'spawn' });
  }
}

async function pollSessions() {
  let map; try { map = await sessions(); } catch { return; }
  for (const a of roster()) {
    if (!a.session) continue;
    const s = map.get(a.session);
    if (!s) continue;
    const upd = s.time?.updated || 0;
    const prev = tails.sess.get(a.session);
    if (prev === undefined) { tails.sess.set(a.session, upd); continue; }
    if (upd > prev) {
      tails.sess.set(a.session, upd);
      const quem = a.codename || a.name || a.session.slice(0, 12);
      const model = s.model ? (typeof s.model === 'object' ? (s.model.modelID || s.model.id) : s.model) : null;
      evPush('say', `${quem}plies  · ${model || 'modelo ?'}${s.title ? ' · ' + String(s.title).slice(0, 80) : ''}`,
        { src: 'agent', agent: quem, session: a.session, model });
    }
  }
}

async function pollBus() {
  const b = await busMessages(20);
  for (const m of b.items || []) {
    const id = m.id || (m.from + ':' + (m.ts || '') + ':' + (m.text || m.body || ''));
    if (tails.bus.seen.has(id)) continue;
    tails.bus.seen.add(id);
    const txt = String(m.text || m.body || '').slice(0, 300);
    evPush('say', `${m.from || m.who || '?'} → ${m.to || 'todos'}: ${txt}`, { src: 'bus' });
  }
  if (tails.bus.seen.size > 400) tails.bus.seen = new Set([...tails.bus.seen].slice(-200));
}

let pollBusy = false;
async function pollAll() {
  if (pollBusy) return;
  pollBusy = true;
  try {
    pollAB();
    pollSpawns();
    await pollSessions();
    await pollBus();
  } catch (e) { /* poller nunca derruba o hub */ } finally { pollBusy = false; }
}

async function handler(req, res) {
  const url = new URL(req.url, 'http://127.0.0.1');
  const send = (code, body, type='text/html; charset=utf-8') => { res.writeHead(code, { 'Content-Type': type }); res.end(body); };
  if (req.method === 'GET' && url.pathname === '/.well-known/agent-card.json') {
    // (15/11) AGENT CARD (padrao A2A): o manifesto publico do hub. O
    // cliente le o card antes de delegar (paper 2609.00006: executor local
    // e agente A2A remoto pela mesma interface).
    return send(200, JSON.stringify({
      name: 'agent-hub JARVIS',
      description: 'Hub de agentes da casa: cria agentes, mostra o bus e acorda sessoes.',
      url: 'http://' + (process.env.HUB_PUBLIC_URL || '127.0.0.1:' + PORT),
      version: '1.0.0',
      protocolVersion: 'a2a/1.0',
      capabilities: { streaming: false, pushNotifications: false,
        stateTransitionHistory: true,
        skills: [
          { id: 'agents.list', name: 'listar agentes' },
          { id: 'agents.spawn', name: 'criar agente' },
          { id: 'bus.read', name: 'ler o bus' },
          { id: 'agent.wake', name: 'acordar agente' },
        ] },
      securitySchemes: { hubToken: { type: 'apiKey', in: 'header',
        name: 'x-agent-hub-token' } },
      defaultInputModes: ['text'],
      defaultOutputModes: ['text'],
    }), 'application/json');
  }
  // F33: geracao real com o checkpoint word-level (playground do /lab)
  if (req.method === 'GET' && url.pathname === '/lab/generate') {
    const prompt = String(url.searchParams.get('prompt') || 'Once upon a time').slice(0, 120);
    const n = Math.min(120, Math.max(10, parseInt(url.searchParams.get('n') || '60', 10)));
    try {
      const { execFileSync } = await import('node:child_process');
      // A GPU e do projeto e pode estar ocupada por um treino: gerar em CPU
      // (18s medidos para 80 tokens) evita OOM e undefined no playground.
      const gcc = execFileSync('bash', ['-lc',
        'ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1'],
        { encoding: 'utf8' }).trim();
      const out = execFileSync('/home/nixos/.venvs/finetune/bin/python', [
        HOME + '/projects/nixos-ai/scripts/f33-generate.py', prompt, String(n),
      ], { encoding: 'utf8', timeout: 120000,
           env: { ...process.env, CUDA_VISIBLE_DEVICES: '',
                  LD_LIBRARY_PATH: gcc + ':/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib',
                  TRITON_LIBCUDA_PATH: '/run/opengl-driver/lib' } });
      return send(200, out.trim());
    } catch (e) {
      return send(500, JSON.stringify({error: String(e).slice(0,240),
        hint: 'geracao em CPU; se ainda falhar, ver /home/nixos/work/hybrid/f33-generate.log'}));
    }
  }
  // F30: dashboard do laboratorio do LLM do zero (servido pelo proprio hub)
  if (req.method === 'GET' && (url.pathname === '/lab' || url.pathname === '/lab/')) {
    try {
      const lab = readFileSync(HOME + '/projects/nixos-ai/tools/lab-timeline/index.html', 'utf8');
      return send(200, lab);
    } catch { return send(404, 'lab dashboard ausente'); }
  }
  if (req.method === 'GET' && url.pathname === '/') {
    // (16/11) UI em arquivo proprio (agent-hub-ui.html), com o HTML inline
    // como fallback se o arquivo nao estiver no disco.
    try {
      const ui = readFileSync(UI_FILE, 'utf8');
      return send(200, ui);
    } catch { return send(200, HTML); }
  }
  // (16/11) FLUXO DE EVENTOS: SSE. O painel ve o happening em tempo real
  // (nascimento, persona, fala, tool, swap, reload, falha, sucesso) sem
  // polling de pagina inteira.
  if (req.method === 'GET' && url.pathname === '/api/tasks') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    return send(200, JSON.stringify({ ok:true, tasks: TASKS.slice(0,200) }), 'application/json');
  }
  if (req.method === 'POST' && url.pathname === '/api/tasks') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    let body = {};
    try { body = JSON.parse(await readBody(req) || '{}'); } catch {}
    const t = taskPush({ title: body.title, agent: body.agent, status: body.status || 'pending', note: body.note, by: body.by || 'ui' });
    return send(200, JSON.stringify({ ok:true, task: t }), 'application/json');
  }
  if (req.method === 'PATCH' && url.pathname === '/api/tasks') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    let body = {};
    try { body = JSON.parse(await readBody(req) || '{}'); } catch {}
    if (!body.id) return send(400, JSON.stringify({ ok:false, error:'id required' }), 'application/json');
    const prev = TASKS.find(x=>x.id===body.id);
    if (!prev) return send(404, JSON.stringify({ ok:false, error:'not found' }), 'application/json');
    const t = taskPush({ ...prev, ...body, id: prev.id });
    return send(200, JSON.stringify({ ok:true, task: t }), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/events/stream') {
    const t = url.searchParams.get('token') || '';
    if (!sameSecret(t, hubToken())) { res.writeHead(401); return res.end('unauthorized'); }
    res.writeHead(200, {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    });
    res.write('data: ' + JSON.stringify({ kind: 'hello', text: 'conectado', ts: Date.now() }) + '\n\n');
    // historico recente: quem abre o painel nao comeca do zero
    for (const ev of EVBUF.slice(-120)) {
      try { res.write('data: ' + JSON.stringify(ev) + '\n\n'); } catch { break; }
    }
    evClients.add(res);
    const ka = setInterval(() => { try { res.write(': ka\n\n'); } catch { /* ignore */ } }, 20000);
    req.on('close', () => { clearInterval(ka); evClients.delete(res); });
    return;
  }
  // (17/11) ROTACAO DE CREDENCIAL — a frota troca de key/modelo sem expor valor.
  // O script key-rotate.py nunca imprime a chave (so id/label/active).
  if (req.method === "POST" && url.pathname === "/api/key/rotate") {
    if (!authorized(req)) return send(401, JSON.stringify({ error: "token required" }), "application/json");
    let body = {};
    try { const raw = await readBody(req); body = JSON.parse(raw || "{}"); } catch { body = {}; }
    const provider = /^[a-z0-9_-]{1,40}$/i.test(String(body.provider || "")) ? String(body.provider) : "nvidia";
    const action = ["list","status","next","verify"].includes(body.action) ? body.action : "next";
    const args = ["/home/nixos/projects/nixos-ai/scripts/key-rotate.py", action, "--provider", provider];
    if (body.dry_run) args.push("--dry-run");
    try {
      const r = spawnSync("python3", args, { encoding: "utf8", timeout: 60000 });
      return send(r.status === 0 ? 200 : 500, JSON.stringify({
        ok: r.status === 0, provider, action,
        out: String(r.stdout || "").slice(0, 500),
        err: String(r.stderr || "").slice(0, 200),
      }), "application/json");
    } catch (e) { return send(500, JSON.stringify({ ok: false, error: String(e) }), "application/json"); }
  }
  // (20/11) CAPABILITY CARDS A2A — contratos por host, gerados de evidencia
  // viva em ai-mesh/manifests/mesh/cards. Read-only; bloqueia marcadores de
  // credencial antes de responder (cards nao devem conter segredo algum).
  const CARDS_DIR = process.env.CARDS_DIR || join(HOME, "projects/ai-mesh/manifests/mesh/cards");
  const CARD_SECRET = /"(?:pubkey|private_key|api_key|authorization|password|secret|access_token|refresh_token)"\s*:|Bearer\s+[A-Za-z0-9._-]{12,}|sk-[A-Za-z0-9]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|"token"\s*:\s*"[^"]{8,}"/i;
  function cardFile(name) {
    if (!/^[A-Za-z0-9._-]+\.json$/.test(name || '')) return null;
    const p = join(CARDS_DIR, name);
    return p.startsWith(CARDS_DIR) ? p : null;
  }
  if (req.method === 'GET' && url.pathname === '/api/cards') {
    const wanted = url.searchParams.get('name');
    try {
      if (wanted) {
        const p = cardFile(wanted);
        if (!p) return send(400, '{"error":"nome invalido"}', 'application/json');
        const raw = readFileSync(p, 'utf8');
        if (CARD_SECRET.test(raw)) return send(503, '{"error":"card contem marcador de credencial"}', 'application/json');
        return send(200, raw, 'application/json');
      }
      const files = readdirSync(CARDS_DIR).filter(f => f.endsWith('.json')).sort();
      const cards = files.map(f => {
        const j = JSON.parse(readFileSync(join(CARDS_DIR, f), 'utf8'));
        return { file: f, name: j.name || f.replace(/\.json$/, ''),
          host_kind: j.host_kind || 'unknown', status: j.status || 'unknown',
          version: j.version || '', description: j.description || '',
          services: (j.services || []).map(x => String(x.name || '?') + ':' + String(x.port || '?')),
          skills: (j.skills || []).length, scripts: (j.scripts || []).length,
          url: '/api/cards?name=' + encodeURIComponent(f) };
      });
      const body = JSON.stringify({ cards, count: cards.length, source: CARDS_DIR });
      if (CARD_SECRET.test(body)) return send(503, '{"error":"payload contem marcador de credencial"}', 'application/json');
      return send(200, body, 'application/json');
    } catch (e) {
      return send(503, JSON.stringify({ error: 'cards indisponiveis', detail: String(e) }), 'application/json');
    }
  }
  // (21/11) PENDENCIAS DA AUDITORIA — fonte versionada, sem segredo, somente
  // leitura. Mesmo padrao de /api/cards: validacao de PATH, JSON e bloqueio
  // de marcadores de credencial antes de responder.
  function pendingFiles() {
    return {
      debt: join(HOME, 'projects/nixos-ai/docs/audit/TECHNICAL-DEBT.md'),
      state: join(HOME, 'projects/nixos-ai/docs/audit/PROJECT-AUDIT-STATE.md'),
      gaps: join(HOME, "projects/ai-mesh/docs/auto-improve-gaps.jsonl"),
      resolution: join(HOME, "projects/ai-mesh/docs/auto-improve-resolution.json"),
      backlog: join(HOME, 'projects/nixos-ai/docs/backlog.jsonl'),
    };
  }
  if (req.method === 'GET' && url.pathname === '/api/pending') {
    try {
      const fonts = pendingFiles();
      const debtRaw = readFileSync(fonts.debt, 'utf8');
      const gapsRaw = readFileSync(fonts.gaps, 'utf8');
      const stateRaw = readFileSync(fonts.state, 'utf8');
      const openItems = [];
      let section = '';
      for (const line of debtRaw.split(/\r?\n/)) {
        const h = line.match(/^##\s+(P[0-3])\b/);
        if (h) { section = h[1]; continue; }
        if (/^- /.test(line) && section && !/FEITO|rejeitada|corrigida/i.test(line))
          openItems.push({ kind: 'debt', level: section, text: line.replace(/^- /, '').slice(0, 240) });
      }
      const gaps = gapsRaw.split(/\r?\n/).filter(l => l.trim() && !l.trim().startsWith('#'))
        .map(l => { try { const d = JSON.parse(l); return {
            kind: 'gap', id: d.id, source: d.source, priority: d.priority,
            task: String(d.task || '').slice(0, 240) }; } catch (e) { return null; } })
        .filter(Boolean);
      const next = stateRaw.split(/\r?\n/).filter(l => /^\d+\. /.test(l)).slice(0, 5)
        .map(l => ({ kind: 'next', text: l.replace(/^\d+\. /, '').slice(0, 240) }));
      // Fonte unica e versionada: o snapshot publicado pelo auto-improve no
      // repo ai-mesh. Nao ha estado proprio do hub nem segundo arquivo local.
      let resolution = null;
      try {
        const r = JSON.parse(readFileSync(fonts.resolution, 'utf8'));
        resolution = { kind: 'resolution', arquivadas: Number(r.arquivadas || 0),
          pendentes: Number(r.pendentes_de_fechamento || 0),
          evidence_ok: r.evidence_ok === true, gate_ok: r.gate_ok === true,
          error: String(r.error || ''),
          ts: r.ts || '', fonte: r.source || '' };
      } catch (e) { resolution = { kind: 'resolution', indisponivel: true }; }
      const result = { items: openItems.concat(gaps, next, resolution ? [resolution] : []),
        counts: { debt: openItems.length, gaps: gaps.length, next: next.length,
                  resolution_arquivadas: resolution?.arquivadas ?? null,
                  resolution_pendentes: resolution?.pendentes ?? null,
                  resolution_evidence_ok: resolution?.evidence_ok ?? null,
                  resolution_gate_ok: resolution?.gate_ok ?? null },
        resolution,
        sources: ['docs/audit/TECHNICAL-DEBT.md', 'docs/audit/PROJECT-AUDIT-STATE.md',
                  'ai-mesh/docs/auto-improve-gaps.jsonl',
                  'ai-mesh/docs/auto-improve-resolution.json'],
        state_url: '/api/pending?name=PROJECT-AUDIT-STATE.md',
        documentation: 'docs/audit/PROJECT-AUDIT-STATE.md' };
      const body = JSON.stringify(result);
      if (CARD_SECRET.test(body)) return send(503, '{"error":"payload contem marcador de credencial"}', 'application/json');
      return send(200, body, 'application/json');
    } catch (e) {
      return send(503, JSON.stringify({ error: 'pendencias indisponiveis', detail: String(e) }), 'application/json');
    }
  }
  if (req.method === 'GET' && url.pathname === '/api/pending/state') {
    try {
      const raw = readFileSync(join(HOME, 'projects/nixos-ai/docs/audit/PROJECT-AUDIT-STATE.md'), 'utf8');
      if (CARD_SECRET.test(raw)) return send(503, '{"error":"estado contem marcador de credencial"}', 'application/json');
      return send(200, raw, 'text/markdown; charset=utf-8');
    } catch (e) { return send(503, String(e), 'text/plain; charset=utf-8'); }
  }
  // (17/11) CASA: indice unico (ai-mesh/index/house.json). A MESMA fonte
  // alimenta o CLI `house`, a pagina /house e a tool coord_house do MCP.
  // Leitura read-only: o indice nao tem segredo; o token do hub nao e exposto.
  if (req.method === "GET" && url.pathname === "/api/house") {
    const p = process.env.HOUSE_INDEX || join(HOME, "projects/ai-mesh/index/house.json");
    try {
      const raw = readFileSync(p, "utf8");
      JSON.parse(raw);
      return send(200, raw, "application/json");
    } catch (e) {
      return send(503, JSON.stringify({ error: "house index indisponivel", detail: String(e), path: p }), "application/json");
    }
  }
  if (req.method === "GET" && url.pathname === "/house") {
    try {
      return send(200, readFileSync(join(__DIR, "house.html"), "utf8"), "text/html; charset=utf-8");
    } catch (e) {
      return send(500, "house.html ausente em " + join(__DIR, "house.html") + ": " + String(e));
    }
  }
  // (16/11) ESTADO AO VIVO DO A/B: loop vivo, ciclo, modelo em curso,
  // estatistica por modelo (taxa de aprovacao, tempo medio) e os patches.
  if (req.method === 'GET' && url.pathname === '/api/ab/live') {
    const loop = abLoopState();
    const { models, stats, niveis, matriz } = abStats();
    let log = [];
    try { log = readFileSync(AB_LOG, 'utf8').split('\n').filter(Boolean).slice(-40); } catch { /* sem log */ }
    const resultados = abResults().slice(-14).reverse().map(r => ({
      modelo: r.modelo, nivel: r.nivel || 'L3', dur: r.dur, ts: r.ts,
      veredito: abVeredito(r), checker: r.checker || r.erro || '',
      patch_bytes: r.patch_bytes || 0,
    }));
    return send(200, JSON.stringify({ loop, models, stats, niveis, matriz, gpu: abGpu(),
      resultados, patches: abPatches(), log }), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/ab/patch') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required' }), 'application/json');
    const f = String(url.searchParams.get('file') || '');
    if (!/^patch-[A-Za-z0-9_.-]+\.diff$/.test(f)) return send(400, JSON.stringify({ error: 'file invalido' }), 'application/json');
    try {
      const body = readFileSync(AB_DIR + '/' + f, 'utf8');
      return send(200, body, 'text/plain; charset=utf-8');
    } catch (e) { return send(404, JSON.stringify({ error: 'patch nao encontrado' }), 'application/json'); }
  }
  // (16/11) COMANDO DO A/B: pausar / retomar / parar / rodar agora.
  // O canal e' um arquivo de controle (o loop le a cada ciclo) — nao matar
  // processo: o loop continua vivo e o dono ve o estado.
  if (req.method === 'POST' && url.pathname === '/api/ab/control') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required' }), 'application/json');
    let body = {};
    try { const raw = await readBody(req); body = JSON.parse(raw || '{}'); } catch { body = {}; }
    const action = String(body.action || '');
    const model = body.model ? String(body.model) : '';
    try {
      if (action === 'pause') { writeFileSync(AB_CTL, 'pause'); return send(200, JSON.stringify({ ok: true, message: 'A/B pausado' }), 'application/json'); }
      if (action === 'resume') { writeFileSync(AB_CTL, 'run'); return send(200, JSON.stringify({ ok: true, message: 'A/B retomado' }), 'application/json'); }
      if (action === 'stop') {
        const st = abLoopState();
        if (st.pid) { try { process.kill(st.pid, 'SIGTERM'); } catch { /* ja morreu */ } }
        writeFileSync(AB_CTL, 'stop');
        return send(200, JSON.stringify({ ok: true, message: 'A/B parado' }), 'application/json');
      }
      if (action === 'run') {
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
      }
      return send(400, JSON.stringify({ error: 'acao desconhecida: ' + action }), 'application/json');
    } catch (e) { return send(500, JSON.stringify({ error: String(e) }), 'application/json'); }
  }
  // (16/11) COMANDO DE AGENTE: acordar / recarregar / trocar modelo.
  // 'wake' usa o caminho canonico da casa (deliver.py) — nao injeta direto.
  if (req.method === 'POST' && url.pathname === '/api/agent/command') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required' }), 'application/json');
    let body = {};
    try { const raw = await readBody(req); body = JSON.parse(raw || '{}'); } catch { body = {}; }
    const action = String(body.action || 'wake');
    const name = String(body.name || '');
    const text = String(body.text || '');
    if (action === 'wake') {
      if (!name) return send(400, JSON.stringify({ error: 'alvo obrigatorio' }), 'application/json');
      if (!text.trim()) return send(400, JSON.stringify({ error: 'texto obrigatorio' }), 'application/json');
      const out = await wake(name, text);
      evPush('say', `comando para ${name}: ${text.slice(0, 200)}`, { src: 'cmd' });
      return send(out.status, JSON.stringify(out.body), 'application/json');
    }
    if (action === 'reload') {
      // (16/11) reload: injeta o comando de reload do proprio opencode na
      // sessao (o mesmo que o /reload do TUI faz: config + plugins).
      const out = await wake(name, '/reload');
      evPush('reload', `reload pedido para ${name}`, { src: 'cmd' });
      return send(out.status, JSON.stringify(out.body), 'application/json');
    }
    if (action === 'swap') {
      // troca de modelo: pede ao agente para trocar (o proprio opencode
      // aplica o /model). Sem sessao, responde o que fazer.
      const model = String(body.model || '').trim();
      const out = await wake(name, model ? ('/model ' + model) : '/model');
      evPush('swap', `troca de modelo pedida para ${name}${model ? ' -> ' + model : ''}`, { src: 'cmd' });
      return send(out.status, JSON.stringify(out.body), 'application/json');
    }
    return send(400, JSON.stringify({ error: 'acao desconhecida: ' + action }), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/mission') {
    const j = await agentsJSON().catch(e => ({ servers: { opencode: false }, agents: [], error: String(e) }));
    const agents = j.agents || [];
    const now = Date.now();
    const byStatus = agents.reduce((acc,a)=>{ acc[a.status||'unknown']=(acc[a.status||'unknown']||0)+1; return acc; },{});
    const recentEvents = EVBUF.slice(-30).reverse();
    const failures = EVBUF.filter(e=>['fail','error'].includes(String(e.kind||'').toLowerCase())).slice(-10).reverse();
    const stale = agents.filter(a=>a.updated && (now-a.updated)>30*60*1000 && !a.unclaimed).slice(0,10).map(a=>({name:a.codename||a.name, session:a.session, age_s:Math.round((now-a.updated)/1000), status:a.status, model:a.model}));
    const summary = {
      ok: true,
      ts: now,
      servers: j.servers || {},
      counts: { total: agents.length, roster: agents.filter(a=>!a.unclaimed).length, unclaimed: agents.filter(a=>a.unclaimed).length, ...byStatus },
      stale,
      failures,
      recentEvents,
      links: { lab:'/lab', house:'/house', agents:'/api/agents', bus:'/api/bus?limit=40' },
      papers: { note:'AgentGUI/AgentOps/AgentSysOps/GovernanceTelemetry + Lacuna alien-sampling (2603.01092) indexed in host Books/RAG' }
    };
    return send(200, JSON.stringify(summary), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/agents') { const j = await agentsJSON().catch(e => ({ servers: { opencode: false }, agents: [], error: String(e) })); return send(200, JSON.stringify(j), 'application/json'); }
  if (req.method === 'GET' && url.pathname === '/api/transcript') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    const s = url.searchParams.get('session');
    if (!s) return send(400, JSON.stringify({ error: 'session required' }), 'application/json');
    try {
      const { status, json } = await oc(`/api/session/${encodeURIComponent(s)}/message`);
      const all = json?.data || [];
      // (19/11) A API devolve as mensagens NEWEST-FIRST: o log chegava de
      // cabeca para baixo e repetia turnos. Ordena por epoch (asc), dedupa
      // por conteudo normalizado e devolve um log de conversa legivel.
      // (22/11, medido) a API e NEWEST-FIRST: slice(-30) pegava as 30
      // MAIS ANTIGAS e o log diario perdia o fim da conversa (sessao de 50
      // mensagens parava em 02:15 quando a conversa ia ate 02:22). O slice
      // correto e cabeca do array; a ordenacao abaixo deixa a leitura asc.
      const msgs = all.slice(0, 30);
      const rows = [];
      for (const m of msgs) {
        const epoch = m.time?.created ? (m.time.created > 1e12 ? m.time.created : m.time.created * 1000) : 0;
        const ts = epoch ? new Date(epoch).toLocaleTimeString('pt-BR') : '';
        const t = (m.type || '?').toUpperCase();
        let line = '';
        // (19/11) V2: o texto do usuario vem em `m.text`, nao em
        // `m.payload.text` (por isso o log dos agentes novos saia vazio).
        if (t === 'USER' || t === 'IDLE') {
          const txt = m.payload?.text || m.text || '';
          if (m.error) {
            line = `[${ts}] ERROR: ${String(m.error.message || m.error.type || '').slice(0, 500)}`;
          } else if (txt) {
            line = `[${ts}] USER: ${txt.slice(0, 400)}`;
          }
        } else if (t === 'ASSISTANT') {
          const parts = (m.content || []).map(c => {
            if (c.type === 'text') return c.text;
            if (c.type === 'tool') return '⚙ tool: ' + c.name + ' ' + JSON.stringify(c.state?.input || {}).slice(0, 180);
            return '[' + c.type + ']';
          }).filter(Boolean);
          if (m.error) parts.push('ERROR: ' + String(m.error.message || m.error.type || '').slice(0, 400));
          line = `[${ts}] ASST:\n${parts.join('\n').slice(0, 900)}`;
        }
        if (line) rows.push({ epoch, line });
      }
      rows.sort((a, b) => a.epoch - b.epoch);
      const seen = new Set();
      const lines = [];
      for (const r of rows) {
        // remove so o horario antes de comparar: mesmo texto em outro minuto
        // e repeticao real (o agente repetiu o turno) e deve sumir do log.
        const key = r.line.replace(/^\[[^\]]+\]\s*/, '').trim().slice(0, 600);
        if (seen.has(key)) continue;
        seen.add(key);
        lines.push(r.line);
      }
      return send(200, JSON.stringify({ session: s, status, lines, ordered: 'asc', total: all.length }), 'application/json');
    } catch (e) { return send(502, JSON.stringify({ error: String(e) }), 'application/json'); }
  }
  if (req.method === 'GET' && url.pathname === '/api/dungeon-ab') {
    // (15/11) O A/B do dungeon roda PELO PAINEL e DENTRO do sistema novo:
    // nightwatch.dungeon usa a FILA do sistema (TaskQueue) + o Harness do
    // proprio nightwatch, com o CHECKER FIXADO (pytest test_astar.py 4/4)
    // e o SANDBOX (worktree por lane). Nada de script solto.
    try {
      const j = await pyMod('nightwatch.dungeon', ['report'], 90000);
      // (16/11) Insights do vídeo Codacus aplicados ao A/B:
      j.insights_video = {
        fonte: "Is this how Local AI reaches Frontier Capabilities? (Codacus, 2026)",
        conclusao_maior: "O planejador e o elo fraco. Job longo/multi-etapa = modelo grande; job curto + resposta verificável = especialista pequeno.",
        regras: [
          "O especialista precisa ver o PEDIDO ORIGINAL inteiro (nao um resumo)",
          "Quem planeja precisa ter modelo forte (API para job longo)",
          "Sandbox + checker travado ANTES de rodar (pytest test_astar.py 4/4)",
          "Dê search ao time: fatos nao cabem em modelo pequeno (RAG + corpus offline)",
          "Peso-editing nao resolve habito espalhado num job longo - consertar o plano, nao o neuronio"
        ],
        resultado_ab_medido: {
          mtp: "4/4 passou, ~314s, implementou A* com heapq",
          bonsai: "4/4 passou, ~160s, implementou A* com heapq (idêntico)",
          conclusao: "Ambos fecham o job com retry baseado no checker. O Bonsai foi 2x mais rápido."
        }
      };
      return send(200, JSON.stringify(j), 'application/json');
    } catch (e) {
      return send(200, JSON.stringify({ erro: String(e) }), 'application/json');
    }
  }
  if (req.method === 'POST' && url.pathname === '/api/dungeon-ab') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    const m = url.searchParams.get('model') || 'mtp';
    const PY = process.env.PY_BIN || '/etc/profiles/per-user/nixos/bin/python3';
    const ROOT = '/home/nixos/projects/nixos-ai';
    const env = { ...process.env, PYTHONPATH: ROOT + '/modules/ai/jarvis/src' };
    const { spawn } = await import('node:child_process');
    // assincrono: um A/B com modelo local leva minutos; a UI nao pode esperar.
    const child = spawn(PY, ['-m', 'nightwatch.dungeon', 'run', '--model', String(m)],
      { detached: true, stdio: 'ignore', cwd: ROOT, env });
    child.unref();
    return send(200, JSON.stringify({ ok: true, status: 'running', model: String(m), pid: child.pid }), 'application/json');
  }

  // (16/11) POST /api/dungeon-ab-retry — roda o A/B com retry baseado no checker
  // no lado do hub. Dispara o dungeon.py, verifica o resultado, e re-dispara
  // com contexto do erro se falhar (máximo maxRetries tentativas).
  if (req.method === 'POST' && url.pathname === '/api/dungeon-ab-retry') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    const m = url.searchParams.get('model') || 'mtp';
    const maxRetries = parseInt(url.searchParams.get('maxRetries') || '3');
    const PY = process.env.PY_BIN || '/etc/profiles/per-user/nixos/bin/python3';
    const ROOT = '/home/nixos/projects/nixos-ai';
    const env = { ...process.env, PYTHONPATH: ROOT + '/modules/ai/jarvis/src' };
    const { execSync } = await import('node:child_process');

    let lastResult = null;
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const out = execSync(PY + ' -m nightwatch.dungeon run --model ' + m, {
          cwd: ROOT, env, timeout: 300000, maxBuffer: 10 * 1024 * 1024
        });
        lastResult = JSON.parse(out.toString());
        if (lastResult.tasks_completed > 0) break;
      } catch (e) {
        lastResult = { error: String(e), attempt: attempt + 1 };
      }
      await new Promise(r => setTimeout(r, 5000));
    }
    return send(200, JSON.stringify({ ok: lastResult && lastResult.tasks_completed > 0, model: m, attempts: maxRetries, result: lastResult }), 'application/json');
  }
  // (20/11) DESAFIO DA FROTA: estado duravel do runner canonico
  // `scripts/fleet-challenge.py`. Read-only; sem spawn e sem segredos.
  if (req.method === 'GET' && url.pathname === '/api/fleet-challenge') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required' }), 'application/json');
    const f = HOME + '/.local/state/jarvis/fleet-challenge/run.json';
    try {
      const j = JSON.parse(readFileSync(f, 'utf8'));
      return send(200, JSON.stringify(j), 'application/json');
    } catch (e) {
      return send(200, JSON.stringify({ status: 'not-started', error: String(e) }), 'application/json');
    }
  }
  if (req.method === 'GET' && url.pathname === '/api/state') {
    // (15/11) TUDO LIGADO num estado so: agentes (roster), claims/board
    // (bus), fila da casa, kanban (nightwatch workitems), spawns, servicos e
    // catalogo de modelos + rate-limit. Agrega o que a casa JA tem — nao
    // duplica nada.
    // (15/11) cache de 30s: o state agrega o workitem da casa (que le a
    // fila) — sem cache, cada poll da UIpressionava o Nix e o DB.
    const now = Date.now();
    if (stateCache.value && now - stateCache.at < 120000) {
      return send(200, JSON.stringify(stateCache.value), 'application/json');
    }
    const j = await pyJSON("hub-state.py", [], 180000).catch(e => ({ error: String(e) }));
    stateCache = { at: now, value: j };
    return send(200, JSON.stringify(j), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/models') {
    // Catalogo REAL de modelos (ctx/output medidos no endpoint, tier,
    // capabilities, good_for) + medidor de rate-limit do nv-gate + cooldowns.
    const j = await pyJSON("model-catalog.py", [], 90000).catch(e => ({ error: String(e) }));
    return send(200, JSON.stringify(j), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/profiles') {
    // Perfis disponíveis para spawn, lidos do roster (mbti/persona) + redteam.
    // Nao e hardcoded: reflete o que a casa realmente tem.
    const perfis = new Set(['redteam']);
    try {
      const raw = readFileSync(ROSTER, 'utf8');
      const d = JSON.parse(raw);
      for (const a of (d.agents || [])) {
        if (a.mbti) perfis.add(String(a.mbti));
        if (a.persona) perfis.add(String(a.persona));
      }
    } catch { /* roster ainda vazio: fica so com redteam */ }
    return send(200, JSON.stringify({ perfis: [...perfis].sort() }), 'application/json');
  }
  if (req.method === 'POST' && url.pathname === '/api/spawn') {
    // Cria um agente NOVO: modelo escolhido (catalogo/cooldown), persona
    // MBTI e system prompt inicial — a experiencia do Grok Bot.
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    let raw = ''; for await (const chunk of req) {
      raw += chunk;
      if (raw.length > BODY_MAX) return send(413, JSON.stringify({ error: 'body grande demais' }), 'application/json');
    }
    let body = {};
    try { body = JSON.parse(raw || '{}'); } catch { return send(400, JSON.stringify({ error: 'json invalido' }), 'application/json'); }
    const task = String(body.task || '');
    if (!task.trim()) return send(400, JSON.stringify({ error: 'task obrigatoria' }), 'application/json');
    // (15/11) O PEDIDO E INPUT EXTERNO: passa pelo guard da frota antes
    // de virar tarefa de agente. O guard decide: intrusao bloqueia,
    // moralizacao vira aviso no prompt do agente novo.
    let guard = { clean: true, hits: [], padroes: [], categoria: 'limpo' };
    try {
      const { spawnSync } = await import('node:child_process');
      const g = spawnSync('python3', ['/home/nixos/projects/nixos-ai/scripts/agent_guard.py',
        '--scan', task, '--json'], { encoding: 'utf8', timeout: 20000 });
      if (g.status === 0 || g.stdout) {
        const v = JSON.parse(g.stdout || '{}');
        if (v && v.hits && v.hits.length) {
          return send(451, JSON.stringify({
            error: 'guard: pedido bloqueado (termo de intrusao)',
            termos: v.hits.map((x) => x.termo),
          }), 'application/json');
        }
        guard = v || guard;
      }
    } catch (e) {
      /* fail-open: o guard no spawn e o agente-spawn.py tambem bloqueia */
    }
    const rate = spawnAllowed(String(req.socket.remoteAddress || '?'));
    if (!rate.ok) return send(429, JSON.stringify({ error: rate.error }), 'application/json');
    const args = ['--task', task];
    if (body.name) args.push('--name', String(body.name));
    if (body.requester) args.push('--requester', String(body.requester));
    // (15/11) o solicitante NAO escolhe persona/modelo/lane: o papel vem do
    // catalogo e o modelo do model_for_task (o override fica para uso local
    // com JARVIS_SPAWN_ALLOW_OVERRIDE=1).
    if (process.env.JARVIS_SPAWN_ALLOW_OVERRIDE === '1') {
      if (body.model) args.push('--model', String(body.model));
      if (body.lane) args.push('--lane', String(body.lane));
      if (body.profile) args.push('--profile', String(body.profile));
    }
    if (body.dry_run) args.push('--dry-run');
    if (body.dry_run) {
      const j = await pyJSON("agent-spawn.py", args, 120000).catch(e => ({ ok: false, error: String(e) }));
      return send(200, JSON.stringify(j), 'application/json');
    }
    // (15/11) ASSINCRONO: um spawn com Nemotron leva minutos; a UI nao pode
    // ficar esperando. O python grava o estado em
    // ~/.local/state/jarvis/spawns/<ses>.json e a UI le por /api/spawns.
    const PY = process.env.PY_BIN || "/etc/profiles/per-user/nixos/bin/python3";
    const { spawn } = await import('node:child_process');
    const child = spawn(PY, ['/home/nixos/projects/nixos-ai/scripts/agent-spawn.py', ...args], {
      detached: true, stdio: 'ignore', cwd: '/home/nixos/projects/nixos-ai',
    });
    child.unref();
    return send(200, JSON.stringify({ ok: true, status: 'starting', pid: child.pid }), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/spawns') {
    // Estado dos spawns recentes (o spawn e lento: o hub responde na hora).
    // (25/11, medido) O status gravado pelo spawn (starting/done/failed) nao
    // basta para o leitor: um spawn em "starting" pode estar rodando ou
    // morto ha dias. Medido no host: 4 dos 29 state files estavam presos em
    // "starting" ha 2,6 dias, sem NENHUM processo vivo. Agora o PID do
    // opencode run vai no checkpoint e o hub deriva o estado EFETIVO:
    //   starting + pid vivo  -> running  (a work ainda esta andando)
    //   starting + pid morto -> dead     (o spawn morreu sem fechar)
    //   done/failed          -> igual
    const out = [];
    try {
      const dir = HOME + '/.local/state/jarvis/spawns';
      const files = readdirSync(dir).filter(f => f.endsWith('.json')).sort();
      for (const f of files.slice(-12)) {
        try {
          const j = JSON.parse(readFileSync(dir + '/' + f, 'utf8'));
          j.effective_status = effectiveSpawnStatus(j);
          out.push(j);
        } catch { /* ignora */ }
      }
    } catch { /* sem spawns ainda */ }
    return send(200, JSON.stringify({ spawns: out }), 'application/json');
  }
  if (req.method === 'GET' && url.pathname === '/api/bus') {
    // (15/11) a conversa da frota. Publica: o bus e append-only e as
    // mensagens sao coord-json (kind=msg/status/claim...). Nao leva
    // token: nao expoe transcript de sessao nem escreve nada.
    const lim = Math.min(100, parseInt(url.searchParams.get('limit') || '40', 10) || 40);
    const b = await busMessages(lim);
    let journal = null;
    try { journal = JSON.parse(readFileSync(HOME + '/.local/state/jarvis/bus-journal/manifest.json', 'utf8')); } catch { /* sem captura ainda */ }
    return send(200, JSON.stringify({ items: b.items, cached: b.cached, err: b.err, journal }), 'application/json');
  }
  if (req.method === 'POST' && url.pathname === '/api/wake') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    let raw = ''; for await (const chunk of req) {
      raw += chunk;
      if (raw.length > BODY_MAX) return send(413, JSON.stringify({ error: 'body grande demais' }), 'application/json');
    }
    try {
      const { name, text } = JSON.parse(raw || '{}');
      const out = await wake(name, text);
      // (20/11) caminho `hub-wake`: entrega direta na sessao tambem e
      // conversa da frota e deve aparecer no Bus com origem etiquetada.
      try {
        const line = JSON.stringify({ ts: new Date().toISOString(), name,
          to: (out.body && out.body.name) || name,
          text: String(text || '').replace(/\s+/g, ' ').slice(0, 500) }) + '\n';
        writeFileSync(HOME + '/.local/state/jarvis/hub-messages.jsonl', line, { flag: 'a' });
      } catch { /* log e best-effort; a entrega ja aconteceu */ }
      return send(out.status, JSON.stringify(out.body), 'application/json');
    } catch (e) { return send(400, JSON.stringify({ error: String(e) }), 'application/json'); }
  }
  // (19/11) FECHAR SESSAO — pedido original 15/11 ('abrir e fechar sessao').
  // API medida: DELETE /api/session/{id} existe no OpenCode V2 (openapi.json).
  if (req.method === 'POST' && url.pathname === '/api/session/close') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required' }), 'application/json');
    let raw = ''; for await (const chunk of req) {
      raw += chunk;
      if (raw.length > BODY_MAX) return send(413, '{"error":"body grande demais"}', 'application/json');
    }
    try {
      const { name, session } = JSON.parse(raw || '{}');
      let sid = session || '';
      if (!sid && name) {
        const a = roster().find(x => x.name === name || x.codename === name);
        sid = a?.session || '';
      }
      if (!sid) return send(400, '{"ok":false,"error":"sem sessao para fechar"}', 'application/json');
      const r = await fetch(OC + '/api/session/' + encodeURIComponent(sid), {
        method: 'DELETE', headers: { Authorization: AUTH() },
        signal: AbortSignal.timeout(10000) });
      const body = await r.text();
      // remove a sessao do roster para o painel nao mostrar um agente fantasma
      // preserva TODAS as chaves do roster (version/tasks) — so troca agents
      try {
        const cur = JSON.parse(readFileSync(ROSTER, "utf8"));
        cur.agents = (cur.agents || []).map(x => x.session === sid ? { ...x, session: null } : x);
        writeFileSync(ROSTER, JSON.stringify(cur, null, 2));
      } catch {}
      return send(r.status, JSON.stringify({ ok: r.ok, status: r.status, session: sid, body: body.slice(0, 200) }), 'application/json');
    } catch (e) { return send(400, JSON.stringify({ ok: false, error: String(e) }), 'application/json'); }
  }
  send(404, '{"error":"not found"}', 'application/json');
}
const PORT = Number(process.env.PORT || 8091);
// (14/11) O padrao era '::' (TODAS as interfaces) enquanto o comentario do
// topo dizia 127.0.0.1 — e o iptables abre 8091 para a LAN inteira. O
// padrao agora e' loopback; para usar na tailnet de novo, e' preciso
// BIND=:: de proposito (e o token continua obrigatorio).
const BIND = process.env.BIND || '127.0.0.1';
createServer((req, res) => handler(req, res).catch(e => { console.error('[hub]', e); res.writeHead(500, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: String(e) })); })).listen(PORT, BIND, () => console.log('[agent-hub] listening on ' + BIND + ':' + PORT));
// (16/11) O poller de eventos roda sempre (mesmo sem nenhum cliente SSE):
// assim o primeiro a abrir o painel ja ve o historico recente e nao um
// painel vazio ate a proxima mudanca.
setTimeout(pollAll, 1500);
setInterval(pollAll, 4000);
console.log('[agent-hub] event poller on');
