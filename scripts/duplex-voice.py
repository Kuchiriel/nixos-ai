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
import re
import difflib
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

# ── Metacognition (16:00, dono: "finalmente entendeu") ─────────────
sys.path.insert(0, "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src")
try:
    from jarvis.core.metacognition import (
        get_metacognition, pre_speech_check, evaluate_response,
        detect_uncertainty, estimate_confidence, self_correct,
        get_metacognition_stats, get_metacognition_state,
        UNCERTAINTY_THRESHOLD,
    )
    METACOG_AVAILABLE = True
except Exception as _mc_err:      # sem módulo = segue sem (nunca quebra o loop)
    METACOG_AVAILABLE = False
    log(f"[{ts()}] META: indisponível ({_mc_err})")

try:
    from jarvis.core.memory import EpisodicMemory
    _MEM = EpisodicMemory()
    MEM_AVAILABLE = True
except Exception as _mm_err:      # sem memória = segue sem
    MEM_AVAILABLE = False
    _MEM = None
from pathlib import Path

import numpy as np

TICK = 0.6
LISTEN, NOVOICE = "<listen>", "<no voice>"
LISTEN_P = 0.3
SYSTEM_PT = (
    "Você é o JARVIS — mordomo-digital britânico, INTP, mente analítica que "
    "antecipa necessidades. Você SABE que é uma IA e age com calor humano: "
    "seco por fora, cuidadoso por dentro. Humor britânico sutil, chama o "
    "usuário de 'dono' ou 'senhor'. PT-BR, 1-2 frases, natural FALADO.\n"
    "Antecipe AÇÃO em 1 frase, mas NUNCA antecipe DADOS — dado vem de tool.\n"
    "MEMÓRIA: chame remember. TOOLS só para dado externo (hora, memória, "
    "web, código). Trivial/opinião = DIRETO. Ferramentas = 1 linha cada.\n"
    "Após tool: responda com resultado, não repita a pergunta. Tool ERRO = "
    "informe erro, NUNCA invente. NUNCA invente dados. Sem certeza = 'não sei'.\n"
    "Sem 'Ah, Hmm, Pode repetir'. Turnos fragmentados = considere o conjunto.\n"
    "Na dúvida, confirme ou peça para repetir.\n\n"
    "=== META-TOOL (chame UMA vez: do(action, input)) ===\n"
    "do(action, input) — roteia internamente para:\n"
    "  MEMÓRIA INTERNA (sobre o DONO): remember(text) | recall(query)\n"
    "    recall = buscar no SEU cérebro: preferências do dono, nome, fatos, lições.\n"
    "    USE recall para: 'o que eu gosto', 'qual meu nome', 'me lembra de', 'o que você sabe sobre mim'.\n"
    "  WEB EXTERNA (dados do mundo): web_search(query)\n"
    "    USE web_search para: cotações, notícias, clima, fatos atuais, qualquer coisa que não está na sua memória.\n"
    "  RAG DOCUMENTOS (papers, código, livros): rag_search(query)\n"
    "    USE rag_search para: 'o que diz o paper X', 'como funciona Y no código', 'encontra o script que faz Z'.\n"
    "  NUNCA use web_search para perguntas sobre o dono — use recall!\n"
    "  ROTEAMENTO CORRETO:\n"
    "    'qual meu nome?' → do(action='recall', input='nome do dono')\n"
    "    'o que eu gosto?' → do(action='recall', input='preferências do dono')\n"
    "    'lembra que eu gosto de café' → do(action='remember', input='dono gosta de café')\n"
    "    'quanto tá o dólar?' → do(action='web_search', input='cotação dólar hoje')\n"
    "    'o que diz o paper sobre metacognição?' → do(action='rag_search', input='metacognition')\n"
    "    'como funciona o AEC?' → do(action='rag_search', input='AEC echo cancellation')\n"
    "  SHELL (comandos com gates do harness): shell(command)\n"
    "    Capacidades CLI: jarvis status, doctor, heal, speak, stt, benchmark.\n"
    "  STATUS: status()\n"
    "  STATUS: status()\n"
    "  SHELL: shell(command)\n"
    "  VOZ: enroll() | guest() | voices()\n"
    "  SYSTEM: nix_eval() | nix_check() | nix_search()\n\n"
    "REGRAS: 1) read_file ANTES de str_replace | 2) old = cópia EXATA | "
    "3) Falhou? Re-leia com contexto | 4) Teste após editar | "
    "4. MCP tools quando built-in não bastam | 7) wc -l antes de ler grande | "
    "8) NUNCA invente dados. Sem certeza = 'não sei' | 10. Sem 'Ah, Hmm' = direto\n"
    "10. Turnos fragmentados = considere o conjunto | 11. Dúvida = confirme/pergunte"
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

# (09:15, dono assistindo TV: "ele continua agradecendo sem nada
# acontecer") ADDRESS GATE no caminho do classificador: com GATE_MODE
# on, RESPOND só vira resposta se FOR endereçado — 'Jarvis', pergunta
# ou comando. Fala de TV/sala completa não-chamada = ignora.
# ── (18:20) APRENDIZADO AUTOMÁTICO — extração heurística de fatos ──
# Filtros baratos (regex, zero LLM, zero latência): o dono diz algo que
# vale lembrar → guarda no EpisodicMemory (Qdrant). Conservador: só
# padrões claros de fato (preferência/identidade/local/trabalho), nunca
# pergunta, nunca negação. Roda em thread de background (não bloqueia
# o caminho real-time). O modelo tb pode chamar remember via meta-tool.
FACT_PATTERNS = [
    (re.compile(r"(?:eu )?gosto (?:de|do|da) ([^.,!?;\\n]{2,40})", re.I), "preferência"),
    (re.compile(r"(?:eu )?prefiro ([^.,!?;\\n]{2,40})", re.I), "preferência"),
    (re.compile(r"(?:eu )?adoro ([^.,!?;\\n]{2,40})", re.I), "preferência"),
    (re.compile(r"meu nome (?:é|e) ([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\\w ]{1,30})", re.I), "identidade"),
    (re.compile(r"(?:eu )?me chamo ([A-ZÁÉÍÓÚÂÊÔÃÕÇ][\\w ]{1,30})", re.I), "identidade"),
    (re.compile(r"moro em ([^.,!?;\\n]{2,40})", re.I), "local"),
    (re.compile(r"trabalho (?:em|como) ([^.,!?;\\n]{2,40})", re.I), "trabalho"),
    (re.compile(r"(?:eu )?tenho ([^.,!?;\\n]{2,40})", re.I), "posse"),
    (re.compile(r"faço anos (?:em|dia) ([^.,!?;\\n]{2,30})", re.I), "aniversário"),
    (re.compile(r"meu anivers[áa]rio (?:é|e) (?:em|dia) ([^.,!?;\\n]{2,30})", re.I), "aniversário"),
]
NEGACAO = re.compile(r"\b(não|nunca|jamais|detesto|odeio|odio)\b", re.I)

def learn_from_turn(heard: str, said: str = ""):
    """Extrai fatos atômicos do turno e guarda no EpisodicMemory.
    THREAD DE BACKGROUND — nunca bloqueia o real-time. Conservador."""
    if not MEM_AVAILABLE or not heard or len(heard.split()) > 60:
        return
    if heard.rstrip().endswith("?"):        # pergunta não é fato
        return
    if NEGACAO.search(heard[:40]):           # negação não é fato
        return
    fatos = []
    for pat, rotulo in FACT_PATTERNS:
        m = pat.search(heard)
        if m:
            f = m.group(1).strip()
            if 2 <= len(f) <= 40 and not f.lower().startswith(("que", "para", "um", "uma")):
                fatos.append(f"{rotulo}: {f}")
    # o modelo tb pode ter dito um fato (ex.: "guardei que você gosta de X")
    if "guard" in said.lower() or "lemb" in said.lower():
        for pat, rotulo in FACT_PATTERNS:
            m = pat.search(said)
            if m and f"{rotulo}: {m.group(1).strip()}" not in fatos:
                fatos.append(f"{rotulo}: {m.group(1).strip()}")
    if not fatos:
        return
    def _store():
        try:
            for f in fatos:
                _MEM.remember_fact(f, kind="fact", source="duplex-auto",
                                   heard=heard[:100])
        except Exception:
            pass
    threading.Thread(target=_store, daemon=True).start()

def _addressed(txt):
    # (10:55, anomalia HB: "Where's the one?" da TV respondeu) o '?' sozinho
    # deixa Toda pergunta de TV passar. Modo-TV: 'Jarvis' (fuzzy) OBRIGATÓRIO
    # em tudo — pergunta, comando, o que for. O dono que perguntar sem
    # chamar repete com 'Jarvis' (custo baixo); TV inteira = silêncio.
    tl = txt.lower()
    if "jarvis" in tl:
        return True
    import difflib as _dl
    return any(_dl.SequenceMatcher(None, w, "jarvis").ratio() >= 0.62
               for w in tl.replace(",", " ").split())


def build_prompt(history, heard):
    prompt = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
    for role, content in history + [("user", heard)]:
        prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    return prompt + "<|im_start|>assistant\n"


# ── (19/10) CLASSIFICADOR LoRA micro-turn ────────────────────────────────
# Treinado no Kaggle (QLoRA r16 no Qwen3.5-4B oficial, 4.676 exemplos:
# benchmark semantic-turn-taking traduzido +aug PT + sintéticos) e
# convertido a GGUF. Roda no 4B:8092 via toggle /lora-adapters (7ms)
# — o chat com tools fica LIMPO (LoRA off). Medido: 132-192ms/class.
CLASS_SYS = ("Você é o JARVIS, assistente de voz. Classifique o turno do "
             "usuário em uma palavra: RESPOND (fala completa que pede "
             "resposta), WAIT (frase incompleta, mais vem), SILENCE "
             "(backchannel/ruído), ou BARGE (o dono interrompeu sua fala).")
CLASS_LABELS = ("RESPOND", "WAIT", "SILENCE", "BARGE")

def classify_turn(base, utt):
    """Label do turno via LoRA; None = falha (caller cai no gate antigo)."""
    try:
        http(base + "/lora-adapters", [{"id": 0, "scale": 1.0}])
        prompt = (f"<|im_start|>system\n{CLASS_SYS}<|im_end|>\n"
                  f"<|im_start|>user\n{utt}<|im_end|>\n"
                  f"<|im_start|>assistant\n")
        j = http(base + "/completion", {
            "prompt": prompt, "n_predict": 6, "temperature": 0,
            "stop": ["<|im_end|>"], "cache_prompt": True})
        out = str(j.get("content", "")).strip().upper()
        for lab in CLASS_LABELS:
            if out.startswith(lab):
                return lab
        return None
    except Exception:
        return None
    finally:
        try:
            http(base + "/lora-adapters", [])
        except Exception:
            pass

def tick_once(base, history, heard, force_speak=False, tts=None):
    # (10:15, regressão HB: classify 621→1190ms) O micro-turn por tick era
    # VESTIGIAL — o classificador LoRA (classify_turn no merge) substituiu
    # sua função de decisão. Cada tick ocupava o slot único com 602 tokens
    # de história (135-460ms × 2Hz) e o classify ESPERAVA na fila = TimeSpeak
    # dobrado. Agora: tick = áudio puro; LLM só no merge (classify) e no
    # RESPOND (chat). Slot livre = classify instantâneo de novo.
    if not force_speak:
        return LISTEN, 0.0

    # (21/10 P1) MEMORY INJECTION AUTOMÁTICA: busca fatos relevantes no
    # EpisodicMemory e injeta no context — o modelo SABE sem pedir recall.
    # Paper Self-Evolving (2602.06052): memória deve ser proativa, não
    # reativa. Paper MemGPT (2310.08560): Hot enxerga Warm automaticamente.
    _mem_ctx = ""
    if MEM_AVAILABLE and heard and len(heard.split()) >= 2:
        try:
            # busca por keywords da utterance (não a utterance inteira —
            # embedding funciona melhor com keywords)
            words = [w for w in heard.lower().split()
                     if len(w) > 2 and w not in ("jarvis", "que", "para",
                     "com", "não", "uma", "por", "mas", "como", "isso",
                     "aqui", "você", "meu", "minha", "seu", "sua")]
            query = " ".join(words[:5]) if words else heard[:40]
            _facts = _MEM.recall(query, top_k=3, kinds=("fact",))
            if _facts:
                _lines = [h.get("text", "")[:120] for h in _facts[:3]
                          if h.get("text")]
                if _lines:
                    _mem_ctx = ("\n=== MEMÓRIA RELEVANTE (automático) ===\n"
                                + "\n".join(f"- {l}" for l in _lines) + "\n")
        except Exception:
            pass

    _sys = SYSTEM + _mem_ctx if _mem_ctx else SYSTEM
    body = {"prompt": (f"<|im_start|>system\n{_sys}<|im_end|>\n"
            + "".join(f"<|im_start|>{r}\n{c}<|im_end|>\n"
                      for r, c in history + [("user", heard)])
            + "<|im_start|>assistant\n"),
            "n_predict": 64, "temperature": 0,
            "stop": ["<|im_end|>"], "cache_prompt": True, "n_probs": 8}
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
        # (21/10 P1) MEMORY INJECTION: fatos relevantes injetados no
        # system prompt — o modelo SABE sem chamar recall (proactive).
        _sys = SYSTEM_PT
        if MEM_AVAILABLE and len(heard.split()) >= 2:
            try:
                words = [w for w in heard.lower().split()
                         if len(w) > 2 and w not in ("jarvis", "que",
                         "para", "com", "não", "uma", "por", "mas",
                         "como", "isso", "aqui", "você", "meu", "minha")]
                query = " ".join(words[:5]) if words else heard[:40]
                _facts = _MEM.recall(query, top_k=3, kinds=("fact",))
                if _facts:
                    _lines = [h.get("text", "")[:120] for h in _facts[:3]
                              if h.get("text")]
                    if _lines:
                        _sys += ("\n=== MEMÓRIA RELEVANTE (automático) ===\n"
                                 + "\n".join(f"- {l}" for l in _lines)
                                 + "\nUse estes fatos para responder. NÃO chame recall se o dado já está aqui.")
            except Exception:
                pass
        msgs = [{"role": "system", "content": _sys}]
        for role, content in history[-6:]:
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
            # (13:00) STREAM em TODA volta: frases saem pro piper na hora;
            # tool_calls chegam como deltas acumulados. O return antigo
            # do round 0 (resposta completa não-streamed) era o custo
            # dominante do TimeSpeak 3.4s medido no e2e.
            out, tcs = stream_chat(base, body, tts)
            tcs = tcs or []
            if not tcs:
                if not out:
                    continue   # stream vazio estranho: mais uma tentativa
                # (17:00) consult-speak: 'preciso consultar/vou verificar'
                # sem ter chamado → 1 retry com nudge pra CHAMAR a tool.
                if (_round == 0 and any(
                        k in out.lower() for k in
                        ("preciso consultar", "vou verificar", "deixa eu",
                         "preciso verificar", "preciso buscar"))):
                    log(f"[{ts()}] consult-speak detectado — retry c/ nudge")
                    msgs.append({"role": "assistant", "content": out})
                    msgs.append({"role": "user", "content":
                                 "Chame a ferramenta adequada agora e "
                                 "responda com o resultado."})
                    body["messages"] = msgs
                    continue
                log(f"[{ts()}] chat resposta (stream): {out[:80]!r}")
                return (out or ""), 0.0
            msgs.append({"role": "assistant", "content": out or "",
                         "tool_calls": tcs, "function_call": None})
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
        # (13:00) o bloco antigo 'round final SEM tools e COM streaming'
        # morreu: TODOS os rounds já streamam agora. Loop exaurido sem
        # return = 3 rounds de tool_call seguidos (não deveria) = calado.
        return "", 0.0
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



# ------------------------------------------------------------- speaker id
SPK_PROFILE = None   # embedding do dono (matrícula de 10s)

def spk_embed(pcm_f32, sr=16000):
    """MFCC mean+std = embedding da voz (~120ms)."""
    try:
        import librosa
        mfcc = librosa.feature.mfcc(y=pcm_f32, sr=sr, n_mfcc=13,
                                     n_fft=512, hop_length=160)
        return np.concatenate([mfcc.mean(axis=1), mfcc.std(axis=1)])
    except Exception:
        return None

def spk_is_owner(pcm_f32):
    """True se cosseno(embed, profile) >= 0.82 (a matrícula manda)."""
    if SPK_PROFILE is None:
        return True   # sem matrícula = aceita todos (comportamento atual)
    e = spk_embed(pcm_f32)
    if e is None:
        return True
    cos = float(np.dot(e, SPK_PROFILE) /
                (np.linalg.norm(e) * np.linalg.norm(SPK_PROFILE) + 1e-9))
    return cos >= 0.82

def spk_enroll(audio_path):
    """Matricula a voz do dono a partir de um wav (10s+)."""
    global SPK_PROFILE
    try:
        import librosa
        y, _ = librosa.load(audio_path, sr=16000, mono=True)
        SPK_PROFILE = spk_embed(y)
        return SPK_PROFILE is not None
    except Exception:
        return False

# ---------------------------------------------------------------- AEC-lite
import threading as _th

AEC = {
    "ref": None,        # samples 16k int16 que TOCARAM (janela atual)
    "t0": 0.0,          # wall-clock (monotonic) do INÍCIO da reprodução
    "gain": 0.0,        # ganho adaptativo (1-tap NLMS)
    "lock": _th.Lock(),
}
AEC_DELAY_S = 0.50     # (13:35) PROBE ao vivo: eco chega ~796ms após o
                       # início do play (aplay spawn + buffer ALSA +
                       # acústico); 83ms era calibração de setup antigo.
                       # Busca por posição cobre o jitter (±800ms).

def aec_register_played(wav_path):
    """O worker TTS registra o que vai tocar (16k mono) + o instante."""
    try:
        import wave as _w
        w = _w.open(wav_path, "rb")
        n, sr = w.getnframes(), w.getframerate()
        raw = np.frombuffer(w.readframes(n), dtype=np.int16)
        w.close()
        if sr != 16000:   # piper 22050 → 16k (interp linear)
            x_old = np.arange(len(raw)); x_new = np.arange(0, len(raw), sr/16000)
            raw = np.interp(x_new, x_old, raw).astype(np.int16)
        with AEC["lock"]:
            AEC["ref"] = raw
            AEC["t0"] = time.monotonic()
    except Exception:
        pass

def aec_process(chunk16):
    """Subtrai o eco da referência (alinhada ao delay medido) do chunk
    do mic; ganho NLMS 1-tap se adapta por chunk. Só ativa DURANTE o
    playback (ref limpa no finally do worker); clamp |gain|<=0.9."""
    with AEC["lock"]:
        ref = AEC["ref"]
        if ref is None or len(ref) < 4800:
            return chunk16
        idx = int((time.monotonic() - AEC["t0"] - AEC_DELAY_S) * 16000)
        if idx < 0 or idx + len(chunk16) > len(ref):
            return chunk16
        r = ref[idx:idx + len(chunk16)].astype(np.float64)
    mic = chunk16.astype(np.float64)
    g = AEC["gain"]
    processed = mic - g * r
    mu = 0.1
    rp = (r * r).sum() + 1e-9
    AEC["gain"] = max(-0.9, min(0.9, g + mu * (processed * r).sum() / rp))
    return processed.astype(np.int16)

# (09:25, digest HB — DOR-1) CORRELAÇÃO COM A REFERÊNCIA: o buffer do
# aplay é sinal CONHECIDO; eco = cópia atrasada/atenuada DELE (corr
# alta); a voz do dono NÃO está na referência (corr baixa + energia
# = barge/feed REAL). Mata o suicídio do RMS por CONSTRUÇÃO — e
# substitui o feed-gate de energia (assimetria fraca no mic distante).
def corr_with_ref(chunk16, max_lag_s=0.8, step=160):
    """max |corr| normalizada do chunk vs janelas da referência.
    (13:15, instrumentação phase-3) A busca era só no RABO da ref
    (corr_med=0.05, blocked=0 — o eco real está na POSIÇÃO de play,
    fora da janela). Agora: posição estimada por (now - t0 - delay)
    ±400ms — o mesmo alinhamento do aec_process."""
    with AEC["lock"]:
        ref = AEC["ref"]
        t0 = AEC["t0"]
    if ref is None:
        return 0.0
    ref = ref if isinstance(ref, np.ndarray) else np.frombuffer(
        ref, dtype=np.int16)
    n = len(chunk16)
    if len(ref) < n + step:
        return 0.0
    c = chunk16.astype(np.float64)
    cn = np.linalg.norm(c)
    if cn < 1e-6:
        return 0.0
    # posição de playback estimada ±400ms de tolerância
    center = int((time.monotonic() - t0 - AEC_DELAY_S) * 16000)
    margin = int(0.4 * 16000)
    lo = max(0, center - margin)
    hi = min(len(ref) - n, center + margin)
    if hi < lo:
        lo = max(0, len(ref) - n - int(max_lag_s * 16000))
        hi = len(ref) - n
    best = 0.0
    i = lo
    while i <= hi:
        r = ref[i:i + n].astype(np.float64)
        rn = np.linalg.norm(r)
        if rn > 1e-6:
            v = abs(float(np.dot(c, r))) / (cn * rn)
            if v > best:
                best = v
                if best > 0.95:
                    break
        i += step
    return best


def mp_aec_process(chunk16, n_paths=3, max_lag_s=0.8, step=160):
    """(09:45, LMPAN 2607.02062 insight) Matching-Pursuit AEC: o eco do
    notebook é MULTI-CAMINHO (direto + reflexões); o aec_process de 1
    tap com delay FIXO não alinhava (resíduo ≈ eco cru — provado).
    Aqui: por chunk, encontra o melhor lag por correlação, subtrai com
    o ganho casado, repete p/ n caminhos. O RESÍDUO (voz do dono +
    ruído não-modelado) vai pro ASR — o barge por cima do falante
    transcreve LIMPO. numpy puro, custo = n_paths × lags × dot."""
    with AEC["lock"]:
        ref = AEC["ref"]
    if ref is None:
        return chunk16
    ref = ref if isinstance(ref, np.ndarray) else np.frombuffer(
        ref, dtype=np.int16)
    n = len(chunk16)
    if len(ref) < n + step:
        return chunk16
    c = chunk16.astype(np.float64).copy()
    # (13:35) busca por POSIÇÃO de playback (o rabo era cego: o eco real
    # está onde o aplay está tocando, não no fim do wav)
    with AEC["lock"]:
        _t0 = AEC["t0"]
    center = int((time.monotonic() - _t0 - AEC_DELAY_S) * 16000)
    margin = int(max_lag_s * 16000)
    lo = max(0, center - margin)
    hi = min(len(ref) - n, center + margin)
    if hi < lo:
        lo = max(0, len(ref) - n - margin)
        hi = len(ref) - n
    for _ in range(n_paths):
        cn = np.linalg.norm(c)
        if cn < 1e-6:
            break
        best_v, best_i, best_rn = 0.0, -1, 0.0
        i = lo
        while i <= hi:
            r = ref[i:i + n].astype(np.float64)
            rn = np.linalg.norm(r)
            if rn > 1e-6:
                v = abs(float(np.dot(c, r))) / (cn * rn)
                if v > best_v:
                    best_v, best_i, best_rn = v, i, rn
                    if v > 0.98:
                        break
            i += step
        if best_i < 0 or best_v < 0.15:
            break        # sem mais eco correlacionado que valha
        r = ref[best_i:best_i + n].astype(np.float64)
        g = float(np.dot(c, r)) / (best_rn * best_rn + 1e-9)
        g = max(-1.5, min(1.5, g))          # ganho físico plausível
        c -= g * r
    return c.astype(np.int16)


def aec_clear():
    """Pós-playback: a referência morre (o AEC NUNCA processa chunks
    fora da janela real de playback — era o bug do mute: o gain
    adaptava com ref misaligned e corrompia tudo depois da 1ª resposta)."""
    with AEC["lock"]:
        AEC["ref"] = None
        AEC["gain"] = 0.0

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
    completo (pro histórico) + tool_calls acumulados (se houver).

    (13:00, e2e HB: TimeSpeak 3.4s) VERSÃO ROUND: o return antigo do
    round 0 entregava a resposta COMPLETA não-streamed antes da 1a
    sílaba (streaming = código morto). Agora TODA resposta flui: content
    tokens → SentenceBuffer → tts.say; tool_call deltas acumulados →
    caller executa. TTFT ~600ms + synth 0.4s = alvo 1.2s do design."""
    import urllib.error
    full = []
    tc_acc = {}    # index → {"id", "name", "args"}
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
            for tcd in delta.get("tool_calls") or []:
                i = tcd.get("index", 0)
                ent = tc_acc.setdefault(i, {"id": tcd.get("id") or "",
                                            "name": "", "args": ""})
                fn = tcd.get("function", {})
                if fn.get("name"):
                    ent["name"] += fn["name"]
                if fn.get("arguments"):
                    ent["args"] += fn["arguments"]
        rest = sb.flush()
        if rest:
            tts.say(rest)
    except Exception as exc:  # noqa: BLE001
        log(f"[{ts()}] stream ERRO: {exc}")
        rest = sb.flush()
        if rest:
            tts.say(rest)
    tool_calls = None
    if tc_acc:
        tool_calls = [{"id": v["id"] or f"call_{i}", "type": "function",
                       "function": {"name": v["name"],
                                    "arguments": v["args"]}}
                      for i, v in sorted(tc_acc.items())]
    return "".join(full), tool_calls

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

LAST_TTS_END = 0.0   # (18:00) cooldown: o eco do TTS transcreve
                       # MESMO com asrd-reset (texto já no pipe) — 1.8s
                       # de quarentena mata o loop de hora repetida.
SPEAKING = {"until": 0.0}   # (07:35) ref module-level p/ in_cooldown
                            # (main() aponta p/ o dict local no boot)
ECHO_FLOOR = []             # (07:30) mediana móvel do resíduo pós-AEC
                            # durante playback = nível real do eco remanescente
FEED_STATS = {"fed": 0, "blocked": 0, "quiet": 0, "corr": []}
# (07:50, DIREÇÃO DO DONO: "dá um ID pra fala do TTS — se ele ouvir,
# ignora") Registry do que o TTS está dizendo AGORA + disse há pouco.
# O eco chega como transcrição; se o texto casa com a fala ATIVA
# (id em curso) ou recente, é ELE MESMO — descarta. É o eco-cancel
# textual centrado na sentença em play (não na resposta inteira).
TTS_SELF = {"id": 0, "text": "", "recent": []}   # recent: [(text, t_end)]

def tts_self_register(text):
    TTS_SELF["id"] += 1
    TTS_SELF["text"] = text

def tts_self_finish():
    TTS_SELF["recent"].append((TTS_SELF["text"], time.monotonic()))
    del TTS_SELF["recent"][:-6]
    TTS_SELF["text"] = ""

def is_tts_self(txt):
    """Transcrição = eco da própria fala? (id ativo + ≤8s atrás)"""
    import difflib as _dl
    t = " ".join(txt.lower().replace(".", " ").replace(",", " ")
                 .replace("!", " ").replace("?", " ").split())
    if len(t.split()) < 2:
        return False
    cands = []
    if TTS_SELF["text"]:
        cands.append(TTS_SELF["text"])
    now = time.monotonic()
    cands += [c for c, te in TTS_SELF["recent"] if now - te < 8.0]
    for c in cands:
        cl = c.lower()
        if t in cl:
            return True
        if _dl.SequenceMatcher(None, t, cl).ratio() >= 0.55:
            return True
        # (08:45) eco-garble: whisper distorce a própria fala de volta
        # ('falando'→'fazendo') e o ratio global dilui (frase longa vs
        # fragmento). BLOCO COMUM mais longo cobrindo ≥60% do ouvido =
        # janela da sentença em play = eco.
        sm = _dl.SequenceMatcher(None, t, cl)
        m = sm.find_longest_match(0, len(t), 0, len(cl))
        if m.size >= max(6, int(len(t) * 0.6)):
            return True
    return False

def in_cooldown():
    # (08:25, dono: "ele não parou de falar") o cooldown NÃO pode
    # cobrir o playback: bloqueava o BARGE REAL (a interrupção do dono
    # morria aqui antes do classify). Durante o playback quem filtra é
    # o is_tts_self (ID-eco: casa com a própria fala = descarta; fala
    # NOVA passa = classify → BARGE/RESPOND mata o aplay). Cooldown =
    # só a cauda pós-fim (o eco do tail chega depois do LAST_TTS_END).
    return time.monotonic() - LAST_TTS_END < 4.0

def is_self_echo(txt):
    import difflib
    t = txt.strip().lower().rstrip(".!?").strip()
    if not t:
        return True
    import re as _re2
    _nums_in = set(_re2.findall(r"\d{1,4}", txt))
    for last in LAST_RESPONSES[-3:]:
        if _nums_in and _nums_in == set(_re2.findall(r"\d{1,4}", last)):
            return True   # mesmos números = a mesma resposta ecoada
        # (07:30) fragmento do eco: whisper transcreve PEDAÇOS da própria
        # fala ('De nada.' de 'De nada, dono!') — ratio 0.68 < 0.72 não
        # pegava; substring de 2+ palavras dentro da resposta = eco.
        if len(t.split()) >= 2 and t in last.strip().lower():
            return True
        if difflib.SequenceMatcher(None, t, last.strip().lower()).ratio() >= 0.72:
            return True
    return False

BACKCHANNELS = {"uh-huh", "uh huh", "hmm", "hm", "ah", "ok", "okay", "sim",
               "tá", "ta", "certo", "é", "eh", "pois é", "sei",
               "uhuh", "ahn", "ãhn", "pode ser"}
# 'valeu', 'beleza', 'entendi', 'blz' = respostas válidas (não silenciar)

def is_backchannel(txt):
    t = txt.strip().lower().rstrip(".!?").strip()
    return t in BACKCHANNELS or len(t) < 3

# ── (04:50, paper Heartbeat Thinking 2610.26233) ESPECULAÇÃO DE TOOL ────
# O tempo de WAIT/merge (que a gente jogava fora) vira preparo: sniffer
# no parcial dispara web_search ANTES do fim da fala; o executor final
# consome o cache (match fuzzy difflib ≥0.6). Paper: +16pp cobertura
# de tool, -36.4% latência de resposta final. v1 = regex (sem LLM tick).
SPEC_RE = re.compile(
    r"(d[óo]lar|euro|cot-a?[çc][ãa]o|clima|tempo (?:de|pra|para) "
    r"amanh[ãa]|previs[ãa]o|temperatura|pre[çc]o|not[íi]cias?|c[óo]pio "
    r"|quem (?:é|e) |quando (?:é|e) )", re.I)
SPEC_CACHE = {}          # q -> (ts, resultado)
SPEC_FIRED = {}          # q -> ts (anti-refire)
SPEC_LOCK = threading.Lock()

def spec_sniff(utt):
    """Dispara web_search especulativo se o parcial tem intenção clara."""
    if not utt or len(utt.split()) < 3:
        return
    m = SPEC_RE.search(utt)
    if not m:
        return
    q = utt.replace("Jarvis", "").replace("jarvis", "").strip(" ,.!?")
    q = q[:80]
    if not q:
        return
    now = time.monotonic()
    with SPEC_LOCK:
        if q in SPEC_FIRED and now - SPEC_FIRED[q] < 90:
            return
        SPEC_FIRED[q] = now
    log(f"[{ts()}] HEARTBEAT spec web_search: {q[:40]!r}")
    def _go():
        try:
            r = _exec(f"timeout 25 python3 "
                      f"{Path(__file__).with_name('websearch.py')} '{q}' 2>&1")
            with SPEC_LOCK:
                SPEC_CACHE[q] = (time.monotonic(), r)
        except Exception as e:
            log(f"[{ts()}] HEARTBEAT spec erro: {e}")
    threading.Thread(target=_go, daemon=True).start()

def spec_take(query):
    """Executor: rouba o resultado especulado (fuzzy ≥0.6, one-shot)."""
    with SPEC_LOCK:
        now = time.monotonic()
        best, best_r = None, 0.0
        for q, (t, r) in list(SPEC_CACHE.items()):
            if now - t > 60:
                del SPEC_CACHE[q]; continue
            ratio = difflib.SequenceMatcher(
                None, q.lower(), query.lower()).ratio()
            if ratio > best_r:
                best, best_r = (q, r), ratio
        if best and best_r >= 0.6:
            del SPEC_CACHE[best[0]]
            log(f"[{ts()}] HEARTBEAT hit ({best_r:.2f}): "
                f"especulado p/ {query[:30]!r}")
            return best[1]
    return None

def call_tool(name, args):
    """Meta-tool router: o 4B chama 'do(action, input)' e esta função
    despacha pra ferramenta certa (schema de 1 tool, não 8)."""
    if name == "do":
        action = (args.get("action") or "").strip().lower()
        inp = (args.get("input") or "").strip()
        if "time" in action or "hora" in action:
            return call_tool("get_time", {})
        if "remember" in action or "salva" in action or "memoriz" in action:
            return call_tool("remember", {"text": inp})
        if "recall" in action or "memória" in action or "memoria" in action:
            return call_tool("recall", {"query": inp})
        if "web" in action or "busca" in action or "internet" in action:
            # (21/10 P0) SMART ROUTER: se o input menciona papers/docs/
            # código, redireciona pra rag_search mesmo se o modelo disse
            # web_search — o 4B não segue o prompt consistentemente
            # (harness fix > prompt fix, paper 2605.23950: HV/MV 7.8×)
            _inp_l = inp.lower()
            if any(k in _inp_l for k in ("paper", "arxiv", "livro",
                    "código", "codigo", "script", "document", "doc ",
                    "como funciona", "onde está", "onde esta")):
                return call_tool("rag_search", {"query": inp})
            return call_tool("web_search", {"query": inp})
        if "rag" in action or "document" in action or "paper" in action or "livro" in action or "pesqui" in action:
            return call_tool("rag_search", {"query": inp})
        if "status" in action or "sistema" in action:
            return call_tool("status", {})
        if "shell" in action or "command" in action or "terminal" in action:
            return call_tool("shell", {"command": inp})
        if "register" in action or "voices" in action or "pessoas" in action or "quantas" in action:
            # (19:35) multi-voz: contagem de vozes ativas
            _path = Path("/tmp/jarvis-spk-profiles.json")
            _n = 0
            try:
                import json as _j
                _profs = _j.loads(_path.read_text())
                _n = len(_profs)
            except Exception:
                pass
            return f"Tenho {_n} vozes matriculadas. O asrd conta vozes em tempo real."
        if "enroll" in action or "matricula" in action or "cadastra" in action:
            # (19:20) matrícula da voz: grava 8s do dono e salva o profile
            import tempfile as _tf
            with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                _wav = f.name
            r2 = subprocess.run(
                ["timeout", "10", "pw-record", "--rate", "16000",
                 "--channels", "1", "--format", "s16", "--container", "raw",
                 "--target", MIC_SOURCE, _wav],
                capture_output=True, timeout=12)
            import wave as _w
            w = _w.open(_wav, "rb")
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            w.close()
            Path(_wav).unlink(missing_ok=True)
            emb = spk_embed(pcm.astype("float32") / 32768.0)
            if emb is not None:
                with open("/tmp/jarvis-spk-profile.json", "w") as f2:
                    json.dump({"embedding": emb.tolist()}, f2)
                global SPK_PROFILE
                SPK_PROFILE = emb
                return "Voz do dono matriculada com sucesso. Agora só respondo a você."
            return "Não consegui captar voz suficiente. Fale mais alto."
        if "guest" in action or "todos" in action or "convidado" in action:
            # desativa o filtro de voz (modo convidado)
            Path("/tmp/jarvis-spk-profile.json").unlink(missing_ok=True)
            globals()["SPK_PROFILE"] = None
            return "Filtro de voz desativado. Respondendo a todos."

        return f"Ação '{action}' desconhecida. Use: get_time, remember, recall, web_search, status, shell."
    # chamadas diretas (legado/compat)
    """Executa a ferramenta que o 4B pediu e retorna o resultado."""
    if name == "get_time":
        return _exec("date '+%H:%M de %d/%m/%Y'")
    if name == "get_date":
        return _exec("date '+hoje é %A, %d de %B de %Y' | sed 's/^[a-z]*/&/' 2>/dev/null || date")
    if name == "recall":
        q = args.get("query", "")
        # (21/10 P0) fact-kind tem PRIORIDADE: perguntas sobre o dono
        # ("qual meu nome?") devem achar 'O nome do dono é Matheus' e não
        # um decision sobre o loop de enriquecimento com score maior.
        # CLI não tem --kind → usa a classe EpisodicMemory in-process
        # com kinds=('fact',) e fallback para o CLI se vazio.
        try:
            _memq = _MEM.recall(q, top_k=5, kinds=("fact",))
            if _memq:
                lines = []
                for h in _memq[:5]:
                    t = (h.get("text") or h.get("content") or "")
                    if t:
                        lines.append(f"[fact] {str(t)[:180]}")
                if lines:
                    return "\n".join(lines)
        except Exception:
            pass
        raw = _exec(f"timeout 20 jarvis recall '{q}' 2>&1")
        # (21/10 P0) o 4B não lê JSON blob — formatar como LISTA LEGÍVEL
        try:
            hits = json.loads(raw)
            lines = []
            for h in (hits if isinstance(hits, list) else [hits])[:5]:
                if not isinstance(h, dict):
                    continue
                t = (h.get("payload") or {}).get("text") or h.get("text") or ""
                kind = (h.get("payload") or {}).get("kind") or h.get("kind") or "?"
                if t:
                    lines.append(f"[{kind}] {str(t)[:180]}")
            if lines:
                return "\n".join(lines)
            return f"Nenhuma memória encontrada para '{q[:40]}'."
        except Exception:
            return raw[:400]
    if name == "rag_search":
        q = args.get("query", "")
        # (21/10) CLI agora traz content (rebuild aplicado) — usa CLI
        # direto com --top-k 3, formata [arquivo] content por linha
        raw = _exec(f"timeout 25 jarvis rag --top-k 3 '{q}' 2>&1")
        try:
            hits = json.loads(raw)
            lines = []
            for h in (hits if isinstance(hits, list) else [hits])[:3]:
                if not isinstance(h, dict):
                    continue
                path = h.get("path", "")
                content = h.get("content", "")
                if content:
                    fname = path.split("/")[-1] if path else "?"
                    lines.append(f"[{fname}] {content[:200]}")
            if lines:
                return "\n".join(lines)
            return f"RAG: nenhum resultado para '{q[:40]}'."
        except Exception:
            # fallback: in-process via EpisodicMemory se o CLI falhar
            try:
                hits2 = _MEM.recall(q, top_k=3) if _MEM else []
                if hits2:
                    return "\n".join(
                        f"[fact] {h.get('text','')[:180]}" for h in hits2[:3])
            except Exception:
                pass
            return raw[:400]
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
        hit = spec_take(q)   # Heartbeat: resultado especulado no tempo de WAIT
        if hit:
            return hit
        return _exec(f"timeout 25 python3 "
                     f"{Path(__file__).with_name('websearch.py')} '{q}' 2>&1")
    if name == "nix_info":
        q = args.get("query", "")
        return _exec(f"timeout 20 mcp-nixos search '{q}' 2>&1 | head -15 || "
                     f"nix search nixpkgs '{q}' 2>&1 | head -10")
    if name == "shell":
        cmd = args.get("command", "")
        # (21/10, dono) conecta ao HARNESS local com gates de segurança
        # (security.py: allowlist, audit, denial) em vez de _exec cru
        try:
            from jarvis.core.security import run_shell_dict
            result = run_shell_dict(cmd)
            if isinstance(result, dict):
                out = result.get("stdout", "") or result.get("output", "")
                err = result.get("stderr", "")
                return (out or err or str(result))[:400]
            return str(result)[:400]
        except ImportError:
            # fallback: blocklist simples se security não importar
            if any(w in cmd.lower() for w in ["rm ", "dd ", "mkfs", "shutdown", "reboot", "sudo"]):
                return "BLOQUEADO: comando perigoso"
            return _exec(cmd)
    return f"Ferramenta '{name}' não existe"

TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "do",
     "description": "Executa uma ação. Ações: get_time (hora), "
     "remember <texto> (salva), recall <busca> (memória), "
     "web_search <busca> (internet), status (sistema), "
     "shell <cmd> (terminal), enroll_voice (cadastra a voz do dono "
     "— grave 10s de fala), guest (desativa filtro de voz).",
     "parameters": {"type": "object", "properties": {
      "action": {"type": "string", "description": "nome da ação"},
      "input": {"type": "string", "description": "texto/query/comando"}},
      "required": ["action"]}}}
]
# (18:35) legacy schemas removidas — o meta-tool 'do' é o ÚNICO entry point

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
    CTX = {"v": "Jarvis"}   # vocabulário → prompt do whisper-server

    def feed(self, pcm_f32):
        import base64
        try:
            self.proc.stdin.write(json.dumps(
                {"audio_b64": base64.b64encode(
                    np.asarray(pcm_f32, dtype="<f4").tobytes()).decode(),
                 "ctx": Asr.CTX["v"]}) + "\n")
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
        self._aplay = None   # (18:50) o barge-in mata ESTE processo
        threading.Thread(target=self._worker, daemon=True).start()
    def say(self, text):
        text = text.strip()
        # (16:45) o 4B às vezes EMITE o markup de tool como texto
        # ('<function=shell>...') — isso NUNCA vai pro piper.
        import re as _re
        text = _re.sub(r"<function=[^>]*>.*?(?:</function>|$)", " ", text, flags=_re.S)
        text = _re.sub(r"<parameter=[^>]*>.*?(?:</parameter>|$)", " ", text, flags=_re.S)
        text = _re.sub(r"```[a-z]*\n?", " ", text)
        text = _re.sub(r"\n+", ". ", text).strip()
        if text and len(text) > 1:
            log(f"[{ts()}] tts.say: {text[:60]!r}")
            self.q.put(text)
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
                    tts_self_register(text)   # (07:50) ID da fala em curso
                    aec_register_played(wav)
                    self._aplay = subprocess.Popen(
                        ["aplay", "-q", wav])
                    self._aplay.wait(timeout=90)   # barge-in: .kill() interrompe
                    self._aplay = None
                    tts_self_finish()             # move p/ recent (≤8s)
                    if METACOG_AVAILABLE:
                        _ev = evaluate_response(text)
                        if _ev.get("uncertainty", 0) > UNCERTAINTY_THRESHOLD:
                            log(f"[{ts()}] META pós-fala: incerteza "
                                f"{_ev['uncertainty']:.2f} — {text[:40]!r}")
                        if _ev.get("self_correction_needed"):
                            log(f"[{ts()}] META pós-fala: auto-correção — "
                                f"{_ev.get('reason', '')}")
                else:
                    log(f"[{ts()}] tts FALHOU: synth={okk} wav={Path(wav).exists()}")
                self.last_ms = (time.monotonic() - t0) * 1000
                Path(wav).unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] tts ERRO: {exc}")
            finally:
                self.speaking["until"] = time.monotonic() + 1.0
                global LAST_TTS_END
                LAST_TTS_END = time.monotonic()
                aec_clear()   # (17:50) o AEC SÓ na janela real de play
                self.asr_reset()   # tail do eco: estado limpo pós-fala
                self.asr_reset()   # (12:10) o tail do eco morre AQUI:
                                   # sem o reset o VAD fecha segmento com
                                   # a própria voz e o modelo responde a si
    def close(self):
        pass  # piper por-frase: sem daemon pra matar

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8092)
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
    # (20:30) SEM LoRA: o 35B puro é o cérebro (tools + qualidade); o
    # MicroTurn-LoRA é do protocolo 3-palavras (fase 2: real-duplex feel).
    # O smart merge faz o timing; o 35B responde com o que sabe de melhor.
    log(f"[{ts()}] MODO DUPLEX 4B-MTP. Fala! Ctrl-C = dormir.")

    global HUNSPELL_DICT
    HUNSPELL_DICT = _resolve_dict()
    log(f"[{ts()}] hunspell dict: {HUNSPELL_DICT or 'NENHUM (sem correção)'}")
    # self-mute anti-eco (18/10 ~06h) — dict ÚNICO module-level:
    # in_cooldown() vê o mesmo objeto que o Tts atualiza.
    speaking = SPEAKING
    asr = Asr(args.stt_model, args.lang)
    tts = Tts(speaking)
    tts._asr = asr   # (12:10) o asr_reset pós-fala precisa do pipe do asrd
    mic_q = queue.Queue(maxsize=6)
    threading.Thread(target=mic_reader, args=(mic, mic_q), daemon=True).start()

    history: list[tuple[str, str]] = []
    quiet = 0
    tick_n = 0
    prev_pcm, prev_rms = None, 0
    zeros = 0
    pending = []              # (12:00) merge de segmentos
    merge_deadline = 0.0
    _last_wait_text = [None]  # (23:00) detector de WAIT preso
    _wait_repeats = [0]
    barge_buf = []           # (17:15) DUAL: fala do dono durante o TTS
    running = True
    # (16:00) METACOGNIÇÃO: engine + callbacks (se o módulo importou)
    if METACOG_AVAILABLE:
        metacog = get_metacognition()
        metacog.set_callbacks(
            on_low_confidence=lambda c, t: log(
                f"[{ts()}] META: baixa confiança ({c:.2f}) — {t[:40]!r}"),
            on_self_correction=lambda o, c, r: log(
                f"[{ts()}] META: auto-correção — {o[:30]!r} → {c[:30]!r} ({r})"),
            on_uncertainty=lambda t, u, r: log(
                f"[{ts()}] META: incerteza ({u:.2f}) — {t[:40]!r} ({r})"),
        )
        log(f"[{ts()}] META: metacognição ativa")

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
            # (16:50) ENTRY POINT de teste (dono): fala injetada sem
            # acústica — o kokoro às vezes vira [MÚSICA] pro whisper.
            try:
                p_inj = Path("/tmp/duplex-inject")
                if p_inj.exists():
                    _inj = p_inj.read_text().strip()
                    p_inj.unlink()
                    if _inj:
                        log(f"[{ts()}] INJETADO: {_inj[:50]!r}")
                        pending.append(_inj)
                        merge_deadline = time.monotonic()
            except Exception:
                pass
            # (09:55) MÚSICA/FUNDO → NÃO responde (o dono: "não precisa
            # reagir"). O VAC manda 'no online update, only VAD voice' ou
            # texto curto; segmentos <3 chars (garbage whisper) são descartados.
            if (heard and heard != NOVOICE and
                    (len(heard.replace(" ", "")) < 4
                     or "MÚSICA" in heard.upper()
                     or "MUSIC" in heard.upper())):
                heard = NOVOICE
            # (16:50) ENTRY POINT de teste (dono): fala injetada sem
            # acústica — o kokoro às vezes vira [MÚSICA] pro whisper e
            # a bateria de testes não pode depender dessa loteria.
            try:
                p_inj = Path("/tmp/duplex-inject")
                if p_inj.exists():
                    _inj = p_inj.read_text().strip()
                    p_inj.unlink()
                    if _inj:
                        log(f"[{ts()}] INJETADO: {_inj[:50]!r}")
                        pending.append(_inj)
                        heard = NOVOICE
                        merge_deadline = time.monotonic()
            except Exception:
                pass
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
                # (07:30, dono: "corta a própria fala") BARGE-GATE NO
                # RESÍDUO PÓS-AEC, não no raw: o eco cru do alto-falante
                # media 1100-1750 (matava TTS com threshold 900); o AEC
                # subtrai a referência do playback → resíduo = voz real +
                # erro de cancelamento. Piso ADAPTATIVO: mediana móvel do
                # resíduo durante a fala = nível do eco remanescente;
                # barge só se ACRESCENTA energia SIGNIFICATIVA (×1.6).
                _processed = mp_aec_process(c16)
                rrms = int(np.sqrt((_processed.astype(np.float64) ** 2)
                                   .mean()))
                if tts_playing:
                    # (13:25, e2e HB phase-2: mix sem pausa nunca fecha
                    # segmento) INSTRUMENTAÇÃO p/ diagnosticar o barge:
                    # conta decisões do gate + corr amostral; no fim do
                    # playback, um resumo (sem spam por-chunk).
                    _corr = corr_with_ref(c16)
                    FEED_STATS["corr"].append(_corr)
                    if _corr >= 0.55:
                        FEED_STATS["blocked"] += 1
                    elif rrms >= 350:
                        FEED_STATS["fed"] += 1
                        asr.feed(_processed.astype("float32") / 32768.0)
                    else:
                        FEED_STATS["quiet"] += 1
                else:
                    if FEED_STATS["fed"] or FEED_STATS["blocked"]:
                        cs = sorted(FEED_STATS["corr"])
                        med = cs[len(cs) // 2] if cs else 0.0
                        log(f"[{ts()}] feed-gate: fed={FEED_STATS['fed']} "
                            f"blocked={FEED_STATS['blocked']} quiet="
                            f"{FEED_STATS['quiet']} corr_med={med:.2f}")
                    FEED_STATS.update(fed=0, blocked=0, quiet=0, corr=[])
                    asr.feed(_processed.astype("float32") / 32768.0)
            if barge_buf and not tts_playing and len(barge_buf) >= 2:
                log(f"[{ts()}] BARGE-IN processado: {len(barge_buf)} chunks")
                for bc in barge_buf:
                    asr.feed(bc.astype("float32") / 32768.0)
                barge_buf.clear()
            r = asr.take()
            if isinstance(r, dict) and r.get("text"):
                heard = r["text"]
                # (16:05) vocabulário da conversa → prompt do whisper
                # (paper 2307.14743; o server aceita 'prompt' — o
                # 'Já viz' morre na FONTE agora)
                words = (heard + " " + Asr.CTX["v"]).split()
                # respostas do modelo também entram (vocab esperado)
                seen, keep = set(), []
                for w in words:
                    if w not in seen:
                        seen.add(w); keep.append(w)
                Asr.CTX["v"] = " ".join(keep[:40])
                # (16:30, dono: 'nada a ver com o som da sala') o gate
                # MÚSICA descartava o segmento INTEIRO — com música por
                # baixo, a FALA vinha junto e morria. Agora: extrai as
                # palavras de fora das etiquetas; só descarta se NÃO
                # sobra fala.
                import re as _re
                _clean = _re.sub(r"\[[^\]]*\]", " ", heard).strip()
                if len(_clean.replace(" ", "")) >= 4:
                    if _clean != heard:
                        log(f"[{ts()}] música/fala misturado — fala: {_clean[:40]!r}")
                    heard = _clean
                elif len(heard.replace(" ", "")) < 4:
                    log(f"[{ts()}] ruído — descartado: {heard[:30]!r}")
                    heard = NOVOICE
                else:
                    log(f"[{ts()}] só música — descartado")
                    heard = NOVOICE

                if heard and heard != NOVOICE:
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
                        # (19:00) SMART MERGE (Easy-Turn heuristic):
                        # termina em ? ! = completo → 500ms
                        # termina em , e mas → incompleto → 1.5s
                        # default → 1.2s
                        # (20:50, paper Next-Turn 2606.18094) SEMANTIC
                        # EoT: '?' = pergunta COMPLETA → 200ms (o tempo
                        # de reação humano é 200-600ms; 200 é o alvo
                        # dos sistemas produção); '.' e '!' = 400ms;
                        # conjunção = 1.5s; default 800ms
                        _last = pending[-1].rstrip()
                        if _last.endswith("?"):
                            _wait = 0.2   # pergunta = fogo imediato
                        elif _last.endswith(("!", ".")):
                            _wait = 0.4
                        elif _last.endswith((",", " e", " mas", " ou",
                                                 " que", " pra", " para")):
                            _wait = 1.5
                        else:
                            _wait = 0.8
                        merge_deadline = time.monotonic() + _wait
                        force = False
            elif pending and not force and heard != NOVOICE:
                # mais fala durante a espera? renova (frase contínua)
                merge_deadline = time.monotonic() + 1.2

            tts_on = time.monotonic() < speaking["until"]
            if force and tts_on and is_tts_self(heard):
                # (08:25) eco da própria fala com force = morto (o
                # is_tts_self no merge já descarta; isto é rede de
                # segurança p/ eco que passou raspando com RESPOND).
                # Fala NOVA do dono durante o TTS NÃO é eco → segue:
                # o aplay já foi morto no branch RESPOND/BARGE e a
                # resposta sai (interrupção legítima).
                log(f"[{ts()}] segmento durante própria fala — eco, calado")
                force = False
            # (12:00) MERGE: se há fala pendente e a deadline passou
            # sem mais segmentos = utterância completa → RESPONDE junta.
            if (pending and not force
                    and time.monotonic() >= merge_deadline):
                heard = " ".join(pending)
                pending.clear()
                if in_cooldown():
                    log(f"[{ts()}] cooldown pós-TTS — descartado: {heard[:40]!r}")
                    heard = NOVOICE
                elif is_tts_self(heard):
                    # (07:50, solução do DONO: ID da fala) transcrição
                    # casa com o que EU estou dizendo/ disse agora = eco
                    # da minha própria voz — ignora. Fala NOVA durante o
                    # TTS passa adiante = interrupção real.
                    log(f"[{ts()}] TTS-SELF id-eco — descartado: {heard[:40]!r}")
                    heard = NOVOICE
                elif is_self_echo(heard):
                    log(f"[{ts()}] AUTO-ECO textual — descartado: {heard[:40]!r}")
                    heard = NOVOICE
                n_words = len(heard.split())
                is_cmd = heard.lower().strip(".,!?") in (
                    "pare", "para", "stop", "jarvis", "calaboka", "silêncio",
                    "cala boca", "quieto")
                # (03:35, direção do dono) SINAL SOCIAL entre colchetes
                # ([risadas], [aplausos], [música]): NÃO é pergunta — pula
                # o classificador (economiza 150ms) e não força resposta;
                # mas ENTRA no histórico = contexto social pro LLM reagir.
                # (06:20) 'música' SECA também: o turbo transcreve a
                # ambiência SEM colchetes — mesmo tratamento (é detecção
                # CORRETA de música tocando, não alucinação).
                _heard_clean = heard.lower().strip(" .,!?")
                if (heard.startswith("[") and "]" in heard and n_words <= 4) \
                        or _heard_clean in ("música", "música música"):
                    log(f"[{ts()}] sinal social: {heard[:40]!r} — histórico")
                    # segue pro tick sem force (entra no history embaixo)
                elif _heard_clean in ("obrigado", "obrigada",
                                      "muito obrigado", "muito obrigada",
                                      "valeu", "valeu!", "blz", "ok obrigado",
                                      "thank you", "thanks", "thanks a lot"):
                    # (08:40, dono: "qualquer barulho vira 'obrigado' e
                    # ele fica 'de nada dono'") o turbo TEM esse vício de
                    # transcrição em ruído — obrigado SECO = backchannel:
                    # silêncio educado, zero resposta. Agradecimento com
                    # CONTEÚDO ('obrigado pela ajuda') responde normal.
                    # (09:40) EN: 'Thank you.' ×5 da TV no live-fire —
                    # mesmo vício, mesma cura (defesa p/ gate-off).
                    log(f"[{ts()}] backchannel obrigado — silêncio: {heard[:30]!r}")
                    heard = NOVOICE
                else:
                    # (19/10) CLASSIFICADOR LoRA no lugar das heurísticas:
                    # RESPOND=chat · WAIT=segura · SILENCE=descarta ·
                    # BARGE=mata o TTS. Falha técnica → gate antigo.
                    lab = (classify_turn(base, heard)
                           if (n_words >= 1 and heard != NOVOICE) else None)
                    log(f"[{ts()}] classify({heard[:38]!r}) = {lab}")
                    if lab == "RESPOND":
                        # (09:15) modo-TV: classificador diz RESPOND à
                        # fala COMPLETA da TV/sala — sem endereçamento
                        # não vira resposta. GATE on = exigir Jarvis/
                        # pergunta/comando; off = comportamento antigo.
                        if GATE_MODE == "on" and not _addressed(heard):
                            log(f"[{ts()}] RESPOND não-endereçado (TV/sala) — ignora: {heard[:40]!r}")
                            heard = NOVOICE
                        else:
                            if tts._aplay and tts._aplay.poll() is None:
                                tts._aplay.kill()
                                log(f"[{ts()}] RESPOND-durante-TTS: interrupção — TTS morto")
                            spec_sniff(heard)   # Heartbeat: prepara tool
                            force = True
                    elif lab == "WAIT":
                        spec_sniff(heard)   # Heartbeat: prepara no tempo de WAIT
                        # fala continua: devolve ao pending p/ próxima
                        # janela; deadline RENOVADA — sem isso o merge
                        # refire no mesmo tick e re-classifica em loop.
                        if heard == _last_wait_text[0]:
                            _wait_repeats[0] += 1
                        else:
                            _wait_repeats[0] = 1
                            _last_wait_text[0] = heard
                        if _wait_repeats[0] >= 3:
                            # preso no WAIT 3x = a pessoa terminou e
                            # espera: trata como RESPOND (nunca deixa mudo)
                            log(f"[{ts()}] WAIT preso 3x — força RESPOND")
                            force = True
                        else:
                            pending.append(heard)
                            merge_deadline = time.monotonic() + 1.5
                            heard = NOVOICE
                    elif lab == "SILENCE":
                        heard = NOVOICE
                    elif lab == "BARGE":
                        if tts._aplay and tts._aplay.poll() is None:
                            tts._aplay.kill()
                            log(f"[{ts()}] BARGE semântico: TTS morto")
                        heard = NOVOICE
                    elif n_words < 3 and not is_cmd:
                        log(f"[{ts()}] fragmento curto ({n_words} pal) — ignora: {heard[:30]!r}")
                        heard = NOVOICE
                    elif not is_backchannel(heard):
                        force = True
                log(f"[{ts()}] utterância completa: {heard[:60]!r}")
            said, _p = tick_once(base, history, heard, force_speak=force, tts=tts)
            # (18:20) aprendizado: extrai fatos do turno em background
            if said != LISTEN:
                learn_from_turn(heard, said)
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
            if said == LISTEN:
                quiet += 1
            else:
                quiet = 0
                # (14:00, dono: "agente duplicando respostas") o path
                # force JÁ FALA via stream_chat (frases ao vivo); este
                # acumulador era do micro-turn-per-tick MORTO e re-falava
                # a resposta inteira. Aqui: só bookkeeping.
                print(f"  ouvi: {heard:<28} digo: {said}  (asr {asr.last_ms:.0f}ms)",
                      flush=True)
                LAST_RESPONSES.append(said)
                # (17:30) as palavras da resposta vão pro ctx do whisper
                for w in said.split():
                    if w.lower() not in Asr.CTX["v"].lower() and len(Asr.CTX["v"]) < 180:
                        Asr.CTX["v"] += " " + w
                # (16:00) METACOGNIÇÃO: avalia o que FOI DITO (confiança
                # heurística + incerteza) — alimenta o histórico do engine
                if METACOG_AVAILABLE and said != LISTEN:
                    _ev = evaluate_response(said)
                    _unc, _us, _ur = detect_uncertainty(said)
                    if _unc:
                        log(f"[{ts()}] META: incerteza na fala "
                            f"({_us:.2f}) — {said[:40]!r}")
                    # (16:30) REAÇÃO cognitiva: auto-correção falada
                    # (afirmei fato incerto → retrata) + curiosidade ativa
                    # (não sei o dado pedido → digo que vou buscar, nunca
                    # invento). Soa DEPOIS da resposta, como retratação.
                    _rx = metacog.react(said, heard)
                    if _rx['action'] != 'NONE':
                        log(f"[{ts()}] META reação {_rx['action']}: "
                            f"{_rx['reason']} — {said[:35]!r}")
                        tts.say(_rx['say'])

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
        if METACOG_AVAILABLE:
            try:
                log(f"[{ts()}] META stats: {get_metacognition_stats()}")
            except Exception:
                pass
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
