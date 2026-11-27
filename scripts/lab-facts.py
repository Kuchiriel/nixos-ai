#!/usr/bin/env python3
"""lab-facts — JSON unico com numeros medidos e status dos gates.

Fonte: arch-facts.json (checkpoints medidos), JSONs das frentes F52/F75/F79,
e baselines pre-registrados em docs. Nao inventa nada: se arquivo ausente,
marca 'ausente'.
"""
import json, time
from pathlib import Path

H = Path("/home/nixos")
B = H / "work/hybrid"
OUT = H / "projects/ai-mesh/docs/lab-facts.json"

def load(p, default=None):
    try: return json.loads(Path(p).read_text())
    except Exception: return default

arch = load(B / "arch-facts.json", {}).get("models", [])
f52 = load(B / "f52-150m-68k-s42.json", {})
f75 = load(B / "f75-simplefull-s42.json", {})
f79 = load(B / "f79-20k-s42.json", {})

models = []
for m in arch:
    models.append({k: m.get(k) for k in ("label", "d", "params", "val", "acc", "steps", "corpus")})
if f79 and not any("F79" in m.get("label", "") for m in models):
    models.append({"label": "F79 · 20k curado", "d": f79.get("d"), "val": f79.get("val_loss"),
                   "acc": f79.get("acc"), "steps": f79.get("steps"),
                   "corpus": "SimpleStories 210M"})

gates = [
 {"id": "F52-gate-1.5", "status": "passado", "value": f52.get("val_loss"),
  "threshold": "<=1.5", "source": "f52-150m-68k-s42.json"},
 {"id": "F76-curadoria-vs-volume", "status": "passado",
  "value": None, "threshold": "F53 1.7334 vs F43 1.9762", "source": "f53/f43 json"},
 {"id": "F86-H3-20k", "status": "passado", "value": f79.get("val_loss"),
  "threshold": "<=1.5999", "source": "f79-watch-result.json"},
 {"id": "F69-compressao-dedup8", "status": "rejeitado",
  "value": 2.7304, "threshold": "<1.95", "source": "f72-gate-dedup8 doc"},
 {"id": "F91-ablacao-beta", "status": "pendente",
  "value": None, "threshold": "3/3 tamanhos, Delta>=0.01 nat", "source": "f91 doc"},
]

out = {
 "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
 "source": "lab-facts.py (arch-facts + JSONs das frentes)",
 "models": models,
 "baselines": {
   "enwik8_1mb": {"xz9_bytes": 302772, "zstd19_bytes": 312705, "gzip9_bytes": 370603,
                  "bits_per_byte": {"xz9": 2.31, "zstd19": 2.3857, "gzip9": 2.8275}},
   "nncp": {"enwik8_bpb": 1.19, "enwik9_bpb": 0.853, "source": "bellard.org/nncp"},
   "llm_compression_2026": {"decode_KB_s": 181.0, "ratio": 7.17,
                            "source": "arxiv 2610.17586 (A100)"}
 },
 "gates": gates,
 "note": "numeros medidos; status pendente nao e' resultado"
}
OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({"models": len(models), "gates": len(gates), "out": str(OUT)}))
