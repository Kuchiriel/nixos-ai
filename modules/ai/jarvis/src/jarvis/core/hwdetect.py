"""Detecção de hardware do JARVIS — roda em QUALQUER plataforma.

Objetivo (visão do usuário): um sistema que roda do Termux num celular velho
até um datacenter com Teslas/TPUs/NPUs. Este módulo detecta o hardware e
classifica num perfil que alimenta `hwprofile` (cálculo das flags SOTA do
llama.cpp + escolha do melhor modelo).

Fontes (em ordem de confiabilidade, com fallback):
  - GPU NVIDIA: `nvidia-smi` (VRAM real, compute capability)
  - GPU AMD/Intel: Vulkan (`vulkaninfo`) e ROCm (`rocm-smi`)
  - Apple Silicon: `sysctl hw.*` (memória unificada = RAM "vira" VRAM)
  - NPU/TPU: /dev/accel (Linux accel), /proc/device-tree (TPU?), android
  - Termux/Android: detecção do ambiente (uname + /data/data/com.termux)
  - CPU/RAM: /proc/cpuinfo, /proc/meminfo (Linux), sysctl (macOS)

Nada aqui exige root; tudo tem fallback para "desconhecido" (o cálculo
decide com o que tem).
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CpuInfo:
    cores: int = 0
    threads: int = 0
    vendor: str = ""        # Intel | AMD | ARM | Qualcomm | MediaTek | Apple | desconhecido
    model: str = ""
    freq_ghz: float = 0.0
    arch: str = ""


@dataclass
class GpuInfo:
    name: str = ""
    vram_gb: float = 0.0
    backend: str = ""       # cuda | rocm | vulkan | metal | none
    count: int = 0
    compute_cap: str = ""   # NVIDIA ex: 8.9 (Ada)
    # múltiplas GPUs (para split/paralelo)
    vram_per_gpu_gb: list[float] = field(default_factory=list)


@dataclass
class HardwareProfile:
    cpu: CpuInfo = field(default_factory=CpuInfo)
    gpu: GpuInfo = field(default_factory=GpuInfo)
    ram_gb: float = 0.0
    unified_memory_gb: float = 0.0   # Apple Silicon / NPU (RAM "vira" VRAM)
    is_termux: bool = False
    is_android: bool = False
    is_apple_silicon: bool = False
    has_npu: bool = False
    npu_name: str = ""
    platform: str = ""               # linux | darwin | android | termux
    # iGPU Intel/AMD integrada (para offload aux: whisper/embed/TTS)
    aux_gpu_name: str = ""           # ex: "Intel UHD Graphics 770"
    aux_gpu_backend: str = ""        # "vulkan" | "openvino" | ""
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers de execução (nunca quebram)
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
        ).stdout
        return out or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _linux_ram_gb() -> float:
    try:
        for line in open("/proc/meminfo", encoding="utf-8", errors="ignore"):
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / (1024 * 1024)  # kB → GB
    except OSError:
        pass
    return 0.0


def _macos_ram_gb() -> float:
    out = _run(["sysctl", "-n", "hw.memsize"])
    try:
        return int(out.strip()) / (1024**3)
    except ValueError:
        return 0.0


def _detect_termux_android() -> tuple[bool, bool]:
    is_termux = os.path.exists("/data/data/com.termux")
    is_android = os.path.exists("/system/build.prop") or "android" in platform.platform().lower()
    return is_termux, is_android


def _is_apple_silicon() -> bool:
    if platform.system() != "Darwin":
        return False
    out = _run(["sysctl", "-n", "hw.optional.arm64"])
    return out.strip() == "1"


def detect_cpu() -> CpuInfo:
    cpu = CpuInfo()
    cpu.arch = platform.machine()
    try:
        cpu.threads = os.cpu_count() or 0
    except (OSError, NotImplementedError):
        cpu.threads = 0

    if platform.system() == "Linux":
        vendors = []
        models = []
        freqs = []
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="ignore"):
            if line.startswith("model name") or line.startswith("Hardware"):
                models.append(line.split(":", 1)[1].strip())
            elif line.startswith("vendor_id"):
                vendors.append(line.split(":", 1)[1].strip())
            elif line.startswith("cpu MHz"):
                try:
                    freqs.append(float(line.split(":", 1)[1].strip()))
                except ValueError:
                    pass
        if vendors:
            v = vendors[0].lower()
            cpu.vendor = {"genuineintel": "Intel", "authenticamd": "AMD",
                          "arm": "ARM"}.get(v, vendors[0])
        if models:
            cpu.model = models[0]
        if freqs:
            cpu.freq_ghz = round(max(freqs) / 1000.0, 2)
    elif platform.system() == "Darwin":
        cpu.model = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if "Apple" in cpu.model:
            cpu.vendor = "Apple"
        elif "Intel" in cpu.model:
            cpu.vendor = "Intel"

    # cores físicos (threads podem incluir SMT)
    try:
        if platform.system() == "Linux":
            cores = set()
            for line in open("/proc/cpuinfo", encoding="utf-8", errors="ignore"):
                if line.startswith("core id"):
                    cores.add(line.split(":", 1)[1].strip())
            cpu.cores = max(len(cores), 1) if cores else cpu.threads
        else:
            cpu.cores = cpu.threads
    except OSError:
        cpu.cores = cpu.threads
    return cpu


def detect_gpu() -> GpuInfo:
    """Detecta GPUs: nvidia-smi → rocm-smi → vulkaninfo → metal."""
    gpu = GpuInfo()

    # 1. NVIDIA (nvidia-smi)
    smi = shutil.which("nvidia-smi")
    if smi:
        out = _run([smi, "--query-gpu=name,memory.total,compute_cap",
                    "--format=csv,noheader,nounits"], timeout=8.0)
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                gpu.count += 1
                gpu.backend = "cuda"
                if gpu.name == "":
                    gpu.name = parts[0]
                try:
                    vram_mib = float(parts[1])
                    gpu.vram_per_gpu_gb.append(round(vram_mib / 1024.0, 2))
                except ValueError:
                    pass
                if len(parts) >= 3:
                    gpu.compute_cap = parts[2]
        if gpu.count:
            gpu.vram_gb = max(gpu.vram_per_gpu_gb) if gpu.vram_per_gpu_gb else 0.0

    # 2. AMD ROCm
    if gpu.count == 0 and shutil.which("rocm-smi"):
        out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram"], timeout=8.0)
        if out.strip():
            gpu.count = 1
            gpu.backend = "rocm"
            gpu.name = "AMD (ROCm)"
            m = re.search(r"(\d+)MB", out)
            if m:
                gpu.vram_gb = round(int(m.group(1)) / 1024.0, 2)
                gpu.vram_per_gpu_gb = [gpu.vram_gb]

    # 3. Vulkan (AMD/Intel/NVIDIA genérico)
    if gpu.count == 0 and shutil.which("vulkaninfo"):
        out = _run(["vulkaninfo", "--summary"], timeout=8.0)
        # conta deviceName e heap de memória local
        names = re.findall(r"deviceName\s*=\s*(.+)", out)
        if names:
            gpu.count = len(set(names))
            gpu.name = names[0].strip()
            if gpu.backend == "":
                gpu.backend = "vulkan"
            mems = re.findall(r"memoryHeaps\[0\][^=]*=\s*(\d+)", out)
            if mems:
                gpu.vram_per_gpu_gb = [round(int(m) / (1024**3), 2) for m in mems]
                gpu.vram_gb = max(gpu.vram_per_gpu_gb) if gpu.vram_per_gpu_gb else 0.0

    # 4. macOS Metal (memória unificada — tratada em detect())
    return gpu


def detect_npu() -> tuple[bool, str]:
    """Detecta NPU/TPU (Linux accel, Android NNAPI, Intel NPU)."""
    if os.path.exists("/dev/accel0") or os.path.exists("/dev/accel/accel0"):
        # Intel NPU / Linux accel (4.15+ ABI)
        try:
            uevent = open("/sys/class/accel/accel0/device/uevent", encoding="utf-8",
                          errors="ignore").read()
            name = re.search(r"DRIVER=(.+)", uevent)
            return True, (name.group(1) if name else "Linux accel")
        except OSError:
            return True, "Linux accel"
    if os.path.exists("/proc/device-tree/npu") or os.path.exists("/proc/device-tree/iva"):
        return True, "NPU (device-tree)"
    # Android: NNAPI está sempre disponível via runtime — detecta pelo build
    if os.path.exists("/system/build.prop"):
        return True, "Android NNAPI"
    return False, ""


def _detect_aux_gpu() -> str:
    """Detecta GPU integrada (Intel UHD/Arc, AMD iGPU) — lspci, rápido e leve.

    No host (Acer Nitro V15): "Intel Corporation Raptor Lake-S GT1 [UHD
    Graphics 770]" — iGPU fraca mas útil para whisper STT via SYCL/OpenVINO
    (12x boost confirmado, whisper.cpp 1.8.3), sem competir com a VRAM da
    RTX 4050. No lab: nada (VM sem iGPU).
    """
    if platform.system() != "Linux":
        return ""
    try:
        out = _run(["lspci"], timeout=5.0)
        for line in out.splitlines():
            ll = line.lower()
            if ("intel" in ll or "amd" in ll) and ("vga" in ll or "display" in ll or "3d" in ll):
                # "... VGA compatible controller: Intel Corporation Raptor Lake-S GT1 [UHD Graphics 770]"
                name = line.split(":", 2)[-1].strip() if line.count(":") >= 2 else line.strip()
                return name
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def detect() -> HardwareProfile:
    """Detecta o hardware completo da máquina atual."""
    hw = HardwareProfile()
    hw.platform = platform.system().lower()  # linux | darwin
    hw.cpu = detect_cpu()
    hw.gpu = detect_gpu()
    hw.is_termux, hw.is_android = _detect_termux_android()
    hw.is_apple_silicon = _is_apple_silicon()
    hw.has_npu, hw.npu_name = detect_npu()
    hw.aux_gpu_name = _detect_aux_gpu()

    if hw.is_termux or hw.is_android:
        hw.platform = "termux" if hw.is_termux else "android"
        # RAM via /proc/meminfo (Android/Termux expõem)
        hw.ram_gb = _linux_ram_gb()
    elif hw.platform == "darwin":
        hw.ram_gb = _macos_ram_gb()
        if hw.is_apple_silicon:
            # memória unificada: Apple Silicon "vira VRAM" (Metal)
            hw.unified_memory_gb = hw.ram_gb
    else:
        hw.ram_gb = _linux_ram_gb()

    hw.raw = {
        "platform": hw.platform,
        "python": platform.python_version(),
        "uname": platform.uname().release,
    }
    return hw


def classify(hw: HardwareProfile) -> str:
    """Classifica o hardware num tier — de celular velho a datacenter.

    RAM efetiva = RAM + memória unificada (Apple/NPU); VRAM efetiva = VRAM
    da GPU (ou a unificada, no Metal — a memória "vira" VRAM).
    """
    ram = hw.ram_gb + hw.unified_memory_gb
    vram = hw.gpu.vram_gb
    if hw.gpu.backend == "metal" and vram == 0:
        vram = hw.unified_memory_gb   # Apple Silicon: RAM vira VRAM
    if hw.gpu.backend == "cuda" and hw.gpu.count >= 4 and vram >= 40:
        return "datacenter"        # multi-Tesla/H100/A100
    if hw.gpu.backend == "cuda" and hw.gpu.count >= 2:
        return "multi-gpu"         # 2+ GPUs (split/paralelo)
    if hw.unified_memory_gb >= 64:
        return "apple-studio"      # Apple Silicon grande (128GB = VRAM)
    if hw.gpu.backend in ("cuda", "rocm", "metal") and vram >= 16:
        return "workstation"
    if hw.gpu.backend in ("cuda", "rocm", "vulkan", "metal") and vram >= 6:
        return "gaming-laptop"     # ex: RTX 4050 6GB (nosso host alvo!)
    if ram >= 24 and hw.cpu.threads >= 8:
        return "desktop"           # CPU-only forte (MoE offload)
    if ram >= 8:
        return "laptop"            # CPU-only leve
    if hw.is_termux or hw.is_android or ram < 8:
        return "phone"             # Termux / celular (Q4 pequeno)
    return "unknown"


def memory_bandwidth_gb_s(hw: HardwareProfile) -> float:
    """Estimativa da largura de banda de memória (GB/s) — o driver do TG.

    Heurísticas (do guia de otimização + specs típicas):
      - NVIDIA com VRAM >= 12GB: ~600-1000 GB/s (GDDR6)
      - NVIDIA 6-12GB: ~250-400 GB/s (RTX 4050 laptop ≈ 256 GB/s)
      - Apple Silicon unificado: 200-400 GB/s
      - CPU RAM: ~50-200 GB/s (depende de canais/DDR)
      - Termux/celular: ~20-40 GB/s (LPDDR)
    """
    if hw.gpu.backend == "cuda":
        if hw.gpu.vram_gb >= 24:
            return 900.0
        if hw.gpu.vram_gb >= 12:
            return 550.0
        if hw.gpu.vram_gb >= 6:
            return 260.0          # RTX 4050 laptop ≈ 256 GB/s
        return 120.0
    if hw.gpu.backend == "rocm":
        return 800.0 if hw.gpu.vram_gb >= 16 else 400.0
    if hw.gpu.backend == "vulkan":
        return 300.0
    if hw.unified_memory_gb >= 64:
        return 400.0              # M3 Max / M4
    if hw.unified_memory_gb >= 16:
        return 200.0
    if hw.is_termux or hw.is_android:
        return 25.0
    if hw.ram_gb >= 32:
        return 120.0              # DDR5 dual-channel
    if hw.ram_gb >= 16:
        return 60.0
    return 35.0
