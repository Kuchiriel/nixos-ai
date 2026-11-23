#!/usr/bin/env python3
"""Gera um job Kaggle que so roda PPL+decode em checkpoints ja treinados.

Motivo medido 23-24/11: baseline completou 5 epochs (28428s) e PPL oficial
150.2832, mas o job morreu no decode por SyntaxError no codigo gerado.
Re-treinar custaria mais 8h; este job so pos-processa.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

BASE = Path("https://www.kaggle.com/api/v1/kernels")

SCRIPT = r'''#!/usr/bin/env python3
"""Resume oficial: PPL eval.py + decode nos checkpoints ja treinados do LittleBit-2."""
import json, os, re, subprocess, sys, time
from pathlib import Path

OUT = Path("/kaggle/working/official-output")
REPO = Path("/kaggle/working/LittleBit")
COMMIT = "42d658b0c79f76450b34b6a3547462c7cdc3e1a0"

def log(m): print(m, flush=True)

def run(cmd, *, cwd=None, capture=False):
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None)
    if r.returncode != 0:
        if capture and r.stdout: log(r.stdout)
        raise RuntimeError("rc=%d: %s" % (r.returncode, " ".join(cmd)))
    return (r.stdout or "") if capture else ""

def decode_code(path, warmup, tokens):
    return """import json,time,torch
from quantization.hub import LittleBitModel
from utils.datautils import load_tokenizer
path=%r
warmup=%r
tokens=%r
model=LittleBitModel.from_pretrained(path, torch_dtype=torch.bfloat16, device="auto")
tok=load_tokenizer(path)
device=next(model.parameters()).device
ids=tok("Fleet parity is measured evidence, not a guess.", return_tensors="pt").input_ids[:, :16].to(device)
model.eval()
with torch.inference_mode():
    model.generate(ids, max_new_tokens=warmup, do_sample=False, use_cache=True)
    if device.type == "cuda": torch.cuda.synchronize()
    started=time.perf_counter()
    out=model.generate(ids, max_new_tokens=tokens, do_sample=False, use_cache=True)
    if device.type == "cuda": torch.cuda.synchronize()
    elapsed=time.perf_counter()-started
generated=int(out.shape[-1]-ids.shape[-1])
print("LITTLEBIT_DECODE",json.dumps({"elapsed_seconds":elapsed,"generated_tokens":generated,"tokens_per_second":generated/elapsed if elapsed else 0,"device":str(device)}))
""" % (path, warmup, tokens)

def main():
    if not REPO.exists():
        run(["git", "clone", "-q", "https://github.com/SamsungLabs/LittleBit.git", str(REPO)])
    run(["git", "checkout", "-q", COMMIT], cwd=REPO)
    run([sys.executable, "-m", "pip", "install", "-q", "transformers==4.51.3",
         "datasets==3.4.1", "accelerate>=1.6.0", "deepspeed", "bitsandbytes",
         "sentencepiece", "lm-eval==0.4.8"], cwd=REPO)
    variants = [v for v in ("baseline", "littlebit2") if (OUT / v / "model.safetensors").is_file()]
    if not variants:
        raise RuntimeError("nenhum checkpoint encontrado em " + str(OUT))
    results = {"schema": 1, "production_writes": False,
               "official_commit": COMMIT, "variants": {}}
    for name in variants:
        path = OUT / name
        ppl_log = run([sys.executable, "eval.py", "--model_id", str(path),
                       "--ppl_task", "wikitext2", "--zeroshot_task", "",
                       "--batch_size", "1", "--num_fewshot", "0",
                       "--seqlen", "2048"], cwd=REPO, capture=True)
        (path / "official-eval.log").write_text(ppl_log, encoding="utf-8")
        m = re.search(r"\[wikitext2\]\s+PPL\s*=\s*([0-9.]+)", ppl_log)
        if not m: raise RuntimeError("PPL ausente para " + name)
        code = decode_code(str(path), 16, 128)
        compile(code, "<decode>", "exec")
        raw = run([sys.executable, "-c", code], cwd=REPO, capture=True)
        d = re.search(r"LITTLEBIT_DECODE\s+(\{.*\})", raw)
        if not d: raise RuntimeError("decode ausente para " + name)
        dec = json.loads(d.group(1))
        (path / "decode-latency.json").write_text(json.dumps(dec, indent=2) + "\n", encoding="utf-8")
        results["variants"][name] = {"use_itq": name == "littlebit2",
                                     "checkpoint": str(path),
                                     "official_wikitext2_ppl": float(m.group(1)),
                                     "decode": dec}
        log("VARIANT_DONE " + name)
    (OUT / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    log("RESULTS " + json.dumps(results, sort_keys=True))
    log("OFFICIAL_LITTLEBIT2_COMPLETE")

if __name__ == "__main__":
    raise SystemExit(main())
'''

META = {
    "id": "kuchiriel/littlebit2-official-resume-2026-11-24",
    "title": "LittleBit2 Official Resume PPL Decode 2026 11 24",
    "code_file": "script.py",
    "language": "python",
    "kernel_type": "script",
    "is_private": True,
    "enable_gpu": True,
    "machine_shape": "NvidiaTeslaT4",
    "enable_internet": True,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "script.py").write_text(SCRIPT, encoding="utf-8")
    (a.out / "kernel-metadata.json").write_text(
        json.dumps(META, indent=2) + "\n", encoding="utf-8")
    compile(SCRIPT, "<resume>", "exec")
    print("job pronto em", a.out, "bytes", len(SCRIPT))


if __name__ == "__main__":
    raise SystemExit(main())
