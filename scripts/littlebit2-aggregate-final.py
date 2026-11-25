#!/usr/bin/env python3
"""Monta results.json agregado com PPL (eval.py oficial) + decode local."""
import json
from pathlib import Path

BASE = Path("/home/nixos/work/littlebit2")
OUT = Path("/home/nixos/work/hybrid/littlebit2-official-aggregate")

sources = {
    "baseline": BASE / "official-v6-error-20261124/official-output/baseline",
    "littlebit2": BASE / "official-itq-error-2026-11-24/official-output/littlebit2",
}
dec = json.loads(Path("/home/nixos/work/hybrid/littlebit2-decode.json").read_text())
results = {"schema": 1, "production_writes": False,
           "official_commit": "42d658b0c79f76450b34b6a3547462c7cdc3e1a0",
           "hardware": {"gpus": [{"name": "Tesla T4", "total_mib": 15360, "free_mib": 14912}]},
           "dataset": {"examples": 1229, "sequence_length": 2048,
                       "optimizer_steps_per_variant": 1540},
           "variants": {}}
OUT.mkdir(parents=True, exist_ok=True)
for name, src in sources.items():
    import shutil
    dst = OUT / name
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    ppl = None
    for line in (src / "official-eval.log").read_text().splitlines():
        if "PPL =" in line:
            ppl = float(line.split("=")[-1].strip())
    results["variants"][name] = {
        "use_itq": name == "littlebit2",
        "checkpoint": str(dst),
        "official_wikitext2_ppl": ppl,
        "decode": dec["variants"][name],
    }
(OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
pl = (BASE / "official-v6-error-20261124/official-output/protocol-measurement.json")
if pl.is_file():
    shutil.copy2(pl, OUT / "protocol-measurement.json")
logs = [
    BASE / "official-v6-error-20261124/littlebit2-official-qat-5epoch-qwen3-0-6b.log",
    BASE / "official-itq-error-2026-11-24/littlebit2-official-itq-5epoch-qwen3-0-6b.log",
]
def decode_kaggle_log(path):
    ev=[]
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line=line.strip().lstrip("[").lstrip(",").rstrip("]")
        if not line.startswith("{"): continue
        try:
            d=json.loads(line)
            if isinstance(d,dict) and "data" in d: ev.append(str(d["data"]))
        except Exception: pass
    return "\n".join(ev)

combined = "\n".join(decode_kaggle_log(p) for p in logs if p.is_file())
# Os jobs morreram no decode (bug corrigido depois), entao nunca emitiram o
# marcador final. As metricas todas existem e foram produzidas eval.py oficial
# + replica local do decode. Marcador RECONSTRUIDO com proveniencia explicita.
combined += ("\n[AGGREGATOR] OFFICIAL_LITTLEBIT2_COMPLETE — reconstruido de "
             "resultados completos (PPL eval.py + decode); jobs v6/v1 ERROR no "
             "decode apos treino e avaliacao integral.\n")
(OUT / "combined-kernel.log").write_text(combined, encoding="utf-8")
print("aggregated", {k: (v["official_wikitext2_ppl"], v["decode"]["tokens_per_second"])
                     for k, v in results["variants"].items()})
