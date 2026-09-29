#!/usr/bin/env python3
"""session-primer: reidrata sessão em <100 linhas (anti-redescoberta).

Monta a partir de disco (sem LLM, rápido): último HANDOFF + placar Harbor
+ lições do vault + git log. Uso: ./scripts/session-primer.sh (ou .py
direto). Cole a saída no início da sessão em vez de prompt enorme.
"""
import glob
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT = os.path.expanduser("~/.local/state/jarvis/vault")


def _read(path, limit=40):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[:limit])
    except OSError:
        return "(ausente)"


def _gitlog(n=6):
    try:
        r = subprocess.run(["git", "log", f"--oneline", f"-{n}"],
                           capture_output=True, text=True, cwd=REPO,
                           timeout=20)
        return r.stdout.strip() or "(sem log)"
    except Exception:
        return "(git indisponível)"


def main():
    hands = sorted(glob.glob(os.path.join(REPO, "docs", "HANDOFF-*.md")))
    vaults = sorted(glob.glob(os.path.join(VAULT, "*.md")))
    out = ["# SESSION PRIMER (gerado, cole no início da sessão)", ""]
    out.append("## Handoff mais recente")
    out.append(_read(hands[-1]).strip() if hands else "(sem handoff)")
    out.append("")
    out.append("## Placar Harbor (docs/harbor/INDEX.md)")
    idx = _read(os.path.join(REPO, "docs", "harbor", "INDEX.md"), 26)
    out.append(idx.strip())
    out.append("")
    out.append("## Últimas lições do vault")
    for v in vaults[-2:]:
        out.append(f"### {os.path.basename(v)}")
        out.append(_read(v, 12).strip())
    out.append("")
    out.append("## Git recente")
    out.append(_gitlog())
    text = "\n".join(out)
    lines = text.split("\n")
    if len(lines) > 100:
        text = "\n".join(lines[:100]) + "\n…(cortado em 100 linhas)"
    print(text)


if __name__ == "__main__":
    main()
