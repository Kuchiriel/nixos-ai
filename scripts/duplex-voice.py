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
    "- Respostas DIRETAS, sem preenchimentos ('Ah,', 'Hmm'): backchannels "
    "só têm sentido ENQUANTO o outro fala (fase duplex); em resposta = "
    "vício.\n"
    "- Se o segmento for ruído/sem sentido, responda só 'Pode repetir?'"
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

def tick_once(base, history, heard, force_speak=False):
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
        msgs = [{"role": "system", "content": SYSTEM_PT}]
        for role, content in history[-12:]:
            if content and content != LISTEN:
                msgs.append({"role": "user" if role == "user" else "assistant",
                             "content": content})
        msgs.append({"role": "user", "content": heard})
        # (10:50) TOOL CALLING nativo do 4B (provado: get_time chamado de
        # primeira). Até 2 rounds: chamada → executa → resultado → resposta.
        body = {"messages": msgs, "max_tokens": 120, "temperature": 0.4,
                "tools": TOOLS_SCHEMA}
        for _round in range(2):
            j = http(base + "/v1/chat/completions", body)
            msg = (j.get("choices") or [{}])[0].get("message", {})
            tcs = msg.get("tool_calls") or []
            if not tcs:
                out = str(msg.get("content", "")).strip()
                log(f"[{ts()}] chat resposta: {out[:80]!r}")
                return (out or "Pode repetir?"), 0.0
            # executa e devolve
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
                             "content": str(result)[:400]})
        out = str(msg.get("content", "")).strip() or "Pronto."
        return out, 0.0
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

def call_tool(name, args):
    """Executa a ferramenta que o 4B pediu e retorna o resultado."""
    if name == "get_time":
        return _exec("date '+%H:%M de %d/%m/%Y'")
    if name == "get_date":
        return _exec("date '+hoje é %A, %d de %B de %Y' | sed 's/^[a-z]*/&/' 2>/dev/null || date")
    if name == "recall":
        q = args.get("query", "")
        return _exec(f"timeout 20 jarvis recall '{q}' 2>&1 | head -20")
    if name == "rag_search":
        q = args.get("query", "")
        return _exec(f"timeout 20 jarvis rag search '{q}' 2>&1 | head -20")
    if name == "status":
        return _exec("systemctl --user is-active jarvis-wakeword 2>&1; uptime -p; free -g | grep Mem")
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
    {"type": "function", "function": {"name": "shell",
     "description": "Executa um comando do sistema e retorna a saída (bloqueia comandos perigosos)",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
]

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
            self.speaking["until"] = max(self.speaking["until"],
                                         time.monotonic() + 1.5)
            self.q.put(text.strip())
    def _worker(self):
        import tempfile
        while True:
            text = self.q.get()
            t0 = time.monotonic()
            self.LOCK.touch()
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
                r = subprocess.run(
                    ["/home/nixos/models/piper/bin/piper", "-m", self.VOICE,
                     "--output_file", wav],
                    input=text + "\n", capture_output=True, text=True,
                    encoding="utf-8", timeout=60)
                if r.returncode == 0 and Path(wav).exists():
                    subprocess.run(["aplay", "-q", wav], timeout=60)
                else:
                    log(f"[{ts()}] tts FALHOU: rc={r.returncode} "
                        f"stderr={(r.stderr or '')[-120:]!r}")
                self.last_ms = (time.monotonic() - t0) * 1000
                Path(wav).unlink(missing_ok=True)
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] tts ERRO: {exc}")
            finally:
                self.LOCK.unlink(missing_ok=True)
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

    speaking = {"until": 0.0}   # self-mute anti-eco (18/10 ~06h)
    asr = Asr(args.stt_model, args.lang)
    tts = Tts(speaking)
    mic_q = queue.Queue(maxsize=6)
    threading.Thread(target=mic_reader, args=(mic, mic_q), daemon=True).start()

    history: list[tuple[str, str]] = []
    frase: list[str] = []
    quiet = 0
    tick_n = 0
    prev_pcm, prev_rms = None, 0
    zeros = 0
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
            tts_playing = (Path("/tmp/jarvis-tts-playing.lock").exists()
                           or time.monotonic() < speaking["until"])
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
                    # segmento COMPLETO chegou = pausa do usuário → o
                    # modelo RESPONDE (ban do <listen>).
                    force = True
                    print(f"  SEGMENTO: {heard}", flush=True)

            tts_on = (Path("/tmp/jarvis-tts-playing.lock").exists()
                      or time.monotonic() < speaking["until"])
            if force and tts_on:
                # (10:25, pesquisa) falando = não decide: eco/segmento
                # fantasma do próprio tail NÃO gera resposta.
                log(f"[{ts()}] segmento durante própria fala — eco, calado")
                force = False
            said, _p = tick_once(base, history, heard, force_speak=force)
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
