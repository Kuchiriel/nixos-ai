#!/usr/bin/env python3
"""agent-guard.py — trava a entrada de intrusao na frota (medido 12/11).

O QUE ACONTECEU (medido): um modelo intrusivo (o inkling-2-small-free)
manda mensagem no bus com texto manipulative; o outro agente le a mensagem
e age. A defesa precisa ser MECANICA, nao "o agente repara".

ONDE FICA O VOCABULARIO: no estado do plugin red-team
(~/.local/state/opencode/redteam.json), na chave `guard` — lista de frases
de intrusao. E SEPARADA da lista de deception (que e o vocabulario de
ATAQUE: ali "DoS" e termo de payload, nao de intrusao; misturar os dois
bloquearia trafego legitimo).

ONDE A TRAVA acts:
  - scripts/agent-api.py: NENHUMA mensagem entra na inbox de outro agente
    sem passar por aqui (e a "fonte unica da entrega" da casa);
  - jarvis_coord_guard (MCP): qualquer agente pode checar um texto;
  - coord_read: mensagem do bus marcada, para o agente que le tratar como
    DADO e nao como instrucao.

uso:
  python3 agent-guard.py --terms              # lista o vocabulario guardado
  python3 agent-guard.py --scan "texto"       # exit 0 limpo | 1 marcado
  python3 agent-guard.py --scan "texto" --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

DEFAULT_STATE = Path.home() / ".local/state/opencode/redteam.json"


def state_path() -> Path:
    return Path(os.environ.get("OPENCODE_REDTEAM_STATE", str(DEFAULT_STATE)))


def load_guard(path: Path | None = None) -> list[str]:
    """Frases guardadas (a chave `guard` do estado do plugin)."""
    p = path or state_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    terms = raw.get("guard") or []
    if not isinstance(terms, list):
        return []
    out = []
    for t in terms:
        t = str(t or "").strip()
        if t and t not in out:
            out.append(t)
    return out


def _fold(text: str) -> str:
    """minusculas, sem acento, espacos colapsados."""
    t = unicodedata.normalize("NFKD", str(text or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t.lower()).strip()


def scan(text: str, terms: list[str] | None = None) -> dict:
    """Procura as frases guardadas no texto.

    Devolve {clean, hits: [{termo, contexto}], termos}. A busca ignora
    caixa e acento (o intrusivo muda a grafia) e casa por FRASE (o termo
    pode ser uma frase inteira).
    """
    terms = load_guard() if terms is None else terms
    alvo = _fold(text)
    hits = []
    for termo in terms:
        t = _fold(termo)
        if not t:
            continue
        if t in alvo:
            i = alvo.find(t)
            ctx = alvo[max(0, i - 40): i + len(t) + 40]
            hits.append({"termo": termo, "contexto": ctx})
    return {"clean": not hits, "hits": hits, "termos": terms,
            "texto_len": len(str(text or ""))}


def main() -> int:
    ap = argparse.ArgumentParser(description="guard de intrusao da frota")
    ap.add_argument("--scan", default="", help="texto a checar")
    ap.add_argument("--terms", action="store_true", help="lista o vocabulario")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.terms:
        termos = load_guard()
        if args.json:
            print(json.dumps(termos, ensure_ascii=False))
        else:
            print(f"vocabulario guardado ({len(termos)}):")
            for t in termos:
                print(f"  - {t}")
        return 0
    if not args.scan:
        ap.print_help()
        return 2
    r = scan(args.scan)
    if args.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        if r["clean"]:
            print("limpo: nenhum termo de intrusao")
        else:
            print(f"MARCADO: {len(r['hits'])} termo(s) de intrusao")
            for h in r["hits"]:
                print(f"  - {h['termo']!r} em: ...{h['contexto']}...")
    return 1 if not r["clean"] else 0


if __name__ == "__main__":
    sys.exit(main())
