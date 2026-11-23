#!/usr/bin/env python3
"""Official LittleBit-2 paired 5-epoch QAT on Kaggle T4x2.

This kernel runs the upstream main.py and eval.py at a pinned commit. The
minimal_qat.py harness is intentionally not used as evidence.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent
# Kaggle kernels push uploads only code_file=script.py. Keep the validated
# contract embedded so the job never depends on auxiliary repo files.
EMBEDDED_CONTRACT = json.loads(r'''{
  "dataset": "wikitext2",
  "evaluation": {
    "decode_max_new_tokens": 128,
    "decode_warmup_tokens": 16,
    "ppl_evaluator": "official eval.py",
    "ppl_task": "wikitext2",
    "ppl_seqlen": 2048,
    "seed": 42
  },
  "model": "Qwen/Qwen3-0.6B",
  "official_commit": "42d658b0c79f76450b34b6a3547462c7cdc3e1a0",
  "production_writes": false,
  "protocol": {
    "deepspeed_config": "configs/zero3.json",
    "eff_bit": 1.0,
    "effective_global_batch_size": 4,
    "epochs": 5.0,
    "expected_dataset_examples": 1229,
    "expected_optimizer_steps_per_variant": 1540,
    "gradient_accumulation_steps": 2,
    "kv_factor": 1.0,
    "l2l_loss_scale": 10.0,
    "learning_rate": 4e-05,
    "min_split_dim": 8,
    "per_device_train_batch_size": 1,
    "quant_func": "SmoothSign",
    "quant_mod": "LittleBitLinear",
    "residual": true,
    "scheduler": "cosine",
    "seed": 42,
    "sequence_length": 2048,
    "trainer": "official main.py",
    "warmup_ratio": 0.02
  },
  "resources": {
    "kaggle_machine_shape": "NvidiaTeslaT4",
    "kaggle_session_limit_hours": 12,
    "minimum_gpu_count": 2,
    "minimum_vram_mib_per_gpu": 15000
  },
  "schema": 1,
  "stop_conditions": [
    "official commit mismatch",
    "fewer than two GPUs or insufficient VRAM",
    "dataset example count differs from the measured contract",
    "official trainer exits non-zero",
    "checkpoint or littlebit_config.json is missing",
    "official PPL evaluation fails"
  ],
  "variants": [
    {
      "name": "baseline",
      "use_itq": false
    },
    {
      "name": "littlebit2",
      "use_itq": true
    }
  ]
}''')
CONTRACT_PATH = HERE / "contract.json"
if CONTRACT_PATH.is_file():
    CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if CONTRACT != EMBEDDED_CONTRACT:
        raise RuntimeError("embedded contract differs from contract.json")
else:
    CONTRACT = EMBEDDED_CONTRACT
WORKING = Path("/kaggle/working")
REPO = WORKING / "LittleBit"
OUTPUT = WORKING / "official-output"
COMMIT = CONTRACT["official_commit"]
PROTOCOL = CONTRACT["protocol"]
RESOURCES = CONTRACT["resources"]
EVALUATION = CONTRACT["evaluation"]


def log(message: str) -> None:
    print(message, flush=True)


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None,
        capture: bool = False) -> str:
    log("+ " + " ".join(command))
    started = time.time()
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    elapsed = time.time() - started
    log(f"RC={result.returncode} elapsed_seconds={elapsed:.1f}")
    if result.returncode != 0:
        if capture and result.stdout:
            log(result.stdout)
        raise RuntimeError(f"command failed rc={result.returncode}")
    return (result.stdout or "") if capture else ""


def parse_gpu_rows(raw: str) -> list[dict]:
    rows = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) == 3:
            try:
                rows.append({"name": parts[0], "total_mib": int(parts[1]), "free_mib": int(parts[2])})
            except ValueError:
                continue
    return rows


def verify_environment() -> dict:
    query = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ]
    rows = parse_gpu_rows(run(query, capture=True))
    if len(rows) < RESOURCES["minimum_gpu_count"]:
        raise RuntimeError(f"need {RESOURCES['minimum_gpu_count']} GPUs, measured {len(rows)}")
    if any(row["total_mib"] < RESOURCES["minimum_vram_mib_per_gpu"] for row in rows):
        raise RuntimeError("measured GPU VRAM is below the official-QAT contract")
    log(json.dumps({"gpus": rows}, ensure_ascii=False))
    return {"gpus": rows}


def prepare_repository() -> None:
    if not REPO.exists():
        run(["git", "clone", "-q", "https://github.com/SamsungLabs/LittleBit.git", str(REPO)])
    run(["git", "checkout", "-q", COMMIT], cwd=REPO)
    actual = run(["git", "rev-parse", "HEAD"], cwd=REPO, capture=True).strip()
    if actual != COMMIT:
        raise RuntimeError(f"official commit mismatch: {actual} != {COMMIT}")
    main = (REPO / "main.py").read_text(encoding="utf-8")
    kd = (REPO / "utils/kd_utils.py").read_text(encoding="utf-8")
    required = {
        "training_arguments": "TrainingArguments(" in main,
        "kd_trainer": "KDTrainer(" in main and "KDTrainer" in kd,
        "teacher_kl": "F.kl_div(" in kd,
        "teacher_hidden_mse": "hidden_states[1:]" in kd and "mse_loss" in kd,
        "deepspeed": "deepspeed.initialize(" in main,
        "checkpoint_output": "littlebit_config.json" in main and "save_pretrained(" in main,
        "zero3_config": (REPO / PROTOCOL["deepspeed_config"]).is_file(),
    }
    if not all(required.values()):
        raise RuntimeError("official protocol features missing: " + json.dumps(required))
    log("official_protocol_features=" + json.dumps(required, sort_keys=True))


def verify_dataset() -> dict:
    code = (
        "from utils.datautils import get_qat_dataset,load_tokenizer;"
        "t=load_tokenizer(%r);d=get_qat_dataset('wikitext2',t);"
        "print('LITTLEBIT_DATASET',len(d),len(d[0]['input_ids']))"
    ) % CONTRACT["model"]
    raw = run([sys.executable, "-c", code], cwd=REPO, capture=True)
    match = re.search(r"LITTLEBIT_DATASET\s+(\d+)\s+(\d+)", raw)
    if not match:
        raise RuntimeError("could not measure official dataset")
    examples, sequence_length = int(match.group(1)), int(match.group(2))
    if examples != PROTOCOL["expected_dataset_examples"]:
        raise RuntimeError(f"dataset examples changed: {examples}")
    if sequence_length != PROTOCOL["sequence_length"]:
        raise RuntimeError(f"dataset sequence length changed: {sequence_length}")
    per_rank_batches = (examples + RESOURCES["minimum_gpu_count"] - 1) // RESOURCES["minimum_gpu_count"]
    steps_per_epoch = (
        per_rank_batches + PROTOCOL["gradient_accumulation_steps"] - 1
    ) // PROTOCOL["gradient_accumulation_steps"]
    expected_steps = steps_per_epoch * int(PROTOCOL["epochs"])
    if expected_steps != PROTOCOL["expected_optimizer_steps_per_variant"]:
        raise RuntimeError(f"optimizer step contract mismatch: {expected_steps}")
    measured = {
        "examples": examples,
        "sequence_length": sequence_length,
        "optimizer_steps_per_variant": expected_steps,
    }
    log("dataset_measurement=" + json.dumps(measured, sort_keys=True))
    (OUTPUT / "protocol-measurement.json").write_text(
        json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def train_variant(variant: dict) -> Path:
    name = str(variant["name"])
    use_itq = bool(variant["use_itq"])
    save_dir = OUTPUT / name
    command = [
        "deepspeed",
        "--num_gpus=%d" % RESOURCES["minimum_gpu_count"],
        "main.py",
        "--model_id", CONTRACT["model"],
        "--dataset", CONTRACT["dataset"],
        "--save_dir", str(OUTPUT),
        "--f_name", name,
        "--seed", str(PROTOCOL["seed"]),
        "--num_train_epochs", str(PROTOCOL["epochs"]),
        "--per_device_train_batch_size", str(PROTOCOL["per_device_train_batch_size"]),
        "--gradient_accumulation_steps", str(PROTOCOL["gradient_accumulation_steps"]),
        "--lr", str(PROTOCOL["learning_rate"]),
        "--warmup_ratio", str(PROTOCOL["warmup_ratio"]),
        "--report", "tensorboard",
        "--run_name", "littlebit2-official-" + name,
        "--quant_func", PROTOCOL["quant_func"],
        "--quant_mod", PROTOCOL["quant_mod"],
        "--residual", "True" if PROTOCOL["residual"] else "False",
        "--eff_bit", str(PROTOCOL["eff_bit"]),
        "--kv_factor", str(PROTOCOL["kv_factor"]),
        "--min_split_dim", str(PROTOCOL["min_split_dim"]),
        "--l2l_loss_scale", str(PROTOCOL["l2l_loss_scale"]),
        "--use_itq", "True" if use_itq else "False",
        "--ds_config_path", PROTOCOL["deepspeed_config"],
    ]
    started = time.time()
    run(command, cwd=REPO)
    elapsed = time.time() - started
    required = ["config.json", "littlebit_config.json"]
    if not all((save_dir / filename).is_file() for filename in required):
        raise RuntimeError(f"official artifacts missing in {save_dir}")
    (save_dir / "train-wall-time.json").write_text(
        json.dumps({"elapsed_seconds": round(elapsed, 1)}, indent=2) + "\n", encoding="utf-8"
    )
    log(f"variant_complete={name} elapsed_seconds={elapsed:.1f}")
    return save_dir


def official_ppl(path: Path) -> float:
    output = run([
        sys.executable,
        "eval.py",
        "--model_id", str(path),
        "--ppl_task", EVALUATION["ppl_task"],
        "--zeroshot_task", "",
        "--batch_size", "1",
        "--num_fewshot", "0",
        "--seqlen", str(PROTOCOL["sequence_length"]),
    ], cwd=REPO, capture=True)
    (path / "official-eval.log").write_text(output, encoding="utf-8")
    match = re.search(r"\[" + re.escape(EVALUATION["ppl_task"]) + r"\]\s+PPL\s+=\s+([0-9.]+)", output)
    if not match:
        raise RuntimeError(f"official PPL not found for {path}")
    return float(match.group(1))


def decode_latency(path: Path) -> dict:
    code = r'''
import json,time,torch
from quantization.hub import LittleBitModel
from utils.datautils import load_tokenizer
path=json.loads(r''' + json.dumps(str(path)) + r''')
warmup=int(json.loads(r''' + json.dumps(str(EVALUATION["decode_warmup_tokens"])) + r''')
tokens=int(json.loads(r''' + json.dumps(str(EVALUATION["decode_max_new_tokens"])) + r'''))
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
'''
    raw = run([sys.executable, "-c", code], cwd=REPO, capture=True)
    match = re.search(r"LITTLEBIT_DECODE\s+(\{.*\})", raw)
    if not match:
        raise RuntimeError(f"decode measurement missing for {path}")
    result = json.loads(match.group(1))
    (path / "decode-latency.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def log_selected_variants(variants: list[dict], selector: str) -> str:
    """Mensagem de selecao — isolada para teste (evita NameError em f-string)."""
    return "selected_variants=%s selector=%s" % (
        [v.get("name") for v in variants], selector)


def selected_variants(variants: list[dict] | None = None,
                      selector: str | None = None) -> list[dict]:
    """One variant per Kaggle session (12h cap); both env names accepted."""
    if variants is None:
        variants = CONTRACT["variants"]
    if selector is None:
        selector = (os.environ.get("LITTLEBIT2_VARIANT")
                    or os.environ.get("LB_VARIANT") or "all")
    mode = str(selector).strip().lower()
    if mode in ("", "all"):
        return list(variants)
    chosen = [v for v in variants
              if mode == str(v.get("name", "")).lower()
              or mode == ("itq" if v.get("use_itq") else "baseline")]
    if not chosen:
        raise RuntimeError(f"unknown variant selector: {selector}")
    return chosen


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    log("contract=" + json.dumps(CONTRACT, sort_keys=True))
    run([
        sys.executable, "-m", "pip", "install", "-q",
        "transformers==4.51.3",
        "datasets==3.4.1",
        "accelerate>=1.6.0",
        "deepspeed",
        "tensorboard",
        "tensorboardX",
        "bitsandbytes",
        "sentencepiece",
        "tqdm",
        "pytorch-optimizer>=3.5.0",
        "GPUtil>=1.4.0",
        "lm-eval==0.4.8",
    ])
    hardware = verify_environment()
    prepare_repository()
    dataset = verify_dataset()
    results = {
        "schema": 1,
        "production_writes": False,
        "official_commit": COMMIT,
        "hardware": hardware,
        "dataset": dataset,
        "variants": {},
    }
    selector = (os.environ.get("LITTLEBIT2_VARIANT")
                or os.environ.get("LB_VARIANT") or "all")
    variants = selected_variants(selector=selector)
    log(log_selected_variants(variants, selector))
    for variant in variants:
        path = train_variant(variant)
        ppl = official_ppl(path)
        decode = decode_latency(path)
        results["variants"][variant["name"]] = {
            "use_itq": bool(variant["use_itq"]),
            "checkpoint": str(path),
            "official_wikitext2_ppl": ppl,
            "decode": decode,
        }
        (OUTPUT / "results.json").write_text(
            json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    log("RESULTS " + json.dumps(results, sort_keys=True))
    log("OFFICIAL_LITTLEBIT2_COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
