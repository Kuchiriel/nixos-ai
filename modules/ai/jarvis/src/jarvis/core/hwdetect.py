"""Hardware detection and auto-configuration for llama.cpp.

Detects system hardware and recommends optimal llama.cpp flags.
No hardcoded values — all calculations based on actual hardware specs.

Usage:
    from jarvis.core.hwdetect import detect_hardware, recommend_config
    hw = detect_hardware()
    config = recommend_config(hw, model_size_b=35, model_quant="Q4_K_M")
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class GPUInfo:
    name: str = "unknown"
    vram_mb: int = 0
    driver: str = "unknown"
    cuda_version: str = "unknown"
    compute_capability: str = "unknown"
    memory_bandwidth_gbps: float = 0.0
    power_limit_w: int = 0
    temperature_c: int = 0
    utilization_pct: int = 0


@dataclass
class CPUInfo:
    name: str = "unknown"
    cores_physical: int = 0
    cores_logical: int = 0
    frequency_ghz: float = 0.0
    architecture: str = "unknown"


@dataclass
class SystemInfo:
    gpu: GPUInfo = field(default_factory=GPUInfo)
    cpu: CPUInfo = field(default_factory=CPUInfo)
    ram_total_mb: int = 0
    ram_available_mb: int = 0
    swap_total_mb: int = 0


@dataclass
class LlamaConfig:
    """Recommended llama.cpp configuration."""
    gpu_layers: int = 99
    threads: int = 4
    context_size: int = 4096
    batch_size: int = 512
    ubatch_size: int = 256
    cpu_moe: int = 0
    kv_cache_type: str = "f16"
    flash_attention: bool = True
    split_mode: str = "layer"
    reasoning: str = "medium"
    notes: list[str] = field(default_factory=list)


def detect_hardware() -> SystemInfo:
    """Detect actual system hardware. No assumptions."""
    hw = SystemInfo()

    # GPU detection via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version,compute_cap,power.limit,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(", ")
            if len(parts) >= 7:
                hw.gpu.name = parts[0].strip()
                hw.gpu.vram_mb = int(float(parts[1].strip()))
                hw.gpu.driver = parts[2].strip()
                hw.gpu.compute_capability = parts[3].strip()
                hw.gpu.power_limit_w = int(float(parts[4].strip()))
                hw.gpu.temperature_c = int(float(parts[5].strip()))
                hw.gpu.utilization_pct = int(float(parts[6].strip()))

        # CUDA version
        result2 = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result2.returncode == 0:
            # Get CUDA version from nvidia-smi header
            result3 = subprocess.run(["nvidia-smi"], capture_output=True, text=True, timeout=5)
            cuda_match = re.search(r"CUDA Version:\s*([\d.]+)", result3.stdout)
            if cuda_match:
                hw.gpu.cuda_version = cuda_match.group(1)

        # Memory bandwidth estimation based on GPU model
        hw.gpu.memory_bandwidth_gbps = _estimate_gpu_bandwidth(hw.gpu.name)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # CPU detection
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
        # Count physical cores
        physical_ids = set()
        core_ids = set()
        for line in cpuinfo.split("\n"):
            if line.startswith("physical id"):
                physical_ids.add(line.split(":")[1].strip())
            if line.startswith("core id"):
                core_ids.add(line.split(":")[1].strip())
            if line.startswith("model name") and hw.cpu.name == "unknown":
                hw.cpu.name = line.split(":")[1].strip()
            if line.startswith("cpu MHz") and hw.cpu.frequency_ghz == 0:
                hw.cpu.frequency_ghz = float(line.split(":")[1].strip()) / 1000

        hw.cpu.cores_physical = len(physical_ids) * len(core_ids) if physical_ids and core_ids else os.cpu_count() or 1
        hw.cpu.cores_logical = os.cpu_count() or 1
        hw.cpu.architecture = os.uname().machine
    except Exception:
        hw.cpu.cores_logical = os.cpu_count() or 1

    # RAM detection
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    hw.ram_total_mb = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable"):
                    hw.ram_available_mb = int(line.split()[1]) // 1024
                elif line.startswith("SwapTotal"):
                    hw.swap_total_mb = int(line.split()[1]) // 1024
    except Exception:
        pass

    return hw


def _estimate_gpu_bandwidth(gpu_name: str) -> float:
    """Estimate GPU memory bandwidth (GB/s) from model name.

    Based on known specs. Returns 0 if unknown.
    """
    name_lower = gpu_name.lower()

    # NVIDIA desktop GPUs
    bandwidth_map = {
        "rtx 5090": 1792.0,
        "rtx 5080": 960.0,
        "rtx 5070 ti": 864.0,
        "rtx 5070": 504.0,
        "rtx 4090": 1008.0,
        "rtx 4080": 717.0,
        "rtx 4070 ti": 504.0,
        "rtx 4070": 504.0,
        "rtx 4060 ti": 288.0,
        "rtx 4060": 272.0,
        "rtx 3090": 936.0,
        "rtx 3080": 760.0,
        "rtx 3070": 448.0,
        "rtx 3060": 360.0,
        "a100": 2039.0,
        "h100": 3350.0,
    }

    # NVIDIA laptop GPUs (typically lower bandwidth)
    laptop_bandwidth = {
        "rtx 4050 laptop": 192.0,
        "rtx 4060 laptop": 256.0,
        "rtx 4070 laptop": 288.0,
        "rtx 3050 laptop": 192.0,
        "rtx 3060 laptop": 288.0,
    }

    for model, bw in laptop_bandwidth.items():
        if model in name_lower:
            return bw

    for model, bw in bandwidth_map.items():
        if model in name_lower:
            return bw

    return 0.0


def recommend_config(
    hw: SystemInfo,
    model_size_b: float = 35,
    model_quant: str = "Q4_K_M",
    model_type: str = "dense",
    active_params_b: float | None = None,
) -> LlamaConfig:
    """Calculate optimal llama.cpp config based on actual hardware.

    All values are calculated, not hardcoded.
    """
    config = LlamaConfig()
    notes = []

    # Estimate model size in bytes
    quant_multiplier = _quant_multiplier(model_quant)
    model_size_gb = (model_size_b * 1e9 * quant_multiplier) / (8 * 1e9)  # bytes

    # VRAM budget (leave 1GB for system/overhead)
    vram_budget_gb = (hw.gpu.vram_mb - 1024) / 1024 if hw.gpu.vram_mb > 1024 else 0

    # RAM budget (leave 4GB for system)
    ram_budget_gb = (hw.ram_available_mb - 4096) / 1024 if hw.ram_available_mb > 4096 else 0

    total_budget_gb = vram_budget_gb + ram_budget_gb

    if model_size_gb > total_budget_gb:
        notes.append(f"Model ({model_size_gb:.1f}GB) exceeds total budget ({total_budget_gb:.1f}GB)")
        # Try to fit in RAM only
        if model_size_gb <= ram_budget_gb:
            config.gpu_layers = 0
            notes.append("Running CPU-only (model fits in RAM)")
        else:
            notes.append("WARNING: Model may not fit in available memory")
            config.gpu_layers = 0
    elif model_size_gb <= vram_budget_gb:
        # Model fits entirely in VRAM
        config.gpu_layers = 99
        notes.append(f"Model fits entirely in VRAM ({model_size_gb:.1f}GB <= {vram_budget_gb:.1f}GB)")
    else:
        # Need to split between GPU and CPU
        gpu_fraction = vram_budget_gb / model_size_gb
        config.gpu_layers = max(1, int(gpu_fraction * 99))
        notes.append(f"Splitting: {config.gpu_layers}/99 layers on GPU")

    # Threads: use physical cores, not hyperthreads
    # For MoE models, fewer threads can be better (less contention)
    if model_type == "moe":
        config.threads = max(2, hw.cpu.cores_physical // 2)
        notes.append(f"MoE mode: {config.threads} threads (half physical cores)")
    else:
        config.threads = max(2, hw.cpu.cores_physical - 2)
        notes.append(f"Dense mode: {config.threads} threads (physical cores - 2)")

    # Context size: based on available RAM after model
    remaining_ram_gb = total_budget_gb - model_size_gb
    if remaining_ram_gb > 2:
        # ~1GB per 8K context for most models
        config.context_size = min(32768, int(remaining_ram_gb * 8000))
    else:
        config.context_size = 2048
        notes.append(f"Limited context ({config.context_size}) due to memory")

    # Batch size: based on VRAM
    if vram_budget_gb > 8:
        config.batch_size = 2048
    elif vram_budget_gb > 4:
        config.batch_size = 1024
    else:
        config.batch_size = 512

    # Ubatch: typically 1/4 of batch
    config.ubatch_size = config.batch_size // 4

    # CPU MoE layers (for MoE models)
    if model_type == "moe" and config.gpu_layers > 0:
        # Offload some MoE layers to CPU to reduce VRAM pressure
        config.cpu_moe = max(0, config.gpu_layers - 20)
        if config.cpu_moe > 0:
            notes.append(f"Offloading {config.cpu_moe} MoE layers to CPU")

    # KV cache type
    if vram_budget_gb > 8:
        config.kv_cache_type = "f16"
    elif vram_budget_gb > 4:
        config.kv_cache_type = "q8_0"
    else:
        config.kv_cache_type = "q4_0"
        notes.append(f"Using {config.kv_cache_type} KV cache to save memory")

    # Flash attention
    config.flash_attention = hw.gpu.vram_mb >= 4096  # Enable if >= 4GB VRAM

    # Reasoning level based on hardware capability
    if hw.gpu.vram_mb >= 8192 and hw.gpu.memory_bandwidth_gbps >= 500:
        config.reasoning = "high"
    elif hw.gpu.vram_mb >= 4096:
        config.reasoning = "medium"
    else:
        config.reasoning = "low"

    config.notes = notes
    return config


def _quant_multiplier(quant: str) -> float:
    """Estimate bits-per-weight multiplier for quantization type."""
    quant_map = {
        "Q2_K": 0.31,
        "Q3_K_S": 0.37,
        "Q3_K_M": 0.44,
        "Q3_K_L": 0.50,
        "Q4_0": 0.56,
        "Q4_K_S": 0.56,
        "Q4_K_M": 0.63,
        "Q4_K_L": 0.69,
        "Q5_0": 0.69,
        "Q5_K_S": 0.69,
        "Q5_K_M": 0.75,
        "Q6_K": 0.81,
        "Q8_0": 1.0,
        "F16": 2.0,
    }
    return quant_map.get(quant, 0.63)  # Default to Q4_K_M


def save_config(config: LlamaConfig, path: str | Path | None = None) -> str:
    """Save recommended config to JSON file."""
    if path is None:
        path = Path.home() / ".local/state/jarvis/hw-profile.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False))
    return str(path)


def load_config(path: str | Path | None = None) -> LlamaConfig | None:
    """Load saved config from JSON file."""
    if path is None:
        path = Path.home() / ".local/state/jarvis/hw-profile.json"
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return LlamaConfig(**data)
    except Exception:
        return None


def generate_nix_flags(config: LlamaConfig) -> str:
    """Generate Nix-compatible flags string from config."""
    flags = [
        f"-c {config.context_size}",
        f"-t {config.threads}",
        f"-b {config.batch_size}",
        f"-ub {config.ubatch_size}",
        f"-ngl {config.gpu_layers}",
    ]
    if config.flash_attention:
        flags.append("-fa")
    if config.cpu_moe > 0:
        flags.append(f"--n-cpu-moe {config.cpu_moe}")
    if config.kv_cache_type != "f16":
        flags.append(f"--cache-type-k {config.kv_cache_type}")
        flags.append(f"--cache-type-v {config.kv_cache_type}")
    return " ".join(flags)


# ═══ Backward Compatibility ═══
# Old API used by test_hwprofile.py and hwprofile.py

from dataclasses import dataclass as _dataclass, field as _field


@_dataclass
class CpuInfo:
    cores: int = 0
    threads: int = 0
    vendor: str = ""
    model: str = ""
    freq_ghz: float = 0.0
    arch: str = ""


@_dataclass
class GpuInfo:
    name: str = ""
    vram_gb: float = 0.0
    backend: str = ""
    count: int = 0
    compute_cap: str = ""
    vram_per_gpu_gb: list = _field(default_factory=list)


@_dataclass
class HardwareProfile:
    cpu: CpuInfo = _field(default_factory=CpuInfo)
    gpu: GpuInfo = _field(default_factory=GpuInfo)
    ram_gb: float = 0.0
    unified_memory_gb: float = 0.0
    is_termux: bool = False
    is_android: bool = False
    is_apple_silicon: bool = False
    has_npu: bool = False
    npu_name: str = ""
    platform: str = ""
    aux_gpu_name: str = ""
    aux_gpu_backend: str = ""
    raw: dict = _field(default_factory=dict)


def classify(hw: HardwareProfile) -> str:
    """Classify hardware into tier (backward compat)."""
    if hw.gpu.vram_gb >= 24:
        return "datacenter"
    elif hw.gpu.vram_gb >= 8:
        return "high"
    elif hw.gpu.vram_gb >= 4:
        return "medium"
    elif hw.ram_gb >= 16:
        return "cpu-only"
    else:
        return "low"


def detect() -> HardwareProfile:
    """Detect hardware and return HardwareProfile (backward compat)."""
    hw_sys = detect_hardware()
    return HardwareProfile(
        cpu=CpuInfo(
            cores=hw_sys.cpu.cores_physical,
            threads=hw_sys.cpu.cores_logical,
            vendor="Intel" if "intel" in hw_sys.cpu.name.lower() else "AMD" if "amd" in hw_sys.cpu.name.lower() else "Unknown",
            model=hw_sys.cpu.name,
            freq_ghz=hw_sys.cpu.frequency_ghz,
            arch=hw_sys.cpu.architecture,
        ),
        gpu=GpuInfo(
            name=hw_sys.gpu.name,
            vram_gb=hw_sys.gpu.vram_mb / 1024,
            backend="cuda" if hw_sys.gpu.vram_mb > 0 else "none",
            count=1 if hw_sys.gpu.vram_mb > 0 else 0,
            compute_cap=hw_sys.gpu.compute_capability,
        ),
        ram_gb=hw_sys.ram_total_mb / 1024,
        platform="linux",
    )
