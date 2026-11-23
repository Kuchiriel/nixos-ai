#!/usr/bin/env python3
"""Agrega os outputs dos DOIS jobs Kaggle do LittleBit-2 oficial.

Cada sessao Kaggle roda uma variante (limite 12h). Este script COPIA
(nunca move/apaga) os diretorios baseline/ e littlebit2/ e os results.json
para um unico diretorio, que e entao passado ao littlebit2-validate.
Somente leitura nas fontes; manifesto com hashes escrito no destino.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

VARIANTS = ("baseline", "littlebit2")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def aggregate(sources: list[Path], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    merged = {"schema": 1, "production_writes": False,
              "official_commit": "42d658b0c79f76450b34b6a3547462c7cdc3e1a0",
              "hardware": {}, "dataset": {}, "variants": {}}
    manifest: dict = {"sources": [], "copied": {}}
    for src in sources:
        root = src / "official-output"
        data = json.loads((root / "results.json").read_text(encoding="utf-8")) if (root / "results.json").is_file() else {}
        manifest["sources"].append({"dir": str(src), "results_sha256": sha(root / "results.json"),
                                    "variants_in_source": sorted(data.get("variants", {}))})
        for key in ("official_commit", "hardware", "dataset"):
            if data.get(key) and not merged.get(key):
                merged[key] = data[key]
        merged["production_writes"] = bool(data.get("production_writes", merged["production_writes"]))
        for name, row in (data.get("variants") or {}).items():
            merged["variants"][name] = row
        pm = root / "protocol-measurement.json"
        if pm.is_file() and not (out / "protocol-measurement.json").exists():
            shutil.copy2(pm, out / "protocol-measurement.json")
            manifest["copied"]["protocol-measurement.json"] = sha(pm)
        for name in VARIANTS:
            d = root / name
            if not d.is_dir():
                continue
            dst = out / name
            shutil.copytree(d, dst, dirs_exist_ok=True)
            manifest["copied"][name] = {"files": len(list(dst.rglob("*")))}
    (out / "results.json").write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest["variants_merged"] = sorted(merged["variants"])
    manifest["complete"] = all(v in merged["variants"] for v in VARIANTS)
    (out / "aggregate-manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sources", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(aggregate(a.sources, a.out), indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
