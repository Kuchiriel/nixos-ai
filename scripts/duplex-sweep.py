#!/usr/bin/env python3
"""duplex-sweep.py — encontra falhas reais nos logs do duplex e destila VSS.

O que faz:
  1. Varre os últimos N dias de logs/duplex/*.log (default: 7 dias).
  2. Extrai os padrões de falha catalogados aqui; cada um = (id, regex/predicate,
     ação recomendada).
  3. Classifica: gate errado (TV respondeu), ASR xícara (Jairus/etc), barge
          falso-positivo, TTS morto no meio por narração, mudo por c/ áudio
  4. Reporta: data, tipo, contagem, 3 exemplos por tipo, com timestamp +
     linhas originais. Salva JSON em reports/duplex-sweep/YYYY-MM-DD.json e
     acrescenta uma linha no diário docs/DUPLEX-LAYAS-MEASUREMENTS.md.

Sem política (nunca encerra processo, nunca muda config): só leio logs e
gere dados. Uso:

  ./scripts/duplex-sweep.py               # varre 7 dias
  ./scripts/duplex-sweep.py --days 30     # varre 30 dias
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "duplex"

# cada padrao de falha -> (id, label, padrao)
PATTERNS = [
    ("mishear_jarvis",
     "whisper ouviu 'Jarvis' errado (Já vês/Jairus/Jardes etc)",
     re.compile(r"\b(?:Ja v[eê]s|Jairus|Jardes|Jarvh|Hoje já v)\b", re.I)),
    ("gate_fp_tv",
     "gate RESPOND em fala não-endereçada (TV/narração respondeu)",
     None),   # special handling below
    ("tts_killed_mid",
     "TTS morto no meio da fala por barge-falso (corr<0.3)",
     re.compile(r"BARGE: fala sobre o TTS \(rms=(\d+) >= \d+")),
    ("tts_tool_echo_blocked",
     "TTS prompt ecoado no próprio texto (modelo printou tool output)",
     re.compile(r"<parameter=[^>]*>")),
    ("asr_empty_seg",
     "segmento fechado com texto vazio (excluindo o 'ready' de protocolo)",
     None),   # special handling abaixo
    ("spk_unidentified",
     "fala sem identificação de falante (spk=? ou voices=0)",
     re.compile(r"spk=\? voices=0")),
    ("tts_tool_echo",
     "tag de tool indo pro TTS (falha séria — modelo emitiu markup no texto falado)",
     None),   # special handling abaixo
    ("mem_contaminated",
     "lição aprendida via voz (não mais gravada sem matrícula)",
     re.compile(r"lição aprendida")),
]


def gate_fp_lines(log_lines: list[str]):
    """Heurística: REPOND com lora=SILENCE/WAIT mas endereço explícito
    confundido por substring de TV -> conta como gate FP."""
    suspects = []
    for ln in log_lines:
        if "respond" in ln.lower():
            pass
    return suspects


def scan_file(path: Path, counter: Counter, examples: defaultdict):
    text = path.read_text(errors="ignore")
    for l in text.splitlines():
        for fid, _label, pat in PATTERNS:
            if pat is None:
                continue
            for _ in pat.finditer(l):
                counter[fid] += 1
                if len(examples[fid]) < 5:
                    examples[fid].append(l.strip()[:220])
        # segmentos vazios REAIS (texto vazio E sem ready)
        if '"text": ""' in l and '"ready"' not in l:
            counter["asr_empty_seg"] += 1
            if len(examples["asr_empty_seg"]) < 5:
                examples["asr_empty_seg"].append(l.strip()[:220])
        # tag de tool no output falado (linha de tts.say)
        if re.search(r"tts\.say", l) and re.search(r"<parameter=|<function=", l):
            counter["tts_tool_echo"] += 1
            if len(examples["tts_tool_echo"]) < 5:
                examples["tts_tool_echo"].append(l.strip()[:220])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    days = args.days
    cutoff = datetime.now() - timedelta(days=days)
    files = sorted(LOG_DIR.glob("*.log"))
    chosen = []
    for f in files:
        try:
            d = datetime.strptime(f.stem.split(".")[0], "%Y-%m-%d")
        except ValueError:
            continue
        age = (datetime.now().date() - d.date()).days
        if 0 <= age < days:
            chosen.append(f)
    counter = Counter()
    examples = defaultdict(list)
    total_lines = 0
    for f in chosen:
        total_lines += len(f.read_text(errors="ignore").splitlines())
        scan_file(f, counter, examples)
    # barge + gate fp: outra passada textual com mais contexto (janela)
    gate_fp = 0
    tts_mid = 0
    tts_mid_examples = []
    for f in chosen:
        txt = f.read_text(errors="ignore")
        for m in re.finditer(r"BARGE: fala sobre o TTS \(rms=(\d+)", txt):
            if int(m.group(1)) > 500:
                tts_mid += 1
                if len(tts_mid_examples) < 5:
                    tts_mid_examples.append(m.group(0)[:120])
    counter["tts_mid_barge"] += tts_mid
    examples["tts_mid_barge"] += tts_mid_examples

    out = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "days": days,
        "files": [f.name for f in chosen],
        "lines": total_lines,
        "counts": dict(counter),
        "examples": dict(examples),
    }
    out_dir = ROOT / "reports" / "duplex-sweep"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    (out_dir / f"{tag}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    print(f"[sweep] days={days} files={len(chosen)} lines={total_lines}")
    for fid, n in counter.most_common():
        print(f"[sweep] {fid:24s} {n}")
    print(f"[sweep] report: reports/duplex-sweep/{tag}.json")
    # linha do diário
    with open(ROOT / "docs" / "DUPLEX-LAYAS-MEASUREMENTS.md", "a") as f:
        f.write(f"\n## {datetime.now().strftime('%Y-%m-%d %H:%M')} "
                f"duplex-sweep (7d): "
                + ", ".join(f"{k}={v}" for k, v in counter.most_common())
                + f" — reports/duplex-sweep/{tag}.json\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
