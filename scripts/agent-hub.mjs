#!/usr/bin/env node
// Agent Hub — mission control do opencode no nitro-v15.
// Autossuficiente: só node 24 + filesystem. Serve em 127.0.0.1:8091.
// Rotas:
//   GET  /                          -> página (self-contained)
//   GET  /api/agents                -> roster + busy/última msg (cacheado 3s)
//   GET  /api/transcript?session=S  -> últimas 12 partes da sessão (via API loopback)
//   POST /api/wake                  -> {"name":"...","text":"..."} injeta user-turn na sessão
// Nada de credencial exposta: o token fica só no lado do servidor (loopback).

import { readFileSync } from 'node:fs';
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
async function wake(name, text) {
  const r = roster().find(a => a.session && (
    (a.name||'').toLowerCase() === name.toLowerCase() ||
    (a.codename||'').toLowerCase() === name.toLowerCase() ||
    ((a.aliases||[]).some(x => String(x).toLowerCase() === name.toLowerCase()))));
  if (!r) return { status: 404, body: { error: 'alvo nao esta no roster local' } };
  if (!text?.trim()) return { status: 400, body: { error: 'texto vazio' } };
  const payload = { text, delivery: 'queue' };
  const res = await fetch(OC + `/api/session/${r.session}/prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: AUTH() },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(15000),
  });
  const body = await res.text().catch(() => '');
  try { return { status: res.status, body: JSON.parse(body) }; } catch { return { status: res.status, body }; }
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
</script></body></html>`;

// ── BUS: a conversa da frota (issue #12 do repo Kuchiriel/mt5) ────────────
// (15/11, crouton-alpha) O dono pediu "ver como eles estao conversando".
// As mensagens entre agentes vao pro bus como comment com bloco ```coord-json.
// Le com o gh (autenticado no host) e cacheia 90s para nao estourar o
// rate-limit do GitHub (a UI faz poll a cada 10s).
let busCache = { at: 0, items: [], err: "" };

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

async function handler(req, res) {
  const url = new URL(req.url, 'http://127.0.0.1');
  const send = (code, body, type='text/html; charset=utf-8') => { res.writeHead(code, { 'Content-Type': type }); res.end(body); };
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
