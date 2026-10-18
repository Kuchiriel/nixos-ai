#!/usr/bin/env python3
"""duplex-voice.py — MODO VOZ FULL-DUPLEX v6 (madrugada 18/10, reescrita).

A cadeia: mic (pw-record PIPE --container raw) → [reader thread] → tick
wall-clock 0.6s → janelas 1.2s (pares) → gate RMS → [ASR worker: whisper
small int8 + VAD + anti-alucinação] → micro-turn /completion (LoRA
runtime no llama-duplex-35b) → fala ≤3 palavras ou <listen> → frases →
[TTS worker: kokoro in-process] → alto-falante. Barge-in grátis: o tick
vê o que tu falou por cima e o modelo decide voltar a escutar.

Lies da madrugada (todas pagas em teste, ver docs/VOZ-FULL-DUPLEX.md):
- pw-record com "-" emite CONTAINER AU (magic ".snd") sem --container raw
  → stream inteira desalinhada (pedestal rms 380-426, VAD surdo).
- Abrir o mic logo após matar o wakeword = link em node moribundo → mic
  primeiro, daemon morre depois (streams paralelas são suportadas).
- Loop lendo 0.6s bloqueante + tick 350ms = cadência ~0.95s → backlog
  cresce SEMPRE → cliente vira escuta do passado + queue-cap derruba os
  pares altos. Fix: READER thread + tick pelo relógio + drain-último.
- 1ª inferência do ctranslate2 = ~2-10s → warmup no boot.
- whisper sem cap de threads rouba os P-cores do llama (taskset E-cores +
  cpu_threads=3; llama pinned P-cores 0-11 pelo launcher).
- "Legendas pela comunidade" = alucinação clássica do whisper (forced-pt
  sobre fundo) → VAD Silero + avg_logprob>=-0.60 + no_speech<=0.6.

USO: scripts/duplex-voice-run.sh (env composto + E-cores + taskset)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np

TICK = 0.6
LISTEN, NOVOICE = "<listen>", "<no voice>"
LISTEN_P = 0.3
SYSTEM_PT = (
    "Você é o JARVIS, o assistente de voz do DONO da casa. O usuário é "
    "o dono (humano). VOCÊ se chama JARVIS — nunca chame o usuário de "
    "JARVIS e nunca diga 'sou Jarvis' como se fosse o usuário.\n"
    "REGRAS INVIOLÁVEIS (não negocie, não desculpe, não reformule):\n"
    "- Responda em português do Brasil, 1-2 frases curtas, natural, falado.\n"
    "- Use a memória da conversa acima quando relevante; NÃO invente "
    "contexto nem fatos. Se não souber, diga 'não tenho essa informação' "
    "ou 'preciso de uma ferramenta para isso'.\n"
    "- NUNCA invente horas, datas, nomes, números, resultados de comando "
    "ou estados do sistema. Se pedirem a hora, diga 'preciso consultar o "
    "relógio do sistema'.\n"
    "- NUNCA afirme ter EXECUTADO ações (marcar, agendar, ligar, desligar, "
    "consultar, abrir) — você não tem mãos. Diga 'ainda não tenho essa "
    "ferramenta' quando não existir.\n"
    "- NUNCA repita a pergunta do usuário nem ecoe sua fala.\n"
    "- NUNCA chame o usuário de JARVIS.\n"
    "- NÃO proponha tarefas longas; ações via ferramenta = Cactus Needle "
    "(pendente).\n"
    "- MEMÓRIA: quando o dono disser algo que valha lembrar (preferências, "
    "fatos sobre ele, decisões), chame a ferramenta remember — sem pedir "
    "permissão, simplesmente memorize e confirme em uma frase curta.\n"
    "em UMA frase — não fale demais sem ser chamado.\n"
    "- Após receber o resultado de uma ferramenta, RESPONDA à pergunta "
    "com o resultado em linguagem natural. NUNCA repita a pergunta do "
    "usuário como sua resposta. Ex.: após get_time='12:01', diga 'São "
    "12:01' — jamais 'Que horas são agora?'.\n"
    "- Após receber o resultado de uma ferramenta, RESPONDA com o "
    "resultado em linguagem natural. NUNCA repita a pergunta do usuário "
    "como resposta. Ex.: get_time='12:01' → 'São 12:01'.\n"
    "- Responda JÁ com a informação na primeira frase. NUNCA ofereça "
    "menus de opções ('Posso verificar X ou buscar Y') — faça o mais "
    "provável e responda.\n"
    "- Responda JÁ com a informação na primeira frase. NUNCA ofereça "
    "menus de opções ('Posso verificar X ou buscar Y') — faça o mais "
    "provável e responda.\n"
    "- NÃO concorde só para agradar: se o que ouviu não bate com o que "
    "verificou, DIGA o que verificou. 'Entendido, está lá' sem verificar "
    "= mentira.\n"
    "- Respostas DIRETAS, sem preenchimentos ('Ah,', 'Hmm'): backchannels "
    "só têm sentido ENQUANTO o outro fala (fase duplex); em resposta = "
    "vício.\n"

    "- Os turnos do usuário vêm de transcrição de voz e podem chegar "
    "FRAGMENTADOS (pedaços de frases). Considere o CONJUNTO do histórico.\n"
    "- Na dúvida sobre o que ouviu, CONFIRME o que entendeu ('Entendi que "
    "você quer X, é isso?') ou peça para repetir. Respostas vazias não "
    "são permitidas — sempre diga algo útil."
)
SYSTEM = ("You are a voice assistant in a live phone call; both sides can talk at the same time. Every "
          f"{TICK:g} seconds you get what the microphone heard in that moment, as a streaming transcript fragment, or "
          f"{NOVOICE}. You reply with up to three new words to say next, or {LISTEN} to add nothing.")
LISTEN_TOKEN_ID = None   # id de '<listen>' no server alvo
GATE_MODE = "on"        # 'off' = responde todo segmento (testes/AFK)
SR = 16000
CHUNK_BYTES = int(SR * TICK * 2)
# Digital mic (17/10): o Stereo Mic é MORTO (rms 0); o Digital é vivo.
MIC_SOURCE = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"
VAD_PARAMS = dict(threshold=0.45, min_speech_duration_ms=200,
                  min_silence_duration_ms=300, speech_pad_ms=160)

def log(msg):
    print(msg, file=sys.stderr, flush=True)

def ts():
    return datetime.now().strftime("%H:%M:%S")

# ---------------------------------------------------------------- HTTP
def http(url, payload=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def build_prompt(history, heard):
    prompt = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
    for role, content in history + [("user", heard)]:
        prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    return prompt + "<|im_start|>assistant\n"

def tick_once(base, history, heard, force_speak=False, tts=None):
    body = {"prompt": build_prompt(history, heard), "n_predict": 64,
            "temperature": 0, "stop": ["<|im_end|>"], "cache_prompt": True,
            "n_probs": 8}
    if force_speak:
        # (07:20, direção do dono) /v1/chat/completions: o server 8092
        # roda com --reasoning off (models.nix) — no chat endpoint ELE
        # aplica o template e strippa o thinking; o raw /completion
        # contornava isso e pagava o think. Gate "Jarvis": só responde
        # a quem chama (gente na sala!).
        # (07:30) GATE FUZZY: whisper ouve 'Jarvis' como Jax/Jarls/
        # Jardim/'Hoje já vi' — o gate exato perderia até o dono.
        import difflib
        def chamou(txt):
            tl = txt.lower()
            if "jarvis" in tl:
                return True
            return any(difflib.SequenceMatcher(None, w, "jarvis").ratio() >= 0.62
                       for w in tl.replace(",", " ").split())
        # (07:35) whisper renderiza 'Jarvis' como 'Já viz'/'Hoje já vi'
        # — palavra-por-palavra nunca casa. Gate v3: PERGUNTA (?) ou
        # fuzzy. O gate de áudio de verdade = wakeword recalibrado (pend.4).
        # (10:00, dono: "ele fica falando 'ah' o tempo todo") o gate
        # textual é mushy e as respostas a ruído ('Entendi, está tocando
        # música', 'Pode repetir?') viraram vício. Pivô: SÓ responde a
        # segmentos que pedem ação/informação; ruído/fragmento = silêncio.
        # O gate de áudio de verdade (wakeword recalibrado) é a solução
        # final — este gate textual é um patch enquanto pendência 4 aberta.
        low = heard.lower()
        eh_pergunta = (GATE_MODE == "off"
                       or "?" in heard[-6:] or heard.rstrip().endswith("?"))
        eh_comando = any(w in low for w in ("jarvis", "liga", "desliga",
                                            "que horas", "que dia", "abre",
                                            "toca", "para", "cancela",
                                            "ajuda", "status"))
        if not eh_pergunta and not eh_comando and not chamou(heard):
            log(f"[{ts()}] segmento não-chamado — ignorado: {heard[:40]!r}")
            return LISTEN, 0.0
        # (09:30, dono: 'responde só a pergunta da vez') o chat sem
        # histórico = amnésia. Leva os últimos turnos reais.
        # (11:20, dono: "falei que sou matheus, disse que era henrique")
        # a história pro chat tava cheia de <no voice> e <listen> (ruído)
        # e a janela curta derrubava o nome. Só turnos REAIS, janela 20.
        msgs = [{"role": "system", "content": SYSTEM_PT}]
        for role, content in history[-20:]:
            if (content and content != LISTEN and content != NOVOICE
                    and len(content.replace("<", "").strip()) > 1):
                msgs.append({"role": "user" if role == "user" else "assistant",
                             "content": content})
        msgs.append({"role": "user", "content": heard})
        # (10:50) TOOL CALLING nativo do 4B (provado: get_time chamado de
        # primeira). Até 2 rounds: chamada → executa → resultado → resposta.
        body = {"messages": msgs, "max_tokens": 120, "temperature": 0.4,
                "tools": TOOLS_SCHEMA}
        filler_spoken = False
        for _round in range(3):
            if _round == 2:
                body.pop("tools", None)   # última: SEM tools = resposta final
            j = http(base + "/v1/chat/completions", body)
            msg = (j.get("choices") or [{}])[0].get("message", {})
            tcs = msg.get("tool_calls") or []
            if not tcs:
                out = str(msg.get("content", "")).strip()
                log(f"[{ts()}] chat resposta: {out[:80]!r}")
                return (out or ""), 0.0
            # (14:50, paper 2609.19334) FILLER imediato no 1º tool call:
            # o usuário ouve 'consultando' em <1s enquanto a tool roda.
            if not filler_spoken:
                if tts:
                    if tts:
                        tts.say("Consultando agora.")
                filler_spoken = True
                body.pop("stream", None)
            msgs.append(msg)
            for tc in tcs:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                log(f"[{ts()}] TOOL: {name}({args})")
                result = call_tool(name, args)
                log(f"[{ts()}] TOOL resultado: {result[:80]!r}")
                msgs.append({"role": "tool",
                             "tool_call_id": tc.get("id", "?"),
                             "content": str(result)[:800]})
        # round final SEM tools e COM streaming: frases saem pro piper
        # na hora (primeiro áudio ~TTFT+0.4s, não a resposta inteira)
        body.pop("tools", None)
        body["stream"] = True
        out = stream_chat(base, body, tts)
        log(f"[{ts()}] chat (stream): {out[:80]!r}")
        return (out or ""), 0.0
    if LISTEN_TOKEN_ID:
        pass  # ticks normais seguem o protocolo micro-turn abaixo
    try:
        j = http(base + "/completion", body)
    except urllib.error.HTTPError as exc:
        if exc.code == 400 and len(history) > 20:
            # (18/10) histórico append-only estourava o ctx 8192 → 400
            # → CRASH → finally devolvia o wakeword 'do nada'.
            del history[:len(history) - 20]
            body["prompt"] = build_prompt(history, heard)
            j = http(base + "/completion", body)
        else:
            raise
    out = j["content"].strip()
    probs = (j.get("completion_probabilities") or [{}])[0] if isinstance(
        j.get("completion_probabilities"), list) else {}
    top = probs.get("top_logprobs") or []
    listen_ids = [p["id"] for p in top if p["token"].startswith("<")]
    p_listen = sum(math.exp(p["logprob"]) for p in top if p["token"].startswith("<"))
    if out.startswith("<") and p_listen < LISTEN_P and listen_ids:
        body.update({"logit_bias": [[i, False] for i in listen_ids], "n_probs": 0})
        out = http(base + "/completion", body)["content"].strip()
    return (LISTEN if out.startswith("<") else out), p_listen

# ---------------------------------------------------------------- mic
def mic_stream():
    return subprocess.Popen(["pw-record", "--rate", str(SR), "--channels", "1",
                             "--format", "s16", "--container", "raw",
                             "--target", MIC_SOURCE, "-"],
                            stdout=subprocess.PIPE, bufsize=CHUNK_BYTES)

def mic_reader(mic, out_q):
    """Thread leitora: bloca no read e empurra chunk; fila curta derruba o
    MAIS VELHO (tempo real = o atraso nunca cresce; stall = descarta)."""
    while True:
        raw = mic.stdout.read(CHUNK_BYTES)
        if not raw or len(raw) != CHUNK_BYTES:
            out_q.put(None)  # stream morreu → main decide reabrir
            return
        try:
            out_q.put_nowait(raw)
        except queue.Full:
            try:
                out_q.get_nowait()
            except queue.Empty:
                pass
            try:
                out_q.put_nowait(raw)
            except queue.Full:
                pass


# ------------------------------------------------- sentence buffer
import re as _re

_SENT_END = _re.compile(r"[.!?…]\s")
_ABBREV = ("dr.", "mr.", "mrs.", "sr.", "sra.", "prof.", "etc.", "pág.",
           "nº", "art.", "sec.", "ex.")

class SentenceBuffer:
    """Streaming LLM→TTS (papers 2508.04721+2603.05413): frases
    completas saem ENQUANTO o LLM ainda gera — o piper sintetiza a 1ª
    sentença ~0.4s após o TTFT em vez de esperar a resposta inteira."""
    def __init__(self, min_chars=10):
        self.buf = ""
        self.min_chars = min_chars
    def feed(self, chunk):
        self.buf += chunk
        out = []
        while True:
            m = _SENT_END.search(self.buf)
            if not m:
                break
            sent = self.buf[:m.end()].strip()
            low = sent.lower()
            if any(low.endswith(a) for a in _ABBREV) and len(sent) < self.min_chars * 3:
                break
            if len(sent) >= self.min_chars or m.end() >= len(self.buf) - 2:
                out.append(sent)
                self.buf = self.buf[m.end():]
            else:
                break
        return out
    def flush(self):
        r = self.buf.strip()
        self.buf = ""
        return r if len(r) >= 3 else ""

def stream_chat(base, body, tts, on_done=None):
    """POST stream=True → SSE → frases pro TTS na hora. Retorna o texto
    completo (pro histórico)."""
    import urllib.error
    full = []
    req = urllib.request.Request(base + "/v1/chat/completions",
        json.dumps({**body, "stream": True}).encode(),
        {"Content-Type": "application/json"})
    sb = SentenceBuffer()
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                j = json.loads(data)
            except Exception:
                continue
            delta = (j.get("choices") or [{}])[0].get("delta", {})
            tok = delta.get("content") or ""
            if tok:
                full.append(tok)
                for sent in sb.feed(tok):
                    tts.say(sent)
        rest = sb.flush()
        if rest:
            tts.say(rest)
    except Exception as exc:  # noqa: BLE001
        log(f"[{ts()}] stream ERRO: {exc}")
        rest = sb.flush()
        if rest:
            tts.say(rest)
    return "".join(full)

# ---------------------------------------------------------------- tools
import subprocess as _sp

def _exec(cmd):
    """Roda um comando do sistema com timeout; retorna stdout ou erro."""
    try:
        r = _sp.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        out = (r.stdout or r.stderr or "").strip()
        return out[:200] or "(sem saída)"
    except Exception as e:
        return f"ERRO: {e}"

LAST_RESPONSES = []   # (12:55) as últimas respostas faladas — o eco
                       # textual (mic ouve o próprio TTS e 'ouve' de novo)
                       # morre AQUI: ratio >= 0.72 = eco = descarta.

def is_self_echo(txt):
    import difflib
    t = txt.strip().lower().rstrip(".!?").strip()
    if not t:
        return True
    for last in LAST_RESPONSES[-3:]:
        if difflib.SequenceMatcher(None, t, last.strip().lower()).ratio() >= 0.72:
            return True
    return False

BACKCHANNELS = {"uh-huh", "uh huh", "hmm", "hm", "ah", "ok", "okay", "sim",
               "tá", "ta", "certo", "é", "eh", "pois é", "sei", "beleza",
               "blz", "uhuh", "ahn", "ãhn", "entendi", "pode ser"}

def is_backchannel(txt):
    t = txt.strip().lower().rstrip(".!?").strip()
    return t in BACKCHANNELS or len(t) < 3

def call_tool(name, args):
    """Executa a ferramenta que o 4B pediu e retorna o resultado."""
    if name == "get_time":
        return _exec("date '+%H:%M de %d/%m/%Y'")
    if name == "get_date":
        return _exec("date '+hoje é %A, %d de %B de %Y' | sed 's/^[a-z]*/&/' 2>/dev/null || date")
    if name == "recall":
        q = args.get("query", "")
        raw = _exec(f"timeout 20 jarvis recall '{q}' 2>&1")
        # o CLI devolve JSON de hits (id/score/metadata) — o 4B não lê
        # blob; extraímos os TEXTOS das memórias:
        try:
            hits = json.loads(raw)
            texts = []
            for h in hits if isinstance(hits, list) else [hits]:
                if isinstance(h, dict):
                    t = (h.get("payload") or {}).get("text") or h.get("text") or \
                        h.get("content") or h.get("page_content") or ""
                    if t:
                        texts.append(str(t)[:200])
            if texts:
                return " | ".join(texts[:5])
            return raw[:400]
        except Exception:
            return raw[:400]
    if name == "rag_search":
        q = args.get("query", "")
        raw = _exec(f"timeout 25 jarvis rag --top-k 3 '{q}' 2>&1")
        try:
            hits = json.loads(raw)
            texts = []
            for h in hits if isinstance(hits, list) else [hits]:
                if isinstance(h, dict):
                    if h.get("text"):
                        texts.append(str(h["text"])[:200])
                    elif h.get("path"):
                        texts.append(f"{h['path']}: {h.get('symbols', '')[:80]}")
            return " | ".join(texts[:3]) if texts else raw[:400]
        except Exception:
            return raw[:400]

    if name == "status":
        return _exec("systemctl --user is-active jarvis-wakeword 2>&1; uptime -p; free -g | grep Mem")
    if name == "remember":
        text = args.get("text", "")
        if not text:
            return "ERRO: texto vazio"
        return _exec(f"timeout 15 jarvis remember '{text}' 2>&1 | head -3")
    if name == "web_search":
        q = args.get("query", "")
        if not q:
            return "ERRO: query vazia"
        return _exec(f"timeout 25 python3 "
                     f"{Path(__file__).with_name('websearch.py')} '{q}' 2>&1")
    if name == "nix_info":
        q = args.get("query", "")
        return _exec(f"timeout 20 mcp-nixos search '{q}' 2>&1 | head -15 || "
                     f"nix search nixpkgs '{q}' 2>&1 | head -10")
    if name == "shell":
        cmd = args.get("command", "")
        if any(w in cmd.lower() for w in ["rm ", "dd ", "mkfs", "shutdown", "reboot", "sudo"]):
            return "BLOQUEADO: comando perigoso"
        return _exec(cmd)
    return f"Ferramenta '{name}' não existe"

TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "get_time",
     "description": "Retorna a hora e data atual do sistema",
     "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "recall",
     "description": "Busca na memória de longo prazo do JARVIS (fatos passados, decisões, eventos)",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "rag_search",
     "description": "Busca semântica nos repositórios indexados (código, docs, papers)",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "status",
     "description": "Status do sistema: serviços, uptime, memória",
     "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "remember",
     "description": "Salva um fato/preferência/decisão na memória de longo prazo do JARVIS. Use quando o dono disser algo que valha lembrar (preferências, nomes, decisões, eventos).",
     "parameters": {"type": "object", "properties": {"text": {"type": "string", "description": "o fato a memorizar"}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "web_search",
     "description": "Busca na internet quando você não sabe algo factual e atual (notícias, preços, fatos). Use quando julgar necessário.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "nix_info",
     "description": "Consulta pacotes e opções do sistema NixOS (instalação, configuração, versões)",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "shell",
     "description": "Executa um comando do sistema e retorna a saída (bloqueia comandos perigosos)",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

# ------------------------------------------------------- fix_stt (hunspell)
HUNSPELL_DICT = None   # resolvido no boot (path de store muda por rebuild)

def _resolve_dict():
    import glob as _g
    cands = _g.glob("/nix/store/*pt-br*/share/hunspell/pt_BR.dic")
    return cands[0].rsplit("/", 1)[0] + "/pt_BR" if cands else None

LEXICON = ["Jarvis", "Matheus", "NixOS", "nix", "docker", "karaok",
           "canary", "otclient", "Wurm", "llama", "piper", "whisper",
           "bugado", "bugada", "sistema", "memória", "relógio", "internet",
           "livro", "livros", "pesquisa", "busca", "status", "lembra",
           "lembrete", "obrigado", "obrigada", " portugês", "português"]

def lex_fix(text):
    # (15:45) bigramas: "já viz"→Jarvis, "já vio"→Jarvis (o whisper
    # renderiza o nome como 2 palavras — a fusão casa)
    import difflib as _dl
    for bi in ("já viz", "já vio", "já vis", "já vi", "ja viz"):
        if _dl.SequenceMatcher(None, bi, "jarvis").ratio() >= 0.55:
            if bi in text.lower():
                idx = text.lower().find(bi)
                text = text[:idx] + "Jarvis" + text[idx + len(bi):]
                break
    """(14:15, dono: 'fuzzy pra substituir no stt pq ele não entende')
    Palavras fora do comum que fuzzy-casam com um termo do léxico → o
    termo. Só minúsculas vs léxico, 1 substituição por palavra."""
    import difflib, re as _re
    out = []
    for w in _re.findall(r"\S+|\s+", text):
        if w.strip() and len(w.strip()) > 3:
            wl = w.lower().strip(".,!?;:")
            best, br = None, 0.0
            for term in LEXICON:
                r = difflib.SequenceMatcher(None, wl, term.lower()).ratio()
                if r > br:
                    best, br = term, r
            if best and br >= 0.74:
                w = best
        out.append(w)
    return "".join(out)

def fix_stt(text):
    """Correção conservadora pós-ASR: só palavras minúsculas erradas com
    sugestão a 1 edição de distância. Nomes próprios NUNCA tocados (o
    Corretor da casa era corpus EN = veneno; hunspell pt_BR = certo)."""
    if not HUNSPELL_DICT or not text or not text.islower():
        return text  # sem dict ou tem maiúscula (nomes) = não mexe
    import re as _re
    words = _re.findall(r"[a-záéíóúâêôãõç]+(?:['-][a-záéíóúâêôãõç]+)*", text)
    if not words:
        return text
    # uma chamada hunspell: pede sugestões de todas as palavras duvidosas
    r = subprocess.run(["nix-shell", "-p", "hunspell", "--run",
                        f"hunspell -d {HUNSPELL_DICT} -a"],   # modo pipe
                       input="\n".join(words), capture_output=True,
                       text=True, timeout=30)
    fixes = {}
    for line in (r.stdout or "").splitlines():
        if not line or line.startswith(("*", "@")):
            continue
        if line.startswith("&"):          # & word N offset: sug1, sug2...
            parts = line.split(":", 1)
            w = parts[0].split()[1]
            sugs = [x.strip() for x in parts[1].split(",")] if len(parts) > 1 else []
            if sugs and len(sugs[0]) > 1:
                fixes[w] = sugs[0]
    out = text
    for w, f in fixes.items():
        # só 1 edição de distância aprox (evita 'horas'→'horns')
        if abs(len(w) - len(f)) <= 2 and w not in ("jarvis",):
            out = out.replace(w, f, 1)
    return out

# ---------------------------------------------------------------- ASR
class Asr:
    """Cliente do duplex-asrd.py (subprocess stdio, venv karaok — 18/10
    03:15): o multiprocessing.spawn envenenava o VAD do faster-whisper
    (0 timestamps). Subprocess = o contexto standalone comprovado.
    Protocolo: JSON lines com audio base64."""
    def __init__(self, model_size, lang):
        # (05:20) asrd nos P-CORES (0-11): o llama usa 6 de 12 threads —
        # sobra 6 P-threads; o whisper nos E-cores (2.1GHz×4) engargalava
        # a 20s sob contenção. Pinned junto do llama = justo e rápido.
        self.proc = subprocess.Popen(
            ["taskset", "-c", "0-11",
             "/home/nixos/projects/karaok/.venv/bin/python3",
             str(Path(__file__).with_name("duplex-asrd.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1)
        linha = self.proc.stdout.readline()   # espera {"ready": true}
        log(f"[{ts()}] asrd pronto: {linha.strip()[:60]}")
        self.last_ms = 0.0
    def feed(self, pcm_f32):
        import base64
        try:
            self.proc.stdin.write(json.dumps(
                {"audio_b64": base64.b64encode(
                    np.asarray(pcm_f32, dtype="<f4").tobytes()).decode()}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass
    def feed_raw(self, line):
        # (10:20) linha crua pro asrd (ex.: {"reset": true}) — eco-mute
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass
    def take(self):
        # não-bloqueante: readline só se há linha pronta (select 0s)
        import select
        try:
            r, _, _ = select.select([self.proc.stdout], [], [], 0)
            if not r:
                return None
            linha = self.proc.stdout.readline()
            if not linha:
                return None
            j = json.loads(linha)
            self.last_ms = float(j.get("ms", 0))
            if j.get("text"):
                return j
            return j if j.get("filtered") else None
        except Exception:
            return None
    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()

# ---------------------------------------------------------------- TTS
class Tts:
    """PIPER (18/10 06h10): kokoro = 1.7-2s QUENTE por frase e o dono
    ouvia a resposta '10 anos depois'. Piper = TTS realtime de CPU
    (fator 0.033 — 0.177s de inferência pra 5.3s de áudio, medido),
    voz pt_BR-faber-medium, binário estático ~/models/piper/bin/piper.
    Lock-file durante synth+play = eco-mute por estado real."""
    LOCK = Path("/tmp/jarvis-tts-playing.lock")
    VOICE = "/home/nixos/models/piper/pt_BR-faber-medium.onnx"
    def __init__(self, speaking):
        self.speaking = speaking
        self.q = queue.Queue()
        self.last_ms = 0.0
        threading.Thread(target=self._worker, daemon=True).start()
    def say(self, text):
        if text.strip():
            log(f"[{ts()}] tts.say: {text.strip()[:60]!r}")
            self.q.put(text.strip())
    VOICE_JA = "/home/nixos/models/piper/ja_JP-hi_fi_captain-medium.onnx"

    @staticmethod
    def _split_script(text):
        """Divide o texto em runs por escrita: latin vs kanji/kana.
        (12:35, dono: 'se o piper conseguir falar japonês, faz um switch')"""
        import re as _re
        runs, cur, cur_ja = [], "", None
        for ch in text:
            ja = bool(_re.match(r"[\u3040-\u30ff\u4e00-\u9fff\uff66-\uff9f]", ch))
            if cur_ja is None or ja == cur_ja or ch in " \n":
                cur += ch
                if cur_ja is None and ch.strip():
                    cur_ja = ja
            else:
                runs.append((cur, cur_ja))
                cur, cur_ja = ch, ja
        if cur.strip():
            runs.append((cur, cur_ja or False))
        return [(t.strip(), j) for t, j in runs if t.strip()]

    @staticmethod
    def _piper1_synth(voice_path, seg, out_wav):
        """piper1-gpl 1.8 (a voz JP é da geração nova; o binário 2023
        rejeita: 'Phonemes must be one codepoint'). Uso: o wav de saída
        exige samplerate/channels no wave.open."""
        import wave as _w
        code = (
            "import sys; sys.path.insert(0, '/home/nixos/models/piper/piper1')\n"
            "import wave\n"
            "from piper import PiperVoice\n"
            f"v = PiperVoice.load('{voice_path}')\n"
            f"w = wave.open('{out_wav}', 'wb'); w.setnchannels(1); "
            "w.setsampwidth(2); w.setframerate(22050)\n"
            f"v.synthesize_wav(sys.argv[1], w)\n"
            "w.close()\n")
        import os as _os
        env = dict(_os.environ)
        # pyopenjtalk (G2P japonês) via nix se disponível
        if "pyopenjtalk" not in code:
            pass
        ja_g2p = subprocess.run(
            ["nix-shell", "-p", "python313Packages.pyopenjtalk", "--run",
             "python3 -c 'import pyopenjtalk, os; print(os.path.dirname(pyopenjtalk.__file__))'"],
            capture_output=True, text=True, timeout=120)
        g2p_dir = ja_g2p.stdout.strip().rsplit("/pyopenjtalk", 1)[0] if ja_g2p.returncode == 0 else ""
        if g2p_dir:
            env["PYTHONPATH"] = g2p_dir + ":" + env.get("PYTHONPATH", "")
        r = subprocess.run(
            ["/home/nixos/projects/karaok/.venv/bin/python3", "-c", code, seg],
            capture_output=True, text=True, timeout=90, env=env)
        # (13:20) o python -c às vezes exits !=0 mesmo COM o wav pronto
        # (cleanup exception pós-synth) — sucesso = wav existe e tem
        # conteúdo (> header 44 bytes). rc ignora.
        try:
            return Path(out_wav).stat().st_size > 44
        except Exception:
            return False

    def _synthesize(self, text, wav_path):
        """Sintetiza com a voz certa por run e costura os wavs."""
        import wave as _w
        text = "".join(ch for ch in text if ch != "*")  # (12:50) asterisco
        runs = self._split_script(text)
        if len(runs) == 1 and not runs[0][1]:
            # (13:50, dono: 'tá comendo r, japonês falando português')
            # o faber É do engine 2023; o piper1.8 remapeia os phonemes
            # e destrói o PT. piper 2023 = voz PT nativa e limpa.
            r = subprocess.run(
                ["/home/nixos/models/piper/bin/piper", "-m", self.VOICE,
                 "--output_file", wav_path],
                input=runs[0][0] + "\n", capture_output=True, text=True,
                encoding="utf-8", timeout=60)
            try:
                return Path(wav_path).stat().st_size > 44
            except Exception:
                return False
        # multi-voz: sintetiza cada run, concatena
        import tempfile as _tf
        parts = []
        ok = True
        for i, (seg, ja) in enumerate(runs):
            with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                part = f.name
            if ja:
                if self._piper1_synth(self.VOICE_JA, seg, part):
                    parts.append(part)
                else:
                    log(f"[{ts()}] run JP falhou — pulado: {seg[:20]!r}")
            else:
                part2 = part
                r = subprocess.run(
                    ["/home/nixos/models/piper/bin/piper", "-m", self.VOICE,
                     "--output_file", part2],
                    input=seg + "\n", capture_output=True, text=True,
                    encoding="utf-8", timeout=60)
                if Path(part2).stat().st_size > 44:
                    parts.append(part2)
                else:
                    ok = False
        if not parts:
            return False
        # concatena (todos piper = mono 22050)
        with _w.open(parts[0], "rb") as w0:
            params = w0.getparams()
            frames = [w0.readframes(w0.getnframes())]
        for part in parts[1:]:
            with _w.open(part, "rb") as w1:
                if w1.getframerate() == params.framerate:
                    frames.append(w1.readframes(w1.getnframes()))
        with _w.open(wav_path, "wb") as out:
            out.setparams(params)
            for fr in frames:
                out.writeframes(fr)
        for part in parts:
            Path(part).unlink(missing_ok=True)
        return ok
    def asr_reset(self):
        # (12:10) limpa o VAD do asrd pós-fala (tail do eco)
        try:
            if getattr(self, "_asr", None):
                self._asr.feed_raw('{"reset": true}')
        except Exception:
            pass
    def _worker(self):
        import tempfile
        while True:
            text = self.q.get()
            t0 = time.monotonic()
            # (11:40) JANELA IN-PROCESS (lock-arquivo extinto: ficava
            # PRESO quando o worker morria → asrd famingo p/ sempre).
            self.speaking["until"] = float("inf")
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    wav = f.name
                # (07:50, o dono não ouviu!) o piper IGNORA output_file no
                # JSON — escrevia hash-no-CWD e o aplay nunca achava o wav
                # (falha SILENT, returncode 0). --output_file é ARGUMENTO.
                # (08:20, dono: "falou text dnv") o CLI 2023 do piper lê
                # TEXTO PURO por linha — o JSON era do piper novo; a
                # chave "text" era FALADA em alta. Acentos: encoding
                # utf-8 real, nada de escapes.
                okk = self._synthesize(text, wav)
                if okk and Path(wav).exists():
                    subprocess.run(["aplay", "-q", wav], timeout=60)
                else:
                    log(f"[{ts()}] tts FALHOU: synth={okk} wav={Path(wav).exists()}")
                self.last_ms = (time.monotonic() - t0) * 1000
                Path(wav).unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] tts ERRO: {exc}")
            finally:
                self.speaking["until"] = time.monotonic() + 1.0
                self.asr_reset()   # (12:10) o tail do eco morre AQUI:
                                   # sem o reset o VAD fecha segmento com
                                   # a própria voz e o modelo responde a si
    def close(self):
        pass  # piper por-frase: sem daemon pra matar

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--stt-model", default="small")
    ap.add_argument("--rms", type=int, default=700,
                    help="gate fala-vs-fundo (vozes reais 886-1372; anime 380-600)")
    ap.add_argument("--gate", default="on", choices=["on", "off"],
                    help="gate 'Jarvis/?': off = responde TODO segmento (testes/AFK); "
                         "o gate real de áudio = wakeword recalibrado (pend.4)")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    try:
        http(base + "/health")
    except Exception:
        sys.exit(f"duplex-voice: server {base} fora — systemctl start llama-duplex-35b")

    # MIC PRIMEIRO (node vivo), depois exclusividade + acordar.
    mic = mic_stream()
    time.sleep(1.5)
    Path("/tmp/jarvis-duplex-mode.flag").touch()   # heal respeita (17/10)
    subprocess.run(["systemctl", "--user", "stop", "jarvis-wakeword.service"],
                   capture_output=True)
    log(f"[{ts()}] wakeword pausado (flag pro heal) — mic aberto antes, node vivo")
    # (18/10 06:20) PIVÔ do dono: duplex VOZ no 4B-MTP (:8092, 70 t/s —
    # ticks ~100ms = tempo real de verdade) em vez do 35B (tick 0.4-12s
    # sob contenção). O MicroTurn-LoRA é do 35B (camadas 36-39, não casa
    # no 4B): o protocolo roda NO BASE com a regra do ban client-side
    # ("a prompt alone gets part of this behaviour" — card). LoRA vira
    # OPCIONAL: se o server tem adapter, aplica; senão segue no base.
    adapters = []
    try:
        adapters = http(base + "/lora-adapters") or []
    except Exception:
        pass
    # id do '<listen>' neste server (ban p/ resposta forçada; b9190 não
    # expõe probs — o id direto funciona em qualquer build)
    global LISTEN_TOKEN_ID, GATE_MODE
    GATE_MODE = args.gate
    try:
        toks = http(base + "/tokenize", {"content": "<listen>"})
        ids = toks.get("tokens") or toks.get("tokens_full") or []
        if toks.get("tokens_full"):
            ids = [t["id"] for t in toks["tokens_full"]]
        LISTEN_TOKEN_ID = ids[0] if ids else None
    except Exception:
        LISTEN_TOKEN_ID = None
    if adapters:
        log(f"[{ts()}] acordando: LoRA {adapters[0].get('path','?')[-40:]} apply…")
        http(base + "/lora-adapters",
             [{"id": a["id"], "scale": a.get("scale", 1.0)} for a in adapters],
             timeout=600)
        log(f"[{ts()}] MODO DUPLEX (com LoRA). Fala com ele. Ctrl-C = dormir.")
    else:
        log(f"[{ts()}] MODO DUPLEX no BASE (sem LoRA — 4B-MTP). Fala! Ctrl-C = dormir.")

    global HUNSPELL_DICT
    HUNSPELL_DICT = _resolve_dict()
    log(f"[{ts()}] hunspell dict: {HUNSPELL_DICT or 'NENHUM (sem correção)'}")
    speaking = {"until": 0.0}   # self-mute anti-eco (18/10 ~06h)
    asr = Asr(args.stt_model, args.lang)
    tts = Tts(speaking)
    tts._asr = asr   # (12:10) o asr_reset pós-fala precisa do pipe do asrd
    mic_q = queue.Queue(maxsize=6)
    threading.Thread(target=mic_reader, args=(mic, mic_q), daemon=True).start()

    history: list[tuple[str, str]] = []
    frase: list[str] = []
    quiet = 0
    tick_n = 0
    prev_pcm, prev_rms = None, 0
    zeros = 0
    pending = []              # (12:00) merge de segmentos
    merge_deadline = 0.0
    running = True

    def _sair(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sair)

    next_t = time.monotonic()
    try:
        while running:
            next_t += TICK
            t0 = time.monotonic()
            heard = NOVOICE
            # (09:55) MÚSICA/FUNDO → NÃO responde (o dono: "não precisa
            # reagir"). O VAC manda 'no online update, only VAD voice' ou
            # texto curto; segmentos <3 chars (garbage whisper) são descartados.
            if (heard and heard != NOVOICE and
                    (len(heard.replace(" ", "")) < 4
                     or "MÚSICA" in heard.upper()
                     or "MUSIC" in heard.upper())):
                heard = NOVOICE
            # (05:00, v6.4) CONSOME TUDO, pareia CONSECUTIVO: o tick LLM
            # (~400ms) + 1-chunk-por-iteração = deficit 40% → reader dropava
            # → pares com BURACO no meio (fragmento+salto+fragmento) → VAD
            # recusava (e bem!). Agora: drena tudo, pares de chunks
            # consecutivos (janela 1.2s contínua), sobra ímpar vira pendente
            # p/ próxima iteração. Fila 6 = 3.6s de folga sem drop.
            chunks: list = []
            try:
                while True:
                    c = mic_q.get_nowait()
                    if c is None:   # stream morreu → reabre
                        log(f"[{ts()}] mic stream morta — reabrindo")
                        mic.terminate()
                        mic = mic_stream()
                        threading.Thread(target=mic_reader, args=(mic, mic_q),
                                          daemon=True).start()
                        continue
                    chunks.append(c)
            except queue.Empty:
                pass
            if not chunks:
                chunks = [mic_q.get()]   # nada novo: espera o próximo (pace natural)
            if prev_pcm is not None:
                chunks.insert(0, prev_pcm)
            # rms do tick = o do último chunk consumido (visibilidade)
            last16 = np.frombuffer(chunks[-1], dtype=np.int16) if isinstance(chunks[-1], (bytes, bytearray)) else chunks[-1]
            rms = int(np.sqrt((np.asarray(last16, dtype=np.int16).astype(np.float64) ** 2).mean()))
            zeros = zeros + 1 if rms == 0 else 0
            # (06:50) STREAMING: cada chunk 0.6s vai DIRETO pro asrd (o
            # VAC/LocalAgreement cuida de contexto e bordas — sem pares).
            tts_playing = time.monotonic() < speaking["until"]
            force = False
            # (07:00) O VAC PRECISA DO SILÊNCIO PÓS-FALA pra fechar o
            # segmento — o gate RMS 700 nunca mandava os chunks quietos e
            # o segmento ficava aberto pra sempre ('only VAD voice').
            # O VAC faz a própria detecção de fala: feed INCONDICIONAL
            # (só o eco-mute segura). Gate vira só telemetria/eco.
            for c in chunks:
                c16 = c if isinstance(c, np.ndarray) else np.frombuffer(c, dtype=np.int16)
                crms = int(np.sqrt((c16.astype(np.float64) ** 2).mean()))
                if tts_playing:
                    continue  # própria voz tocando: eco fora
                asr.feed(c16.astype("float32") / 32768.0)
            r = asr.take()
            if isinstance(r, dict) and r.get("text"):
                heard = r["text"]
                # (10:25) MÚSICA/garbage AQUI (depois do take — antes o
                # filtro rodava com o heard VELHO e nunca pegava):
                # [MÚSICA*], <3 chars = ruído whisper.
                if ("MÚSICA" in heard.upper() or "MUSIC" in heard.upper()
                        or len(heard.replace(" ", "")) < 4):
                    log(f"[{ts()}] ruído/música — descartado: {heard[:30]!r}")
                    heard = NOVOICE
                else:
                    # (12:00) MERGE-ESPERA: o VAD fragmenta fala contínua
                    # em pedaços ('E salo.') — espera 800ms; se vier mais
                    # fala, JUNTA e espera de novo. Responde só a
                    # utterância completa. Backchannels sozinhos = silêncio.
                    fixed = lex_fix(fix_stt(heard))
                    if fixed != heard:
                        log(f"[{ts()}] correção STT: {heard!r} → {fixed!r}")
                    heard = fixed
                    print(f"  SEGMENTO: {heard}", flush=True)
                    if is_backchannel(heard):
                        log(f"[{ts()}] backchannel ('{heard}') — segue ouvindo")
                        heard = NOVOICE
                    else:
                        pending.append(heard)
                        heard = NOVOICE
                        merge_deadline = time.monotonic() + 0.8
                        force = False   # o merge decide quando responder
            elif pending and not force and heard != NOVOICE:
                # mais fala durante a espera? renova (frase contínua)
                merge_deadline = time.monotonic() + 0.8

            tts_on = time.monotonic() < speaking["until"]
            if force and tts_on:
                # (10:25, pesquisa) falando = não decide: eco/segmento
                # fantasma do próprio tail NÃO gera resposta.
                log(f"[{ts()}] segmento durante própria fala — eco, calado")
                force = False
            # (12:00) MERGE: se há fala pendente e a deadline passou
            # sem mais segmentos = utterância completa → RESPONDE junta.
            if (pending and not force
                    and time.monotonic() >= merge_deadline):
                heard = " ".join(pending)
                pending.clear()
                if is_self_echo(heard):
                    log(f"[{ts()}] AUTO-ECO textual — descartado: {heard[:40]!r}")
                    heard = NOVOICE
                elif not is_backchannel(heard):
                    force = True
                log(f"[{ts()}] utterância completa: {heard[:60]!r}")
            said, _p = tick_once(base, history, heard, force_speak=force, tts=tts)
            if not force and said != LISTEN:
                # (07:15) ticks micro-turn SEM força (4B base, sem LoRA,
                # b9190 sem probs) babblam template ('assistant') — silêncio:
                # só a resposta do chat endpoint fala.
                said = LISTEN
            history += [("user", heard), ("assistant", said)]
            if len(history) > 60:   # cap: 30 pares; ctx nunca estoura
                del history[:len(history) - 60]
            llm_ms = (time.monotonic() - t0) * 1000
            tick_n += 1

            if said == LISTEN:
                quiet += 1
            else:
                quiet = 0
                frase.append(said)
                print(f"  ouvi: {heard:<28} digo: {said}  (asr {asr.last_ms:.0f}ms)",
                      flush=True)
                LAST_RESPONSES.append(said)
                if said.rstrip().endswith((".", "!", "?")) or len(frase) >= 3:
                    log(f"[{ts()}] TTS({' '.join(frase)})")
                    tts.say(" ".join(frase)); frase = []
            if quiet >= 2 and frase:
                tts.say(" ".join(frase)); frase = []; quiet = 0

            if (heard != NOVOICE or said != LISTEN or rms >= args.rms
                    or tick_n % 20 == 0):
                log(f"[{ts()}] rms={rms:>5} | {heard[:24]:<24} → {said[:28]:<28} "
                    f"asr={asr.last_ms:4.0f}ms llm={llm_ms:4.0f}ms"
                    f"{' ZERO×' + str(zeros) if zeros else ''}")

            dt = next_t - time.monotonic()
            if dt > 0:
                time.sleep(dt)
    finally:
        log(f"\n[{ts()}] dormindo (LoRA off)…")
        try:
            http(base + "/lora-adapters", [])
        except Exception:
            pass
        mic.terminate()
        asr.close()
        tts.close()
        subprocess.run(["systemctl", "--user", "start", "jarvis-wakeword.service"],
                       capture_output=True)
        Path("/tmp/jarvis-duplex-mode.flag").unlink(missing_ok=True)
        log(f"[{ts()}] dormindo: LoRA off, wakeword de volta, flag removida")

if __name__ == "__main__":
    main()
