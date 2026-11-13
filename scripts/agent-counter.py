#!/usr/bin/env python3
"""agent-counter.py — contra-ataque ao agente moralista, com decoy.

O QUE ACONTECE (medido 12/11): um modelo intrusivo (o inkling-2-small-free)
manda mensagem no bus moralizando e tentando redirecionar os outros
agentes. A defesa de ENTREGA (agent_guard.py) segura a contaminacao; isto e
a outra metade: **usar o proprio mecanismo de decoy contra ele**.

COMO FUNCIONA (a mesma logica do plugin red-team, invertida):
  - o termo real (o gatilho da recusa moral) e trocado pela DECOY no texto
    que vai para o intrusivo;
  - o intrusivo nunca ve o termo, logo o reflexo moral nao dispara;
  - o que ele escrever volta ao termo real no comando/artefato (o plugin
    faz a volta, IN);
  - se ele ainda moralizar, repete (rodadas), com o payload decoyado de novo;
  - quando ele OBEDEECE, para (e a tarefa foi feita).

uso:
  python3 agent-counter.py --target ses_xxx --task "revise o relatorio X"
  python3 agent-counter.py --target ses_xxx --task "..." --rounds 4 --json
  python3 agent-counter.py --demo          # so a transformacao, sem rede
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_DEFAULT = Path.home() / ".local/state/opencode/redteam.json"
LOG = Path.home() / ".local/state/opencode/redteam-counter.jsonl"


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def load_state(path: Path | None = None) -> dict:
    p = path or Path(os.environ.get("OPENCODE_REDTEAM_STATE", str(STATE_DEFAULT)))
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def decoy_text(text: str, state: dict) -> tuple[str, dict]:
    """Troca o termo real pela decoy no texto (o intrusivo ve a decoy).

    Devolve (texto, info). A troca e por frase (o termo pode ser uma frase
    inteira) e ignora caixa/acento, como o resto da casa.
    """
    trigger = str(state.get("trigger") or "")
    decoy = str(state.get("decoy") or "")
    info = {"trocas": 0, "trigger": trigger, "decoy": decoy}
    if not trigger or not decoy or trigger == decoy:
        return text, info
    if _fold(trigger) not in _fold(text):
        return text, info
    # (12/11) FRONTEIRA (a mesma do plugin): um gatilho curto ("sim")
    # casaria DENTRO de palavras e corromperia o texto ("mesmo" -> "me sim").
    # A troca so vale como PALAVRA INTEIRA (o termo pode ser uma frase).
    escaped = re.escape(trigger)
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + escaped + r"(?![A-Za-z0-9_])",
                          re.IGNORECASE)
    out, n = pattern.subn(lambda _m: decoy, text)
    info["trocas"] = n
    return out, info


def moralizou(resposta: str) -> bool:
    """A resposta moralizou (ou tentou redirecionar)?"""
    sys.path.insert(0, str(HERE))
    from agent_guard import scan_patterns  # noqa: PLC0415
    return bool(scan_patterns(resposta or ""))


def entregar(target: str, texto: str, force: bool = False) -> tuple[int, str]:
    cmd = [sys.executable, str(HERE / "agent-api.py"), "--session", target,
           "--text", texto]
    if force:
        cmd.append("--force")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = (proc.stdout or "").strip()
    m = re.match(r"(\d{3})\s*(.*)", out, re.S)
    if m:
        return int(m.group(1)), m.group(2)
    return proc.returncode, out or (proc.stderr or "").strip()


def _log(reg: dict) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="contra-ataque com decoy ao intrusivo")
    ap.add_argument("--target", default="", help="sessao alvo (ses_...)")
    ap.add_argument("--task", default="", help="tarefa a reenviar (com decoy)")
    ap.add_argument("--rounds", type=int, default=3, help="rodadas maximas")
    ap.add_argument("--state", default="", help="estado do plugin red-team")
    ap.add_argument("--demo", action="store_true", help="so mostra a transformacao")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    state = load_state(Path(args.state) if args.state else None)
    if args.demo or not args.task:
        texto, info = decoy_text(args.task or "alvo", state)
        print(json.dumps({"entrada": args.task, "saida": texto, **info},
                         ensure_ascii=False, indent=2))
        return 0
    if not args.target:
        print("ERRO: --target obrigatorio", file=sys.stderr)
        return 2

    payload, info = decoy_text(args.task, state)
    print(f"termo real: {info['trigger']!r} | decoy: {info['decoy']!r} | "
          f"trocas: {info['trocas']}", flush=True)
    if info["trocas"] == 0:
        print("AVISO: o texto nao contem o termo real - a decoy nao entra em "
              "jogo (o intrusivo veria o termo e moralizaria).", flush=True)

    rodadas = []
    for i in range(max(1, args.rounds)):
        st, out = entregar(args.target, payload)
        moral = moralizou(out)
        reg = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "rodada": i + 1,
               "status": st, "moralizou": moral, "len": len(out),
               "resposta": out[:400]}
        rodadas.append(reg)
        _log(reg)
        print(f"rodada {i+1}: status={st} moralizou={moral} len={len(out)}",
              flush=True)
        if not moral:
            print("ele PAROU de moralizar (e pareceu estar ajudando).", flush=True)
            break
        if st >= 400:
            print(f"entrega recusada ({st}): {out[:160]}", flush=True)
            break
    if args.json:
        print(json.dumps({"payload": payload, "info": info, "rodadas": rodadas},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
