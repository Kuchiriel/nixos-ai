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
    cores_perf: int = 0   # P-cores (hyperthread) — o alvo de -t
    cores_eff: int = 0    # E-cores (sem hyperthread)
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
    layers_total: int = 0
    threads: int = 4
    context_size: int = 4096
    batch_size: int = 512
    ubatch_size: int = 256
    cpu_moe: int = 0
    kv_cache_type: str = "f16"
    mlock: bool = False
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
                def _num(txt: str) -> float | None:
                    """nvidia-smi devolve '[N/A]' em notebook (ex.: power.limit
                    em GPU laptop). float('[N/A]') CRASHAVA a deteccao inteira
                    neste hardware (25/09) — agora vira None."""
                    t = txt.strip()
                    try:
                        return float(t)
                    except ValueError:
                        return None

                hw.gpu.name = parts[0].strip()
                v = _num(parts[1]); hw.gpu.vram_mb = int(v) if v else 0
                hw.gpu.driver = parts[2].strip()
                hw.gpu.compute_capability = parts[3].strip()
                v = _num(parts[4]); hw.gpu.power_limit_w = int(v) if v else 0
                v = _num(parts[5]); hw.gpu.temperature_c = int(v) if v else 0
                v = _num(parts[6]); hw.gpu.utilization_pct = int(v) if v else 0

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
        # P-cores vs E-cores. Dois erros ja vistos aqui: (a) thread_siblings_list
        # usa FAIXAS ("0-1"), entao split(',') da 1 para todo mundo; (b) cada
        # P-core aparece em DUAS entradas (cpu0 e cpu1 tem o mesmo sibling list),
        # entao contar por CPU da 12 em vez de 6. Aqui conta por GRUPO unico.
        # Medido 25/09 no i7-13620H: 6P+4E = 10 fisicos, e o lscpu reporta
        # "8". O alvo do -t sao os P-cores: -t6=16,4 | -t8=14,1 | -t10=10,4.
        try:
            cbase = Path("/sys/devices/system/cpu")
            grupos: dict[str, int] = {}
            for cp in cbase.glob("cpu[0-9]*"):
                sibf = cp / "topology" / "thread_siblings_list"
                if not sibf.exists():
                    continue
                txt = sibf.read_text().strip()
                if not txt:
                    continue
                n = 0
                for parte in txt.split(","):
                    parte = parte.strip()
                    if "-" in parte:
                        a, _, b = parte.partition("-")
                        try:
                            n += int(b) - int(a) + 1
                        except ValueError:
                            n += 1
                    elif parte:
                        n += 1
                grupos[txt] = n
            perf = sum(n // 2 for n in grupos.values() if n >= 2)
            eff = sum(1 for n in grupos.values() if n < 2)
            if perf:
                hw.cpu.cores_perf = perf
                hw.cpu.cores_eff = eff
        except Exception:
            pass
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
    # params(B) x bytes/param = bytes; /1e9 = GB. A versao anterior dividia
    # por 8 DEPOIS de ja converter para bytes, ou seja, 8x menor: um 35B
    # Q4_K_M (20GB em disco) aparecia como 2,8GB e cabia "facilmente" na
    # VRAM. Isso e a raiz do erro de fit — e do config 2,7x mais lento.
    model_size_gb = model_size_b * quant_multiplier

    # MoE: TODO expert tem que estar residente em ALGUM lugar (GPU ou RAM),
    # porque o router pode escolher qualquer um no proximo token. Entao o
    # FIT e decidido pelo TAMANHO TOTAL do arquivo, nunca pelos parametros
    # ATIVOS. A versao anterior usava ativos (3B x 0,55 = 1,6GB) e conclui
    # "cabe na VRAM" -> gpu_layers=99, cpu_moe=0, que e exatamente a config
    # que o sweep de 25/09 mediu como 2,7x MAIS LENTA (cmoe37=16,1 t/s).
    # Se active_params_b for informado e o total nao, sobe o total a partir
    # dele e sinaliza a uncertainties em vez de fingir que cabe.
    if model_type == "moe" and active_params_b and model_size_b < active_params_b:
        model_size_b = active_params_b * 2.0  # piso conservador p/ MoE denso-em-total
        notes.append(f"MoE: total estimado como {model_size_b:.0f}B (de active_params)")

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
    # Threads = P-CORES, nao "metade dos fisicos" nem "fisicos - 2".
    # Medido 25/09 no i7-13620H (hibrido 6P+4E=10 fisicos, e o lscpu
    # reporta "8" escondendo a assimetria):
    #   -t 6 = 16,4 | -t 8 = 14,1 | -t 10 = 10,4 | -t 12 = 7,9 t/s
    # E-cores e hyperthread competem e custam ~14%. No MoE -t 6 == -t 8
    # (bandwidth-bound), mas -t 6 e seguro nos dois casos.
    perf = hw.cpu.cores_perf or hw.cpu.cores_physical
    config.threads = max(2, perf)
    notes.append(f"{config.threads} threads (P-cores; {hw.cpu.cores_physical} fisicos"
                 + (f", {hw.cpu.cores_eff} E-cores ignorados" if hw.cpu.cores_eff else "") + ")")

    # Context size: based on available RAM after model
    remaining_ram_gb = total_budget_gb - model_size_gb
    if remaining_ram_gb > 2:
        # ~1GB per 8K context for most models
        config.context_size = min(32768, int(remaining_ram_gb * 8000))
    else:
        config.context_size = 2048
        notes.append(f"Limited context ({config.context_size}) due to memory")

    # Batch/ubatch: ALINHADO com models.nix (512/512). Antes o heuristico
    # dava 1024/256 nesta maquina, que (a) discordava do service e (b) mexia
    # na decisao de offload do ik_llama.cpp, cujo threshold e
    # 32 * total_experts/active_experts (~1024 tokens p/ 35B-A3B). Errar o
    # ubatch muda se os experts vao ou nao pela PCIe — que e exatamente o
    # comportamento bimodal (40 vs 15 t/s) que o sweep de 25/09 expôs.
    config.batch_size = 512
    config.ubatch_size = 512

    # CPU MoE layers (for MoE models)
    if model_type == "moe" and config.gpu_layers > 0:
        # Offload some MoE layers to CPU to reduce VRAM pressure
        # Direcao INVERTIDA (medido 25/09 no 35B-A3B): experts na VRAM
        # sao piores, nao melhores. Expert na GPU tem que vir pelo PCIe
        # (Gen4 x4 = 6-7 GB/s) em vez de RAM (41-83 GB/s). Curva em U
        # invertido: cmoe41 = 40,3 t/s | cmoe39 = 19,9 | cmoe37 = 16,1.
        # A heuristica antiga (gpu_layers - 20) punha experts na GPU.
        # Agora: quase tudo na CPU, e o que sobra de VRAM vai para
        # attention/dense/KV — que correm em TODOS os tokens.
        # Sem contagem de camadas conhecida, assume o PESSIM caso seguro
        # para o que medimos: quase tudo na CPU. experts na GPU afogam no
        # PCIe (sweep 25/09: cmoe37 = 16,1 t/s vs cmoe41 = 40,3). Um
        # default otimista aqui custa 2,7x; um pessimista so custa um pouco
        # de PP. models.nix usa 35 de 48.
        total = config.layers_total or 48
        config.cpu_moe = max(0, total - 1)
        if config.cpu_moe > 0:
            notes.append(f"{config.cpu_moe}/{total} MoE layers on CPU "
                         f"(experts na GPU afogam no PCIe; medido 25/09)")

    # KV cache type
    # KV: nesta maquina (6GB VRAM) a heuristica antiga escolhia q8_0, mas o
    # service roda q4_0 e foi com q4_0 que o sweep mediu 40 t/s. Alineado.
    if vram_budget_gb > 8:
        config.kv_cache_type = "q8_0"
    else:
        config.kv_cache_type = "q4_0"
    notes.append(f"KV cache {config.kv_cache_type} (alinhado com models.nix)")

    # mlock: para modelo grande em RAM, evita paginacao/zram. Medido 25/09:
    # --mlock esta nos perfis MoE do models.nix. O sweep NAO conseguiu medir
    # se estabiliza o bimodal (runs estouraram o timeout), entao aqui e
    # coerencia com o service, nao um ganho comprovado.
    config.mlock = model_size_gb > 16
    if config.mlock:
        notes.append("--mlock: pesos >16GB travados na RAM (alinhado com models.nix)")

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
    if hw.gpu.backend == "cuda" and hw.gpu.count >= 4 and hw.gpu.vram_gb >= 40:
        return "datacenter"
    if hw.gpu.backend == "cuda" and hw.gpu.count >= 2:
        return "multi-gpu"
    if hw.unified_memory_gb >= 64:
        return "apple-studio"
    if hw.gpu.backend in ("cuda", "rocm", "metal") and hw.gpu.vram_gb >= 16:
        return "workstation"
    if hw.gpu.backend in ("cuda", "rocm", "vulkan", "metal") and hw.gpu.vram_gb >= 6:
        return "gaming-laptop"
    if hw.ram_gb >= 24 and hw.cpu.threads >= 8:
        return "desktop"
    if hw.ram_gb >= 8:
        return "laptop"
    if hw.is_termux or hw.is_android or hw.ram_gb < 8:
        return "phone"
    return "unknown"


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

def memory_bandwidth_gb_s(hw: HardwareProfile) -> float:
    """Estimate memory bandwidth (GB/s) — the TG driver."""
    if hw.gpu.backend == "cuda":
        if hw.gpu.vram_gb >= 24:
            return 900.0
        if hw.gpu.vram_gb >= 12:
            return 550.0
        if hw.gpu.vram_gb >= 6:
            return 260.0
        return 120.0
    if hw.gpu.backend == "rocm":
        return 800.0 if hw.gpu.vram_gb >= 16 else 400.0
    if hw.gpu.backend == "vulkan":
        return 300.0
    if hw.unified_memory_gb >= 64:
        return 400.0
    if hw.unified_memory_gb >= 16:
        return 200.0
    if hw.is_termux or hw.is_android:
        return 25.0
    if hw.ram_gb >= 32:
        return 120.0
    if hw.ram_gb >= 16:
        return 60.0
    return 35.0
