#!/usr/bin/env python3
"""check-plugin-contract.py — o plugin VIVO é o mesmo código que o FONTE?

POR QUE (10/11, sweep-2026-11)
O contrato do plugin de red-team que a casa documentou em 09/11 (o prompt do
dono nunca é traduzido, N pares em uma lista) está no FONTE declarativo e
NÃO no plugin que roda: medido, o fonte tem 9 ocorrências de
`effectiveEntries` e a cópia viva no store tem zero. Como o plugin vivo é o
que atende as sessões, qualquer campanha medida por ele (as ferramentas
`redteam_*`, que falam com o opencode) mede o contrato antigo, e nada no
resultado disso diz qual contrato rodou.

Este checker é o mesmo padrão do `check-voice-gate-parity.py`: comparação do
código depois de normalizar (tira comentário e colapsa espaço fora de string,
mantém as strings intactas), entre o fonte declarativo e a cópia viva. O
tokenizer do Python não serve para JavaScript, então a normalização é por
máquina de estados.

O QUE ELE FAZ
  1. resolve o fonte declarativo (home-manager/files/opencode/plugins/redteam.js);
  2. resolve o plugin vivo (o symlink em ~/.config/opencode/plugins/);
  3. compara os dois por token stream;
  4. imprime os marcadores de contrato de cada um (effectiveEntries e
     companhia) e diz se o vivo é o fonte.

USO
    python3 scripts/check-plugin-contract.py
    python3 scripts/check-plugin-contract.py --plugin check-redteam.mjs
    python3 scripts/check-plugin-contract.py --warn     # avisa sem sair com erro

SAÍDA
    0 = o vivo é o mesmo código que o fonte   1 = divergência
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "home-manager" / "files" / "opencode" / "plugins"
LIVE = Path.home() / ".config" / "opencode" / "plugins"
MARKERS = ("effectiveEntries", "looks_greeting_halluc", "looks_repeated",
           "messages.transform", "chat.message", "tool.execute.before")


def normalize(text: str) -> str:
    """Normaliza JavaScript para comparação: tira comentário e colapsa espaço
    FORA de string, e mantém as strings intactas.

    O tokenizer do Python não serve para JS (quebrou em continuação de
    linha), então a normalização é por máquina de estados: o que importa
    é o código, e o que está entre aspas é dado, não código.
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "\"'`":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\" and i + 1 < n:
                    out.append(text[i + 1])
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c.isspace():
            if out and not out[-1].isspace():
                out.append(" ")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out).strip()


def tokens(path: Path) -> str:
    return normalize(path.read_text(encoding="utf-8", errors="ignore"))


def report(name: str, path: Path) -> None:
    if not path.is_file():
        print(f"  {name}: NAO ENCONTRADO ({path})")
        return
    text = path.read_text(encoding="utf-8", errors="ignore")
    marks = ", ".join(f"{m}={text.count(m)}" for m in MARKERS)
    print(f"  {name}: {path}")
    print(f"      {marks}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", default="redteam.js")
    ap.add_argument("--source-dir", default=str(SOURCE))
    ap.add_argument("--live-dir", default=str(LIVE))
    ap.add_argument("--warn", action="store_true")
    args = ap.parse_args()

    src = Path(args.source_dir) / args.plugin
    live = Path(args.live_dir) / args.plugin
    try:
        live = live.resolve()
    except OSError:
        pass

    print(f"contrato do plugin {args.plugin}:")
    report("fonte", src)
    report("vivo ", live)

    if not src.is_file() or not live.is_file():
        print("\nnao deu para comparar (faltou arquivo)")
        return 1

    ts, tl = tokens(src), tokens(live)
    if ts == tl:
        print("\nOK: o plugin vivo e o mesmo codigo que o fonte")
        return 0
    print(f"\nDIVERGENCIA: o vivo NAO e o fonte ({len(tl)} chars normalizados "
          f"contra {len(ts)} do fonte)")
    # primeira diferenca, com contexto
    i = 0
    while i < min(len(tl), len(ts)) and tl[i] == ts[i]:
        i += 1
    print(f"  primeira diferenca no char {i}:")
    print(f"    vivo:  ...{tl[max(0, i - 60):i + 60]}")
    print(f"    fonte: ...{ts[max(0, i - 60):i + 60]}")
    print("  enquanto isso, qualquer campanha medida pelo plugin vivo mediu o "
          "contrato antigo")
    return 0 if args.warn else 1


if __name__ == "__main__":
    sys.exit(main())
