#!/usr/bin/env python3
"""F30: dashboard estatico auto-contido da evolucao do LLM do zero.

Le todos os JSONs de ~/work/hybrid relevantes e gera um unico HTML com
Plotly (CDN). Nao depende de servidor Python: basta servir o diretorio.
"""
from __future__ import annotations
import json, re
from pathlib import Path

W = Path("/home/nixos/work/hybrid")
OUT = Path("/home/nixos/projects/nixos-ai/tools/lab-timeline")
OUT.mkdir(parents=True, exist_ok=True)

# padroes de frente -> metricas conhecidas
PATTERNS = {
    "f3-rerun": "F3 300M", "f7-150m": "F7 150M", "f9-": "F9 seeds",
    "f12-": "F12 protocolo", "f13-": "F13 specialization", "f14-": "F14 KV",
    "f16-": "F16 KV 150M", "f17": "F17 IC95", "f18-": "F18 escala 50M",
    "f19-": "F19 undertraining", "f20-": "F20 curva estrita", "f21": "F21 gate causal",
    "f22-50m": "F22 50M causal", "f23b-": "F23b calibracao", "f24-": "F24 geracao 256",
    "f25-": "F25 geracao 300M", "f26-": "F26 4800 passos", "f27-": "F27 BitNet",
    "f29-": "F29 FLT x nGPT",
}
def label(name: str) -> str:
    for k, v in PATTERNS.items():
        if name.startswith(k): return v
    return "outras"

points = []
for p in sorted(W.glob("*.json")):
    try: d = json.loads(p.read_text())
    except Exception: continue
    if not isinstance(d, dict): continue
    rng = d.get("rows")
    if not isinstance(rng, list): continue
    for r in rng:
        if not isinstance(r, dict): continue
        rec = {
            "file": p.name, "front": label(p.name),
            "scale": r.get("scale_m") or d.get("depth") or d.get("seed") or 0,
            "variant": r.get("variant", ""), "mode": r.get("mode", "full"),
            "val": r.get("val_loss"), "acc": r.get("acc_all", r.get("acc")),
            "ece": r.get("ece_all", r.get("ece")),
            "tok_s": r.get("train_tok_s", r.get("tok_per_s", r.get("prompts_per_s"))),
            "vram": r.get("peak_vram_bytes"), "tokens": r.get("tokens_until_answer"),
        }
        if rec["val"] is None and rec["acc"] is None: continue
        points.append(rec)

html = """<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<title>Lab Timeline — LLM do zero</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{font-family:system-ui;background:#0d1117;color:#e6edf3;margin:0;padding:20px}
h1{margin:0 0 6px} .sub{color:#8b949e;margin-bottom:20px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:18px}
table{border-collapse:collapse;width:100%;font-size:13px} td,th{border-bottom:1px solid #30363d;padding:5px;text-align:left}
button{cursor:pointer;background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:5px;padding:6px 10px}
input{background:#0d1117;color:#e6edf3;border:1px solid #30363d;padding:7px;border-radius:5px;width:60%}
</style></head><body>
<h1>Laboratório do LLM do zero — linha do tempo</h1>
<div class="sub">Dados: """ + str(len(points)) + """ medições de """ + str(len(set(p['front'] for p in points))) + """ frentes · host local · hardware modesto</div>
<div class="card"><b>Escolha o eixo:</b>
 <button onclick="plot('val')">val loss</button>
 <button onclick="plot('acc')">acurácia</button>
 <button onclick="plot('ece')">ECE</button>
 <button onclick="plot('tok_s')">tokens/s</button>
 <button onclick="plot('vram')">VRAM</button>
 <div id="chart" style="height:420px"></div></div>
<div class="card"><b>Playground (demo local, sem teacher forcing):</b><br>
<input id="prompt" value="Once upon a time" placeholder="digite um prompt">
<button onclick="gen()">gerar</button>
<pre id="out">(o modelo real ainda é mini; esta área mostra o estado honesto da geração)</pre></div>
<div class="card"><b>Últimas medições</b><div id="table"></div></div>
<script>
const D = """ + json.dumps(points) + """;
function plot(k){
  const traces = {};
  D.forEach(p=>{ const v=p[k]; if(v==null||isNaN(v))return;
    const key=p.variant||p.mode||'todos';
    (traces[key]=traces[key]||[]).push([p.front+' / '+p.scale, v, p.file]);
  });
  const data=Object.keys(traces).map(k=>({type:'bar',name:k,
    x:traces[k].map(t=>t[0]),y:traces[k].map(t=>t[1]),
    customdata:traces[k].map(t=>t[2]),hovertemplate:'%{x}<br>'+k+': %{y}<br>%{customdata}<extra></extra>'}));
  Plotly.react('chart',data,{barmode:'group',paper_bgcolor:'#161b22',plot_bgcolor:'#161b22',
    font:{color:'#e6edf3'},margin:{b:160},xaxis:{tickangle:-40},yaxis:{title:k}});
}
function gen(){ document.getElementById('out').textContent =
 'Demo interativa sera ligada ao checkpoint quando o corpus word-level (F31) estiver pronto.\\n'+
 'Ate la: o laboratorio mede mecanismos — veja os graficos acima.'; }
function table(){
  const rows=D.slice(-30).reverse();
  document.getElementById('table').innerHTML='<table><tr><th>frente</th><th>escala</th><th>variante</th><th>val</th><th>acc</th><th>ECE</th></tr>'+
   rows.map(r=>'<tr><td>'+r.front+'</td><td>'+r.scale+'</td><td>'+(r.variant||r.mode)+'</td><td>'+(r.val??'-')+'</td><td>'+(r.acc??'-')+'</td><td>'+(r.ece??'-')+'</td></tr>').join('')+'</table>';
}
plot('val'); table();
</script></body></html>"""
(OUT / "index.html").write_text(html)
(OUT / "data.json").write_text(json.dumps(points, indent=2))
print("dashboard_ok", len(points), len(html))
