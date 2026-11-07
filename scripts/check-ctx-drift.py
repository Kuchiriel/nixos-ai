#!/usr/bin/env python3
"""Confere o contexto do registry contra o contexto REAL dos GGUFs.

Fontes de verdade:
  - `modules/ai/models.nix` -> `ctxSize` (o que o llama-server recebe) e
    `opencode.context` (o que o opencode publica). Sao ESCOLHAS de
    operacao (o 4B-MTP roda em 12288 por causa da VRAM, por exemplo).
  - o proprio arquivo GGUF -> `*.context_length` = o limite TREINADO do
    modelo. NINGUEM pode prometer mais que isso.

Regra: ctxSize e opencode.context DEVEM ser <= o ctx treinado do GGUF.
Acima disso = bug (o server foi启动 com um ctx que o modelo nao tem).
Abaixo = escolha legitima (e mostra a folga que existe).

Uso:
  scripts/check-ctx-drift.py            # tabela + exit != 0 se violar
  scripts/check-ctx-drift.py --quiet    # so o exit code
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_NIX = ROOT / "modules" / "ai" / "models.nix"
CTX_TOOL = ROOT / "scripts" / "gguf-ctx.py"


def gguf_ctx_map():
    out = subprocess.run([sys.executable, str(CTX_TOOL), "--json"],
                         capture_output=True, text=True, check=True).stdout
    import json
    data = json.loads(out)
    return {o["path"]: o for o in data if "error" not in o}


def parse_models_nix():
    """Extrai (modelFile, ctxSize, opencode_context, opencode_key)."""
    txt = MODELS_NIX.read_text()
    rows = []
    # blocos: "<name> = { ... };" no nivel do routing.models
    for m in re.finditer(r"(\w[\w-]*)\s*=\s*\{", txt):
        name = m.group(1)
        start = m.end()
        depth = 1
        i = start
        while i < len(txt) and depth:
            if txt[i] == "{":
                depth += 1
            elif txt[i] == "}":
                depth -= 1
            i += 1
        block = txt[start:i]
        mf = re.search(r'modelFile\s*=\s*"([^"]+)"', block)
        if not mf:
            continue
        cs = re.search(r"ctxSize\s*=\s*(\d+)", block)
        oc = re.search(r"opencode\s*=\s*\{[^}]*?context\s*=\s*(\d+)", block)
        ok = re.search(r"opencode\s*=\s*\{[^}]*?key\s*=\s*\"([^\"]+)\"", block)
        rows.append({
            "name": name,
            "file": mf.group(1),
            "ctxSize": int(cs.group(1)) if cs else None,
            "oc_ctx": int(oc.group(1)) if oc else None,
            "oc_key": ok.group(1) if ok else None,
        })
    return rows


def main():
    quiet = "--quiet" in sys.argv
    gg = gguf_ctx_map()
    rows = parse_models_nix()
    bad = []
    if not quiet:
        print(f"{'model':<22} {'ctxSize':>8} {'oc_ctx':>8} {'gguf':>8}  arquivo")
    for r in rows:
        g = gg.get(r["file"])
        trained = g["trained_context"] if g else None
        if not trained:
            continue
        flag = ""
        for label, val in (("ctxSize", r["ctxSize"]),
                           ("oc_ctx", r["oc_ctx"])):
            if val and val > trained:
                flag += f" !!{label}>{trained}"
                bad.append((r["name"], label, val, trained, r["file"]))
        if not quiet:
            print(f"{r['name']:<22} {str(r['ctxSize']):>8} "
                  f"{str(r['oc_ctx']):>8} {trained:>8}  "
                  f"{Path(r['file']).name}{flag}")
    if bad:
        print("\nVIOLACOES (promete mais que o modelo suporta):")
        for name, label, val, trained, f in bad:
            print(f"  {name}: {label}={val} > gguf {trained} ({f})")
        return 1
    if not quiet:
        print("\nOK: todo ctx do registry <= contexto treinado do GGUF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
