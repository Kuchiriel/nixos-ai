"""Experiment Tracker — records and compares benchmark results.

Tracks:
- Baseline → patch/fork → benchmark → result
- Hardware state (GPU, CPU, RAM, temperature)
- Reproducibility metadata

Usage:
    from jarvis.benchmarks.experiment_tracker import ExperimentTracker
    
    tracker = ExperimentTracker()
    exp = tracker.start_experiment(
        name="baseline-vs-ehs25",
        description="Compare upstream with Expert Hot Store fork",
        config={
            "model": "Qwen3.6-35B-A3B-Q4_K_M",
            "backend": "llama-cpp",
            "hardware": "RTX 4050 6GB",
        },
    )
    
    # Run baseline
    result = tracker.record_run(exp.id, config_name="baseline", metrics={...})
    
    # Run experiment
    result = tracker.record_run(exp.id, config_name="ehs25", metrics={...})
    
    # Compare
    comparison = tracker.compare(exp.id)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".local/state/jarvis/experiments"


@dataclass
class RunResult:
    """Result of a single benchmark run."""
    config_name: str
    timestamp: float = field(default_factory=time.time)
    
    # Performance metrics
    peak_tg: float = 0.0  # Peak tokens/second (text generation)
    sustained_tg: float = 0.0  # Sustained tokens/second
    median_tg: float = 0.0
    p90_tg: float = 0.0
    stdev_tg: float = 0.0
    
    # Prefill
    peak_pp: float = 0.0  # Peak prompt processing tokens/second
    
    # Hardware state
    gpu_temp_c: float = 0.0
    gpu_clock_mhz: float = 0.0
    gpu_power_w: float = 0.0
    gpu_util_pct: float = 0.0
    vram_used_mb: int = 0
    vram_total_mb: int = 0
    cpu_temp_c: float = 0.0
    ram_used_mb: int = 0
    
    # Timing
    total_time_s: float = 0.0
    warmup_s: float = 0.0
    
    # Classification
    classification: str = ""  # STABLE, MODERATE_THROTTLING, etc.
    
    # Raw data
    raw_runs: list[dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    backend: str = "llama-cpp"
    commit: str = ""
    fork: str = ""  # "upstream", "wackmall", "ik", "moe-cache", etc.
    patch_description: str = ""
    
    # Status
    status: str = "OK"  # OK, FAILED, TIMEOUT, OOM
    error: str = ""


@dataclass
class Experiment:
    """An experiment comparing multiple configurations."""
    id: str
    name: str
    description: str = ""
    timestamp: float = field(default_factory=time.time)
    config: dict[str, Any] = field(default_factory=dict)
    runs: list[RunResult] = field(default_factory=list)
    status: str = "running"  # running, completed, failed


class ExperimentTracker:
    """Track and compare benchmark experiments."""
    
    def __init__(self, state_dir: Path | None = None):
        self._dir = state_dir or STATE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
    
    def start_experiment(
        self,
        name: str,
        description: str = "",
        config: dict[str, Any] | None = None,
    ) -> Experiment:
        """Start a new experiment."""
        exp_id = f"{name}-{int(time.time())}"
        exp = Experiment(
            id=exp_id,
            name=name,
            description=description,
            config=config or {},
        )
        self._save_experiment(exp)
        return exp
    
    def record_run(
        self,
        experiment_id: str,
        config_name: str,
        metrics: dict[str, Any],
        *,
        status: str = "OK",
        error: str = "",
    ) -> RunResult:
        """Record a benchmark run result."""
        exp = self._load_experiment(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment not found: {experiment_id}")
        
        run = RunResult(
            config_name=config_name,
            status=status,
            error=error,
            **{k: v for k, v in metrics.items() if hasattr(RunResult, k)},
        )
        
        exp.runs.append(run)
        self._save_experiment(exp)
        return run
    
    def complete_experiment(self, experiment_id: str) -> Experiment:
        """Mark an experiment as completed."""
        exp = self._load_experiment(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment not found: {experiment_id}")
        
        exp.status = "completed"
        self._save_experiment(exp)
        return exp
    
    def compare(self, experiment_id: str) -> dict[str, Any]:
        """Compare runs within an experiment."""
        exp = self._load_experiment(experiment_id)
        if exp is None:
            raise ValueError(f"Experiment not found: {experiment_id}")
        
        if len(exp.runs) < 2:
            return {"error": "Need at least 2 runs to compare"}
        
        # Find baseline and experiment runs
        runs_by_config: dict[str, list[RunResult]] = {}
        for run in exp.runs:
            if run.config_name not in runs_by_config:
                runs_by_config[run.config_name] = []
            runs_by_config[run.config_name].append(run)
        
        comparison = {
            "experiment": exp.name,
            "configs": {},
            "ranking": [],
        }
        
        for config_name, runs in runs_by_config.items():
            tgs = [r.peak_tg for r in runs if r.peak_tg > 0]
            sustained = [r.sustained_tg for r in runs if r.sustained_tg > 0]
            
            comparison["configs"][config_name] = {
                "runs": len(runs),
                "peak_tg_mean": sum(tgs) / len(tgs) if tgs else 0,
                "peak_tg_max": max(tgs) if tgs else 0,
                "peak_tg_min": min(tgs) if tgs else 0,
                "sustained_tg_mean": sum(sustained) / len(sustained) if sustained else 0,
                "classification": runs[0].classification if runs else "",
                "avg_gpu_temp": sum(r.gpu_temp_c for r in runs) / len(runs) if runs else 0,
                "avg_power": sum(r.gpu_power_w for r in runs) / len(runs) if runs else 0,
            }
        
        # Rank by sustained performance
        comparison["ranking"] = sorted(
            comparison["configs"].keys(),
            key=lambda k: comparison["configs"][k]["sustained_tg_mean"],
            reverse=True,
        )
        
        # Add delta analysis
        if len(comparison["ranking"]) >= 2:
            baseline = comparison["ranking"][-1]  # slowest as baseline
            winner = comparison["ranking"][0]  # fastest
            
            baseline_tg = comparison["configs"][baseline]["sustained_tg_mean"]
            winner_tg = comparison["configs"][winner]["sustained_tg_mean"]
            
            if baseline_tg > 0:
                improvement_pct = (winner_tg - baseline_tg) / baseline_tg * 100
            else:
                improvement_pct = 0
            
            comparison["delta"] = {
                "baseline": baseline,
                "winner": winner,
                "improvement_pct": round(improvement_pct, 2),
                "winner_tg": round(winner_tg, 2),
                "baseline_tg": round(baseline_tg, 2),
            }
        
        return comparison
    
    def list_experiments(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent experiments."""
        experiments = []
        for p in sorted(self._dir.glob("*.json"), reverse=True)[:limit]:
            try:
                with open(p) as f:
                    data = json.load(f)
                experiments.append({
                    "id": data.get("id", p.stem),
                    "name": data.get("name", ""),
                    "status": data.get("status", ""),
                    "runs": len(data.get("runs", [])),
                    "timestamp": data.get("timestamp", 0),
                })
            except Exception:
                continue
        return experiments
    
    def _save_experiment(self, exp: Experiment) -> None:
        """Save experiment to disk."""
        path = self._dir / f"{exp.id}.json"
        with open(path, "w") as f:
            json.dump(asdict(exp), f, indent=2, ensure_ascii=False)
    
    def _load_experiment(self, exp_id: str) -> Experiment | None:
        """Load experiment from disk."""
        path = self._dir / f"{exp_id}.json"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                data = json.load(f)
            exp = Experiment(**{
                k: v for k, v in data.items()
                if k in Experiment.__dataclass_fields__
            })
            exp.runs = [RunResult(**r) for r in data.get("runs", [])]
            return exp
        except Exception:
            return None
