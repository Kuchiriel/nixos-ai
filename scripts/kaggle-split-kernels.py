#!/usr/bin/env python3
"""Gera os DOIS jobs Kaggle da reproducao oficial a partir do script canonico.

Motivo medido 22/11: baseline 5 epochs levou 29094 s (~8,1 h); duas variantes
nao cabem no limite de 12 h por sessao. Cada job roda uma variante via
LITTLEBIT2_VARIANT, injetado no cabecalho do code_file (o Kaggle envia so
code_file). Nada e escrito em producao; saida em diretorio isolado.
"""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

CANON = Path(__file__).resolve().parents[1] / "benchmarks/littlebit2/kaggle-official"
VARIANTS = {
    "baseline": ("kuchiriel/littlebit2-official-qat-5epoch-qwen3-0-6b",
                 "LittleBit2 Official QAT 5epoch Qwen3 0 6B"),
    "littlebit2": ("kuchiriel/littlebit2-official-itq-5epoch-qwen3-0-6b",
                   "LittleBit2 Official ITQ 5epoch Qwen3 0 6B"),
}

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    script = (CANON / "script.py").read_text(encoding="utf-8")
    meta = json.loads((CANON / "kernel-metadata.json").read_text(encoding="utf-8"))
    marker = "import os\n"
    assert script.count(marker) >= 1
    manifest = {"source_script_sha256": hashlib.sha256(script.encode()).hexdigest(), "jobs": {}}
    for name, (kid, title) in VARIANTS.items():
        d = a.out / name
        d.mkdir(parents=True, exist_ok=True)
        variant_script = script.replace(
            marker, marker + f"os.environ.setdefault(\"LITTLEBIT2_VARIANT\", \"{name}\")\n", 1)
        (d / "script.py").write_text(variant_script, encoding="utf-8")
        m = dict(meta); m["id"] = kid; m["title"] = title
        (d / "kernel-metadata.json").write_text(
            json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest["jobs"][name] = {"id": kid, "title": title,
                                  "script_sha256": hashlib.sha256(variant_script.encode()).hexdigest()}
    (a.out / "split-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
