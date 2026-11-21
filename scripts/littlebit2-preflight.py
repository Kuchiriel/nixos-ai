#!/usr/bin/env python3
"""Read-only preflight for LittleBit-2 QAT reproduction.

The checker audits the official repository, the local minimal harness, the
Python environment, and GPU capacity.  It never imports the training modules
and never launches main.py, minimal_qat.py, deepspeed, or a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_OFFICIAL_COMMIT = "42d658b0c79f76450b34b6a3547462c7cdc3e1a0"
DEFAULT_MIN_VRAM_MIB = 16 * 1024
DEFAULT_MIN_FREE_MIB = 12 * 1024


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _venv_lib_path() -> str:
    """Derive the library path needed by a Nix-built Python venv.

    The torch wheel is linked against libstdc++.so.6 in the Nix store; the
    plain environment of the Checker does not include it, which produced a
    false-negative "torch unavailable". No store hash is hardcoded: pick the
    newest gcc lib directory visible on this host.
    """
    parts: list[str] = []
    libs = sorted(
        Path('/nix/store').glob('*-gcc-*-lib/lib/libstdc++.so.6'),
        key=lambda q: q.stat().st_mtime,
    ) if Path('/nix/store').exists() else []
    if libs:
        parts.append(str(libs[-1].parent))
    for extra in ('/run/opengl-driver/lib', '/run/current-system/sw/share/nix-ld/lib'):
        if Path(extra).exists():
            parts.append(extra)
    current = os.environ.get('LD_LIBRARY_PATH', '')
    if current:
        parts.append(current)
    return os.pathsep.join(dict.fromkeys(parts))


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 30,
         env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
        }
    except Exception as exc:
        return {"ok": False, "rc": None, "stdout": "", "stderr": f"{type(exc).__name__}: {exc}"}


def _contains(text: str, *needles: str) -> bool:
    return all(needle in text for needle in needles)


def _default_epoch(text: str) -> float | None:
    match = re.search(r'--num_train_epochs["\'],\s*type=float,\s*default=([0-9.]+)', text)
    return float(match.group(1)) if match else None


def _readme_epochs(text: str) -> list[float]:
    values = []
    for match in re.finditer(r"--num_train_epochs\s+([0-9.]+)", text):
        value = float(match.group(1))
        if value not in values:
            values.append(value)
    return values


def audit_sources(official_dir: Path, minimal_path: Path) -> dict[str, Any]:
    main_path = official_dir / "main.py"
    kd_path = official_dir / "utils/kd_utils.py"
    readme_path = official_dir / "README.md"
    minimal_main = minimal_path
    files = {
        "official_main": main_path,
        "official_kd": kd_path,
        "official_readme": readme_path,
        "minimal": minimal_main,
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        return {
            "ready": False,
            "missing": missing,
            "files": {name: {"path": str(path), "exists": path.is_file()} for name, path in files.items()},
            "divergences": [],
            "official": {},
            "minimal": {},
        }

    main = _read(main_path)
    kd = _read(kd_path)
    readme = _read(readme_path)
    minimal = _read(minimal_main)

    official = {
        "hf_training_arguments": "TrainingArguments(" in main,
        "kd_trainer": "KDTrainer(" in main and "KDTrainer" in kd,
        "deepspeed": "import deepspeed" in main and "deepspeed.initialize(" in main,
        "teacher_mandatory": "Loading teacher model" in main and "load_teacher_model(" in main,
        "teacher_kl": "F.kl_div(" in kd,
        "teacher_hidden_mse": "hidden_states[1:]" in kd and "mse_loss" in kd,
        "checkpoint_output": "save_pretrained(" in main and "littlebit_config.json" in main,
        "use_itq": "--use_itq" in main and "use_itq" in readme,
        "default_epochs": _default_epoch(main),
        "readme_epochs": _readme_epochs(readme),
    }
    minimal_features = {
        "hf_training_arguments": "TrainingArguments(" in minimal,
        "kd_trainer": "KDTrainer" in minimal,
        "deepspeed": "deepspeed" in minimal.lower(),
        "teacher_optional": "--teacher" in minimal,
        "teacher_logits_mse": "mse_loss(" in minimal and "out.logits" in minimal,
        "teacher_hidden_mse": "hidden_states" in minimal,
        "fixed_steps": "for step in range(STEPS)" in minimal,
        "checkpoint_output": "save_pretrained(" in minimal,
        "use_itq": "--use-itq" in minimal and "use_itq" in minimal,
        "model": re.search(r"MODEL\s*=\s*['\"]([^'\"]+)", minimal).group(1)
        if re.search(r"MODEL\s*=\s*['\"]([^'\"]+)", minimal) else None,
        "default_steps": int(match.group(1)) if (match := re.search(r"STEPS\s*=\s*int\([^)]*?['\"](\d+)['\"]", minimal)) else None,
    }

    divergences = [
        {
            "area": "schedule",
            "official": f"HF Trainer epochs (default {official['default_epochs']}; README {official['readme_epochs']})",
            "minimal": f"custom fixed-step loop (default {minimal_features['default_steps']})",
            "impact": "minimal is not the paper's 5-epoch schedule",
        },
        {
            "area": "teacher_distillation",
            "official": "mandatory teacher; KL logits + scaled hidden-state MSE",
            "minimal": "optional teacher; logits MSE only",
            "impact": "loss semantics differ even when --teacher is enabled",
        },
        {
            "area": "distributed_training",
            "official": "DeepSpeed/ZeRO-3 path and ZeRO model gathering",
            "minimal": "single-process loop; no DeepSpeed",
            "impact": "not reproducible on the official multi-GPU stack",
        },
        {
            "area": "model_and_dataset",
            "official": "configurable model and c4/c4_wiki/wikitext2",
            "minimal": f"fixed {minimal_features['model']} and wikitext2",
            "impact": "not the official paper configuration",
        },
        {
            "area": "optimizer_schedule",
            "official": "adamw_torch + cosine scheduler + warmup + beta settings",
            "minimal": "fixed LR; AdamW/AdamW8bit/SGD without scheduler/warmup",
            "impact": "optimization trajectory differs",
        },
        {
            "area": "artifact",
            "official": "checkpoint, tokenizer, and littlebit_config.json",
            "minimal": "result JSON only; no trained checkpoint",
            "impact": "official eval/decode latency cannot consume the minimal output",
        },
        {
            "area": "evaluation",
            "official": "eval.py for WikiText-2/C4 PPL and zero-shot tasks",
            "minimal": "inline fixed-window WikiText-2 PPL",
            "impact": "PPL values are not directly interchangeable with the official evaluator",
        },
    ]
    return {
        "ready": True,
        "missing": [],
        "files": {
            name: {
                "path": str(path),
                "exists": True,
                "sha256": _sha256(path),
            }
            for name, path in files.items()
        },
        "official": official,
        "minimal": minimal_features,
        "divergences": divergences,
    }


def probe_git(official_dir: Path, expected_commit: str) -> dict[str, Any]:
    if not official_dir.is_dir():
        return {"ok": False, "commit": None, "expected": expected_commit, "error": "official dir absent"}
    result = _run(["git", "rev-parse", "HEAD"], cwd=official_dir, timeout=15)
    commit = result["stdout"] if result["ok"] else None
    return {
        "ok": result["ok"],
        "commit": commit,
        "expected": expected_commit,
        "matches_expected": commit == expected_commit,
        "error": result["stderr"],
    }


def probe_gpu() -> dict[str, Any]:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return {"ok": False, "error": "nvidia-smi absent"}
    result = _run(
        [
            binary,
            "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout=15,
    )
    if not result["ok"] or not result["stdout"]:
        return {"ok": False, "error": result["stderr"] or "nvidia-smi returned no data"}
    rows = []
    for line in result["stdout"].splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            continue
        try:
            rows.append(
                {
                    "name": parts[0],
                    "total_mib": int(parts[1]),
                    "used_mib": int(parts[2]),
                    "free_mib": int(parts[3]),
                    "utilization_percent": int(parts[4]),
                }
            )
        except ValueError:
            continue
    return {"ok": bool(rows), "gpus": rows, "error": result["stderr"]}


def probe_python(python: Path) -> dict[str, Any]:
    probe = (
        "import json,torch,transformers;"
        "print(json.dumps({'torch':torch.__version__,"
        "'cuda_available':bool(torch.cuda.is_available()),"
        "'transformers':transformers.__version__}))"
    )
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = _venv_lib_path()
    result = _run([str(python), "-c", probe], timeout=45, env=env)
    payload: dict[str, Any] = {}
    if result["ok"]:
        try:
            payload = json.loads(result["stdout"].splitlines()[-1])
        except Exception:
            result = {**result, "ok": False, "stderr": "python probe returned invalid JSON"}
    version = str(payload.get("transformers", ""))
    return {
        "ok": bool(result["ok"] and payload),
        "python": str(python),
        "torch": payload.get("torch"),
        "transformers": version,
        "transformers_4_51": version.startswith("4.51."),
        "cuda_available": bool(payload.get("cuda_available")),
        "error": result["stderr"],
    }


def evaluate_gate(
    sources: dict[str, Any],
    git: dict[str, Any],
    gpu: dict[str, Any],
    environment: dict[str, Any],
    *,
    min_vram_mib: int,
    min_free_mib: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    gpu_rows = gpu.get("gpus") or []
    best = max(gpu_rows, key=lambda row: row.get("free_mib", 0), default=None)
    hardware_ready = bool(
        best
        and best.get("total_mib", 0) >= min_vram_mib
        and best.get("free_mib", 0) >= min_free_mib
    )
    if not gpu_rows:
        reasons.append("no NVIDIA GPU was measured")
    elif best and best.get("total_mib", 0) < min_vram_mib:
        reasons.append(
            f"best GPU has {best.get('total_mib', 0)} MiB total; official-QAT gate requires {min_vram_mib} MiB"
        )
    elif best and best.get("free_mib", 0) < min_free_mib:
        reasons.append(
            f"best GPU has {best.get('free_mib', 0)} MiB free; official-QAT gate requires {min_free_mib} MiB"
        )
    if not sources.get("ready"):
        reasons.append("official/minimal source files are missing")
    if not git.get("ok"):
        reasons.append("official repository commit could not be read")
    elif not git.get("matches_expected"):
        reasons.append(
            f"official repository commit {git.get('commit')} does not match pinned {git.get('expected')}"
        )
    if not environment.get("ok"):
        reasons.append("Python environment probe failed")
    else:
        if not environment.get("transformers_4_51"):
            reasons.append("transformers 4.51.x is required by the official README")
        if not environment.get("cuda_available"):
            reasons.append("PyTorch CUDA is unavailable")
    ready = hardware_ready and bool(sources.get("ready")) and bool(git.get("matches_expected")) and bool(
        environment.get("ok")
        and environment.get("transformers_4_51")
        and environment.get("cuda_available")
    )
    return {
        "ready_for_official_qat": ready,
        "hardware_ready": hardware_ready,
        "source_ready": bool(sources.get("ready")),
        "git_ready": bool(git.get("matches_expected")),
        "environment_ready": bool(
            environment.get("ok")
            and environment.get("transformers_4_51")
            and environment.get("cuda_available")
        ),
        "best_gpu": best,
        "thresholds": {"min_vram_mib": min_vram_mib, "min_free_mib": min_free_mib},
        "reasons": reasons,
    }


def collect_report(args: argparse.Namespace) -> dict[str, Any]:
    official_dir = Path(args.official_dir).expanduser().resolve()
    minimal_path = Path(args.minimal).expanduser().resolve()
    python = Path(args.python).expanduser()
    sources = audit_sources(official_dir, minimal_path)
    git = probe_git(official_dir, args.expected_commit)
    gpu = probe_gpu()
    environment = probe_python(python)
    gate = evaluate_gate(
        sources,
        git,
        gpu,
        environment,
        min_vram_mib=args.min_vram_mib,
        min_free_mib=args.min_free_mib,
    )
    return {
        "schema": 1,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "official_dir": str(official_dir),
        "minimal_path": str(minimal_path),
        "training_started": False,
        "read_only": True,
        "sources": sources,
        "git": git,
        "gpu": gpu,
        "environment": environment,
        "gate": gate,
        "recommendation": (
            "official QAT preflight passed; run the official command separately"
            if gate["ready_for_official_qat"]
            else "do not start QAT on this host; use the reasons as the next-hardware checklist"
        ),
    }


def _human(report: dict[str, Any]) -> str:
    gate = report["gate"]
    gpu = gate.get("best_gpu") or {}
    env = report["environment"]
    lines = [
        f"LittleBit-2 preflight: ready_for_official_qat={gate['ready_for_official_qat']}",
        f"official commit: {report['git'].get('commit')} (pinned match={report['git'].get('matches_expected')})",
        (
            f"GPU: {gpu.get('name', 'none')} total={gpu.get('total_mib', 0)} MiB "
            f"free={gpu.get('free_mib', 0)} MiB"
        ),
        (
            f"env: torch={env.get('torch')} transformers={env.get('transformers')} "
            f"cuda={env.get('cuda_available')} ok={env.get('ok')}"
        ),
        f"source divergences: {len(report['sources'].get('divergences', []))}",
        "reasons:",
    ]
    lines.extend(f"  - {reason}" for reason in gate.get("reasons", []))
    lines.append("training_started=false")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    default_official = os.environ.get("LITTLEBIT_DIR", "~/projects/LittleBit")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-dir", default=default_official)
    parser.add_argument("--minimal", default="")
    parser.add_argument("--python", default="")
    parser.add_argument("--expected-commit", default=EXPECTED_OFFICIAL_COMMIT)
    parser.add_argument("--min-vram-mib", type=int, default=DEFAULT_MIN_VRAM_MIB)
    parser.add_argument("--min-free-mib", type=int, default=DEFAULT_MIN_FREE_MIB)
    parser.add_argument("--json", action="store_true", help="emit the complete machine-readable report")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    official_dir = Path(args.official_dir).expanduser().resolve()
    if not args.minimal:
        args.minimal = str(official_dir / "minimal_qat.py")
    if not args.python:
        args.python = str(official_dir / ".venv/bin/python")
    report = collect_report(args)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(_human(report))
    return 0 if report["gate"]["ready_for_official_qat"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
