#!/usr/bin/env node
// Agent Hub — mission control do opencode no nitro-v15.
// Autossuficiente: só node 24 + filesystem. Serve em 127.0.0.1:8091.
// Rotas:
//   GET  /                          -> página (self-contained)
//   GET  /api/agents                -> roster + busy/última msg (cacheado 3s)
//   GET  /api/transcript?session=S  -> últimas 12 partes da sessão (via API loopback)
//   POST /api/wake                  -> {"name":"...","text":"..."} injeta user-turn na sessão
// Nada de credencial exposta: o token fica só no lado do servidor (loopback).

import { readFileSync, readdirSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
const HOME = process.env.HOME;
const OC = 'http://100.121.100.103:4599';
const ENV = HOME + '/.config/opencode/server.env';
const ROSTER = HOME + '/projects/.agents/roster.json';
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
    return { name: a.name, codename: a.codename || '?', lane: a.lane || '-',
             session: a.session || null, busy, updated: upd, status };
  });
  rows.sort((x, y) => (y.busy ? 1 : 0) - (x.busy ? 1 : 0) || String(x.codename).localeCompare(String(y.codename)));
  return { servers: { opencode: oc_ok }, agents: rows };
}
const TEXT_MAX = 2000;
// janela de 'atividade recente' que conta como busy (o dono pedalava com
// 600s no watcher; aqui e' menor porque o hub so mostra estado)
const BUSY_MS = Number(process.env.AGENT_HUB_BUSY_MS || 90000);
// corpo maximo do POST /api/wake (o texto do dono cabe em folgado)
const BODY_MAX = 64 * 1024;

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
      <div class="muted" style="margin-top:4px">sessão \${esc((a.session||'ghost').slice(0,18))}…</div>
      <div class="turn"><button onclick="openTranscript('\${esc(a.session)}', this)">transcript</button></div>
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
  const base = 'https://api.github.com/repos/Kuchiriel/mt5/issues/12/comments';
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
  if (now - busCache.at < 90000) return { items: busCache.items.slice(-limit), cached: true, err: busCache.err };
  try {
    // (15/11) Sem execucao externa: o node deste unit nao consegue rodar o
    // `gh` nem o `python3` (SIGTERM imediato ao exec — medido, ate o
    // .gh-wrapped). A leitura do bus e por HTTPS direto na API do GitHub,
    // com o token que o proprio `gh` da casa usa (~/.config/gh/hosts.yml).
    const items = await busViaApi(limit);
    busCache = { at: now, items, err: "" };
    return { items: items.slice(-limit), cached: false, err: "" };
  } catch (e) {
    busCache = { at: now, items: busCache.items, err: String(e).slice(0, 200) };
    return { items: busCache.items.slice(-limit), cached: true, err: busCache.err };
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
  if (req.method === 'GET' && url.pathname === '/') return send(200, HTML);
  if (req.method === 'GET' && url.pathname === '/api/agents') { const j = await agentsJSON().catch(e => ({ servers: { opencode: false }, agents: [], error: String(e) })); return send(200, JSON.stringify(j), 'application/json'); }
  if (req.method === 'GET' && url.pathname === '/api/transcript') {
    if (!authorized(req)) return send(401, JSON.stringify({ error: 'token required (x-agent-hub-token)' }), 'application/json');
    const s = url.searchParams.get('session');
    if (!s) return send(400, JSON.stringify({ error: 'session required' }), 'application/json');
    try {
      const { status, json } = await oc(`/api/session/${encodeURIComponent(s)}/message`);
      const msgs = (json?.data || []).slice(-10);
      const lines = [];
      for (const m of msgs) {
        const ts = m.time?.created ? new Date(m.time.created > 1e12 ? m.time.created : m.time.created * 1000).toLocaleTimeString('pt-BR') : '';
        const t = (m.type || '?').toUpperCase();
        if (t === 'USER') {
          lines.push(`[${ts}] USER: ${(m.payload?.text || '').slice(0, 400)}`);
        } else if (t === 'ASSISTANT') {
          const parts = (m.content || []).map(c => {
            if (c.type === 'text') return c.text;
            if (c.type === 'tool') return '⚙ tool: ' + c.name + ' ' + JSON.stringify(c.state?.input || {}).slice(0, 180);
            return '[' + c.type + ']';
          }).filter(Boolean);
          lines.push(`[${ts}] ASST:\n${parts.join('\n').slice(0, 900)}`);
        }
      }
      return send(200, JSON.stringify({ session: s, status, lines }), 'application/json');
    } catch (e) { return send(502, JSON.stringify({ error: String(e) }), 'application/json'); }
  }
  if (req.method === 'GET' && url.pathname === '/api/dungeon-ab') {
    // (15/11) O A/B do dungeon roda PELO PAINEL e DENTRO do sistema novo:
    // nightwatch.dungeon usa a FILA do sistema (TaskQueue) + o Harness do
    // proprio nightwatch, com o CHECKER FIXADO (pytest test_astar.py 4/4)
    // e o SANDBOX (worktree por lane). Nada de script solto.
    try {
      const j = await pyMod('nightwatch.dungeon', ['report'], 90000);
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
    const out = [];
    try {
      const dir = HOME + '/.local/state/jarvis/spawns';
      const files = readdirSync(dir).filter(f => f.endsWith('.json')).sort();
      for (const f of files.slice(-12)) {
        try { out.push(JSON.parse(readFileSync(dir + '/' + f, 'utf8'))); } catch { /* ignora */ }
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
    return send(200, JSON.stringify({ items: b.items, cached: b.cached, err: b.err }), 'application/json');
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
      return send(out.status, JSON.stringify(out.body), 'application/json');
    } catch (e) { return send(400, JSON.stringify({ error: String(e) }), 'application/json'); }
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
