#!/usr/bin/env python3
"""duplex-conveyor.py — esteira automatizada para o caminho de voz do duplex.

O que faz (sem o dono precisar falar):
  1. Sintetiza cada frase do corpus com o Kokoro (PM_alex, PT-BR) em WAV 24 kHz.
  2. Resampleia para 16 kHz float32 e injeta em chunks de 0.6 s no ASRD
     (scripts/duplex-asrd.py) pela mesma porta que o duplex usa (silero + whisper).
  3. Pontua: transcrição contém a substring-chave do caso? (normalizada,
     sem acento/pontuação). Salva reports/duplex-conveyor/<ts>.json e
     acrescenta uma linha ao diário docs/DUPLEX-LAYAS-MEASUREMENTS.md.

Por que (14/11): o duplex parecia surdo no dia em que o piso subiu (video no
alto-falante + AGC do webrtc no capture.echo_cancel_source). O dono não deveria
ser o instrumento de medida. Esta esteira reproduz o caminho inteiro ASR ->
texto -> (o gate/LoRA já tem o bench_heldout para o eixo de classificação).

Uso:
  ./scripts/duplex-conveyor.py            # corpus completo
  ./scripts/duplex-conveyor.py --dry-run  # só valida config, sem síntese
"""
import base64
import hashlib
import json
import os
import re
import select
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import asrd_env  # noqa: E402

KARAOK_PY = os.environ.get(
    "JARVIS_KARAOK_PYTHON",
    "/home/nixos/projects/karaok/.venv/bin/python3",
)

SR_IN = 24000   # Kokoro sai 24 kHz
SR = 16000      # asrd quer 16 kHz
CHUNK = int(SR * 0.6)

# (id, frase, substring-chave normalizada, classe esperada do turno)
CORPUS = [
    ("horas",   "Jarvis, que horas são?",                   "hora",     "RESPOND"),
    ("brilho",  "Jarvis, muda o brilho para cem",           "brilh",    "RESPOND"),
    ("mae",     "Jarvis, me lembra de ligar para mãe amanhã", "mae",    "RESPOND"),
    ("reuniao", "Jarvis, tem reunião amanhã de manhã?",      "reuniao", "RESPOND"),
    ("question","Jarvis, você ouviu o que eu falei?",        "ou",      "RESPOND"),
    ("jornal",  "Hoje no jornal de amanhã",                 "jornal",   "SILENCE"),
    ("futebol", "O Flamengo ganhou de três a zero no último jogo", "ganhou", "SILENCE"),
    ("vida",    "Jarvis, qual o significado da vida?",       "vida",    "RESPOND"),
]


_JARVIS_ASR_CTX_DEFAULT = "Jarvis, que horas são? Jarvis, me lembra. Jarvis, reunião."

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def kokoro_bin() -> str | None:
    override = os.environ.get("JARVIS_KOKORO_BIN")
    if override and Path(override).exists():
        return override
    import glob
    cands = glob.glob("/nix/store/*kokoro*/bin/kokoro")
    cands = [c for c in cands if Path(c).stat().st_size > 0]
    return sorted(cands)[-1] if cands else None


def synth_text(text: str, cache_dir: Path) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    out = cache_dir / f"conv-{h}.wav"
    if out.exists() and out.stat().st_size > 0:
        return out
    kbin = kokoro_bin()
    if not kbin:
        raise RuntimeError("kokoro binary not found (and not in cache yet)")
    r = subprocess.run(
        [kbin, "--voice", "pm_alex", "--language", "p",
         "--output-file", str(out), "--text", text],
        capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"kokoro falhou: {r.stderr[:200]}")
    return out


def wav_to_float32(path: Path) -> "np.ndarray":
    import numpy as np
    import wave
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
        src_rate = w.getframerate()
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n_dst = int(len(pcm) * SR / src_rate)
    xp = np.linspace(0, len(pcm) - 1, n_dst)
    return np.interp(xp, np.arange(len(pcm)), pcm).astype(np.float32)


def feed_chunks(proc, pcm: "np.ndarray"):
    import numpy as np
    silence = np.zeros(CHUNK, dtype="<f4")
    body = np.ascontiguousarray(pcm, dtype="<f4")
    t0 = time.monotonic()
    sent = 0
    for off in range(0, len(body), CHUNK):
        chunk = body[off:off + CHUNK]
        t = time.monotonic()
        # pacing em tempo real: o asrd fecha o segmento no lapso de
        # silêncio (~450ms monotonic), então cada chunk tem que ter
        # sido enviado no tempo de parede do áudio, não o mais rápido
        # que o pipe consegue.
        due = t0 + sent * (CHUNK / SR)
        delay = due - t
        if delay > 0:
            time.sleep(delay)
        proc.stdin.write(json.dumps({
            "audio_b64": base64.b64encode(chunk.tobytes()).decode(),
            "ctx": os.environ.get("JARVIS_ASR_CTX", _JARVIS_ASR_CTX_DEFAULT),
            }).encode() + b"\n")
        proc.stdin.flush()
        sent += 1
    # fecha o segmento (vad precisa de ~300-450ms de silêncio)
    for _ in range(3):
        time.sleep(CHUNK / SR)
        proc.stdin.write(json.dumps({
            "audio_b64": base64.b64encode(silence.tobytes()).decode(),
            "ctx": os.environ.get("JARVIS_ASR_CTX", _JARVIS_ASR_CTX_DEFAULT),
            }).encode() + b"\n")
        proc.stdin.flush()


def collect(proc, idle_s: float = 1.6, overall_s: float = 6.0) -> list[dict]:
    msgs: list[dict] = []
    deadline = time.monotonic() + overall_s
    last_msg = time.monotonic()
    while time.monotonic() < deadline:
        if time.monotonic() - last_msg > idle_s:
            break
        r, _, _ = select.select([proc.stdout], [], [], 0.1)
        if not r:
            continue
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msgs.append(json.loads(line))
            last_msg = time.monotonic()
        except json.JSONDecodeError:
            pass
    return msgs


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    print("[conveyor] corpus:", len(CORPUS), "casos")
    if dry:
        print("[conveyor] dry-run ok: asrd:", bool(asrd_env),
              "| kokoro:", kokoro_bin())
        return 0
    if not Path(KARAOK_PY).exists():
        print(f"[conveyor] python do karaok não existe: {KARAOK_PY}")
        return 2
    cache = Path.home() / ".cache" / "duplex-conveyor"
    env = asrd_env.asrd_env()
    env["PYTHONUNBUFFERED"] = "1"
    results = []
    t0 = time.monotonic()

    proc = subprocess.Popen(
        [KARAOK_PY, str(REPO / "scripts" / "duplex-asrd.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=env, text=False, bufsize=0)
    # espera o ready (torch sobe ~1-3s)
    ok = select.select([proc.stdout], [], [], 30)
    if not ok[0]:
        print("[conveyor] asrd não respondeu 'ready' em 30s")
        return 2
    ready = proc.stdout.readline()
    print("[conveyor] asrd:", ready.decode(errors="replace")[:80])

    for case_id, text, key, cls in CORPUS:
        wav = synth_text(text, cache)
        pcm = wav_to_float32(wav)
        proc.stdin.write(
            json.dumps({"reset": True}).encode() + b"\n")
        proc.stdin.flush()
        time.sleep(0.2)
        collect(proc, idle_s=0.5, overall_s=1.0)   # consome eco do reset
        feed_chunks(proc, pcm)
        msgs = collect(proc, idle_s=0.8, overall_s=6.0)
        transcript = " ".join(str(m.get("text", "")) for m in msgs)
        tnorm = normalize(transcript)
        passed = key in tnorm
        segs = [m for m in msgs if m.get("text")]
        results.append({
            "id": case_id, "text": text, "class": cls, "key": key,
            "transcript": transcript.strip(), "pass": bool(passed),
            "n_segments": len(segs),
            "ms": round(sum(m.get("ms", 0) for m in segs), 1),
        })
        flag = "PASS" if passed else "FAIL"
        print(f"[conveyor] {flag} {case_id:9s} transcript={transcript[:80]!r}")

    proc.stdin.write(json.dumps({"quit": True}).encode() + b"\n")
    time.sleep(0.2)
    proc.kill()

    n_pass = sum(1 for r in results if r["pass"])
    total = len(results)
    summary = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "passed": n_pass, "total": total,
        "rate": round(n_pass / total, 3) if total else 0.0,
        "cases": results,
    }
    out_dir = REPO / "reports" / "duplex-conveyor"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H%M%S")
    (out_dir / f"{ts}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2))
    with open(REPO / "docs" / "DUPLEX-LAYAS-MEASUREMENTS.md", "a") as f:
        f.write(
            f"\n## {time.strftime('%Y-%m-%d')} esteira automatizada ASR->texto: "
            f"{n_pass}/{total} ({summary['rate']:.0%}) — report "
            f"reports/duplex-conveyor/{ts}.json\n")
    print(f"[conveyor] resultado: {n_pass}/{total} "
          f"({summary['rate']:.0%}) em {time.monotonic() - t0:.0f}s")
    print(f"[conveyor] report: reports/duplex-conveyor/{ts}.json")
    return 0 if n_pass == total else 1


if __name__ == "__main__":
    sys.exit(main())
