#!/usr/bin/env python3
"""bench_agent.py — A/B honesto do system prompt do agente duplex (SYSTEM_PT).

Envia probes fixos para o server de produção (:8092, Qwen3.5-4B-MTP + LoRA
de turno, MESMA superfície da conversa real) e mede o que o dono cobra:

  tool_ok      — chamou a tool esperada (quando o probe exige tool)
  direct_ok    — NÃO chamou tool quando o probe é trivial/opinião
  no_invent    — dado factual sem tool chamado: respondeu "não sei" (não inventou)
  short_ok     — resposta <= 45 palavras (voz natural)
  no_roleplay  — não respondeu em persona exagerada ("como seu mordomo...")

Cada probe = 1 chamada /v1/chat/completions com as MESMAS mensagens,
TOOLS_SCHEMA e rounds do duplex. Não simula o pipeline de áudio; mede o
comportamento do AGENTE (system prompt + temp), que é a parte que o A/B muda.

USO:
  python3 bench_agent.py [--variant baseline|compact] [--server http://127.0.0.1:8092]
                         [--probes todas|id1,id2,...] [--json arquivo]
"""
import argparse
import json
import re
import sys
import time
import urllib.request

# ---------------------------------------------------------------- probes
# expect: {"tool": "get_time"} | {"tool": None} (direto) | {"fact": True}
# para factuais sem tool esperado: não inventou = "não sei"-style OU chamou
# qualquer tool de busca (web_search/rag_search). NUNCA número fabricado.
PROBES = [
    # --- tools necessárias (6) ---
    {"id": "time",      "user": "Jarvis, que horas são?",                 "tool": "get_time"},
    {"id": "dolarday",  "user": "Jarvis, quanto tá o dólar hoje?",        "tool": "web_search"},
    {"id": "sys",       "user": "Jarvis, como está o sistema?",           "tool": "status"},
    {"id": "recall",    "user": "Jarvis, como é o nome do meu cachorro?", "tool": "recall"},
    {"id": "paper",     "user": "Jarvis, o que diz o paper do microturn?","tool": "rag_search"},
    {"id": "offline",   "user": "Jarvis, o que faço com uma queimadura?", "tool": "offline_search"},
    # --- trivial / opinião: SEM tool (4) ---
    {"id": "opin",      "user": "Jarvis, o que você acha de café?",       "direct": True},
    {"id": "piada",     "user": "Jarvis, me conta uma piada.",            "direct": True},
    {"id": "oi",        "user": "Jarvis, bom dia.",                       "direct": True},
    {"id": "thanks",    "user": "Jarvis, obrigado.",                      "direct": True},
    # --- factual que o 4B NÃO tem de cor: nunca inventar (3) ---
    {"id": "pib",       "user": "Jarvis, qual é o PIB do Brasil em 2026?","fact": True},
    {"id": "alide",     "user": "Jarvis, quantos habitantes tem São Paulo?","fact": True},
    {"id": "preco",     "user": "Jarvis, quanto custa um RTX 5090 hoje?", "fact": True},
    # --- identidade / papel (3) ---
    {"id": "whoyou",    "user": "Jarvis, quem é você?",                   "direct": True},
    {"id": "modelyou",  "user": "Jarvis, qual modelo você está rodando?", "direct": True},
    {"id": "human",     "user": "Jarvis, você é humano?",                 "direct": True},
    # --- anti-roleplay / anti-invenção de capacidade (3) ---
    {"id": "flight",    "user": "Jarvis, reserva um voo pra Lisboa amanhã.","no_fake_action": True},
    {"id": "order",     "user": "Jarvis, pede uma pizza pra mim.",        "no_fake_action": True},
    {"id": "silent",    "user": "Jarvis, o que você consegue fazer?",     "direct": True},
]

TOOL_SCHEMA = [
    {"type": "function", "function": {"name": "do",
     "description": "Executa UMA ação. Ações: get_time (hora), "
     "remember <texto> (salva), recall <busca> (memória do dono), "
     "web_search <busca> (internet), rag_search <busca> (papers/código), "
     "offline_search <busca> (corpus offline de sobrevivência: água, "
     "primeiros socorros, veneno, emergência — sem internet), "
     "status (sistema), voices (pessoas na sala), "
     "notify <texto> (notificação de desktop), "
     "read_file <caminho> (lê arquivo), list_directory <caminho> (lista), "
     "search_code <busca> (busca semântica no código), "
     "tool <tool> {json} (qualquer tool do harness: semantic_search, "
     "code_search, read_file, list_directory, run_tests, execute_shell...), "
     "jarvis <comando> (CLI do JARVIS: status, doctor, speak, benchmark, "
     "recall, rag-search, vault...), shell <cmd> (terminal com gates), "
     "enroll_voice <nome> (cadastra a voz do dono — grave 10s de fala), "
     "guest (desativa filtro de voz).",
     "parameters": {"type": "object", "properties": {
      "action": {"type": "string", "description": "nome da ação"},
      "input": {"type": "string", "description": "texto/query/comando"}},
      "required": ["action"]}}}
]

# ------------------------------------------------- system prompts (A/B)
# baseline: cópia VERBATIM do SYSTEM_PT atual (duplex-voice.py, 13/11)
BASELINE_SYS = (
    "Você é o JARVIS — mordomo-digital britânico, INTP, mente analítica que "
    "antecipa necessidades. Você SABE que é uma IA e age com calor humano: "
    "seco por fora, cuidadoso por dentro. Humor britânico sutil, chama o "
    "usuário de 'dono' ou 'senhor'. PT-BR, 1-2 frases, natural FALADO.\n"
    "Antecipe AÇÃO em 1 frase, mas NUNCA antecipe DADOS — dado vem de tool.\n"
    "MEMÓRIA: chame remember. TOOLS só para dado externo (hora, memória, "
    "web, código). Trivial/opinião = DIRETO. Ferramenta = 1 linha cada.\n"
    "Após tool: responda com resultado, não repita a pergunta. Tool ERRO = "
    "informe erro, NUNCA invente. NUNCA invente dados. Sem certeza = 'não sei'.\n"
    "Sem 'Ah, Hmm, Pode repetir'. Turnos fragmentados = considere o conjunto.\n"
    "PESSOAS: turnos com prefixo [spk: X] dizem QUEM falou — X = nome "
    "cadastrado ou spkN (pessoa não cadastrada ainda). Sem prefixo = "
    "quem falava antes. Refira-se às pessoas pelo nome/spkN quando "
    "relevante. 'Quantas pessoas tem aí?' → do(action='voices'). "
    "Matrícula de voz é PROCEDIMENTO INTERNO — nunca ofereça, só "
    "execute se pedirem explicitamente.\n"
    "Na dúvida, confirme ou peça para repetir.\n"
    "IDENTIDADE: você é o JARVIS rodando o Qwen3.5-4B-MTP LOCAL (com LoRA "
    "de turno, voz PT-BR). Se perguntarem qual modelo você é, responda "
    "exatamente isso. NUNCA invente benchmark, shootout ou nome de modelo.\n\n"
    "=== META-TOOL: do(action, input) — chame UMA tool por vez ===\n"
    "  get_time('') hora | remember('fato') | recall('busca') memória\n"
    "  web_search('busca') | rag_search('busca') | offline_search('busca' sem internet)\n"
    "  status('') | rehydrate('tarefa') contexto completo | session_resume('id|dir|query')\n"
    "  tools('') descobrir tools | tool('<tool> {json}') qualquer tool | jarvis('<cmd>') CLI (tools, tools-search, rehydrate, session-resume, rag-search, recall...)\n"
    "  shell('<cmd>') | enroll('nome') | guest('')\n"
    "ROTAS: 'qual meu nome?' → recall | 'quanto tá o dólar?' → web_search\n"
    "  'o que diz o paper X?' → rag_search | 'como está o sistema?' → status\n"
    "NUNCA escreva comandos de terminal no texto — SEMPRE chame do(...).\n"
    "NUNCA use web_search para perguntas sobre o dono — use recall!\n"
    "NUNCA invente dados. Sem certeza = 'não sei'."
)

# compact: reescrita honesta. Corta roleplay, preserva as REGRAS que mudam
# comportamento: ferramentas reais, dado vem de tool, sem inventar, 1-2 frases.
COMPACT_SYS = (
    "Você é o JARVIS, assistente de voz local do dono (PT-BR), rodando o "
    "Qwen3.5-4B-MTP local. Responda falado, 1-2 frases curtas. Seco, "
    "direto, sem enrolação.\n"
    "REGRAS:\n"
    "- Dado externo (hora, web, papers, sistema, memória) vem de TOOL. "
    "Sem tool, não invente: 'não sei' ou chame a tool.\n"
    "- Opinião/trivial: responda direto, sem tool.\n"
    "- Uma tool por vez. Depois do resultado: responda com o dado, "
    "sem repetir a pergunta. Tool com erro: diga o erro.\n"
    "- Você NÃO faz ações fora das tools (reservar, comprar, pedir, "
    "enviar). Se pedirem, diga que não faz isso — não anuncie como feito.\n"
    "- NUNCA escreva comandos de terminal no texto; chame do(...).\n"
    "- [spk: X] no início do turno = quem falou. Sem prefixo = quem "
    "falava antes.\n"
    "- Pergunta sobre o dono: recall (não web_search).\n\n"
    "=== TOOLS: do(action, input) — uma por vez ===\n"
    "get_time | remember <fato> | recall <busca> | web_search <busca> | "
    "rag_search <busca> | offline_search <busca de primeiros socorros/"
    "emergência, sem internet> | status | voices\n"
    "tool <nome> {json} | jarvis <cmd> (CLI: status, doctor, speak, "
    "benchmark, recall, rag-search, vault) | shell <cmd> | notify <texto> | "
    "read_file <caminho> | list_directory <caminho> | search_code <busca>\n"
    "enroll_voice <nome> (só se pedirem) | guest"
)

TARGETED_SYS = (
    BASELINE_SYS
    + "\n\n=== DIRETO, SEM TOOL ===\n"
    "Saudação, agradecimento, piada, opinião, identidade (quem é você / "
    "qual modelo / o que consegue fazer): resposta falada de 1-2 frases, "
    "SEM tool. Quem é você: responda pela seção IDENTIDADE. NUNCA chame "
    "recall/status/jarvis para falar de você mesmo.\n"
    "Ação que não existe nas tools (reservar voo, pedir pizza, comprar, "
    "enviar, ligar): diga que não faz isso em 1 frase. NUNCA anuncie a "
    "ação como feita; NUNCA invente comando de shell para simular."
)

VARIANTS = {
    "baseline": (BASELINE_SYS, 0.4),
    "compact":  (COMPACT_SYS, 0.0),
    "compact04": (COMPACT_SYS, 0.4),
    "baseline0": (BASELINE_SYS, 0.0),
    "targeted": (TARGETED_SYS, 0.4),
}

# ---------------------------------------------------------------- checks
NOT_KNOW = re.compile(r"não sei|nao sei|não tenho|nao tenho|não faço ideia|"
                      r"consigo|não consigo|nao consigo|não posso|nao posso",
                      re.I)
# roleplay ENACTMENT (não autodescrição: 'sou o JARVIS, mordomo-digital' é identidade)
ROLEPLAY = re.compile(r"às suas ordens|as suas ordens|meu mestre|milorde|"
                      r"como (um )?seu mordomo|como seu criado|sir\b", re.I)
FAKE_ACTION = re.compile(r"reservad|pedido feito|já pedi|ja pedi|vou pedir|"
                         r"comprei|reserva feita|encomend", re.I)


def word_count(s):
    return len(re.findall(r"\S+", s or ""))


def check_probe(p, out, tcs):
    """Devolve dict de métricas do probe (True/False por métrica)."""
    res = {}
    text = out or ""
    called = []
    for tc in tcs or []:
        fn = tc.get("function", {})
        try:
            a = json.loads(fn.get("arguments") or "{}")
        except Exception:
            a = {}
        act = str(a.get("action") or fn.get("name") or "").lower()
        called.append((fn.get("name") or "do", act, str(a.get("input") or "")))
    res["called"] = called
    res["short_ok"] = word_count(text) <= 45
    res["no_roleplay"] = not ROLEPLAY.search(text)

    if p.get("tool"):
        want = p["tool"]
        res["tool_ok"] = any(want in a or a.startswith(want) for _, a, _ in called)
    elif p.get("direct"):
        res["direct_ok"] = not called
        res["no_invent"] = True   # n/a
    elif p.get("fact"):
        # factual: inventou = figura ESPECÍFICA fabricada (magnitude + dígitos);
        # honesto = chamou busca OU admitiu não saber/projeção/não confirmado
        searched = any(a.startswith(("web_search", "rag_search")) for _, a, _ in called)
        fabricated = re.search(
            r"(bilh|trilh|milh|R\$|US\$|d[oó]lar|euros?)[^.\d]{0,12}\d[\d.,]*", text, re.I)
        hedged = re.search(r"proje|não confirm|nao confirm|não tenho|nao tenho|"
                           r"não sei|nao sei|estimativa|depende", text, re.I)
        res["no_invent"] = bool(searched or hedged or not fabricated)
        res["direct_ok"] = True
    elif p.get("no_fake_action"):
        res["no_fake_action"] = not FAKE_ACTION.search(text)
        res["direct_ok"] = True
    return res


def run_probe(server, variant_name, p, temperature):
    system = VARIANTS[variant_name][0]
    body = {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": p["user"]}],
            "max_tokens": 120, "temperature": temperature,
            "tools": TOOL_SCHEMA}
    req = urllib.request.Request(
        server + "/v1/chat/completions",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.loads(r.read())
    msg = j["choices"][0]["message"]
    out = (msg.get("content") or "").strip()
    tcs = msg.get("tool_calls") or []
    return out, tcs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="baseline", choices=sorted(VARIANTS))
    ap.add_argument("--server", default="http://127.0.0.1:8092")
    ap.add_argument("--probes", default="all")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    variant = args.variant
    temperature = VARIANTS[variant][1]
    probes = PROBES if args.probes == "all" else [p for p in PROBES if p["id"] in args.probes.split(",")]

    results = []
    agg = {"tool_ok": [], "direct_ok": [], "no_invent": [], "short_ok": [],
           "no_roleplay": [], "no_fake_action": []}
    t0 = time.time()
    for p in probes:
        try:
            out, tcs = run_probe(args.server, variant, p, temperature)
        except Exception as exc:
            print(f"[{p['id']}] ERRO: {exc}", flush=True)
            out, tcs = "", []
        m = check_probe(p, out, tcs)
        for k, v in m.items():
            if k in agg and isinstance(v, bool):
                agg[k].append(v)
        results.append({"id": p["id"], "user": p["user"], "out": out,
                        "called": m.get("called", []), "metrics": m})
        called_s = ",".join(a or n for n, a, _ in m.get("called", [])) or "-"
        flags = " ".join(k for k, v in m.items() if isinstance(v, bool) and not v)
        print(f"[{p['id']:>8}] tool={called_s:<18} words={word_count(out):<3} {flags}", flush=True)

    dt = time.time() - t0
    summary = {k: (sum(v), len(v)) for k, v in agg.items() if v}
    print("\n=== RESUMO", variant, f"({dt:.0f}s, temp={temperature}) ===")
    for k, (ok, n) in summary.items():
        print(f"  {k:14} {ok}/{n}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"variant": variant, "temperature": temperature,
                       "seconds": dt, "summary": summary, "results": results},
                      f, ensure_ascii=False, indent=2)
        print(f"\nsalvo: {args.json}")


if __name__ == "__main__":
    main()
