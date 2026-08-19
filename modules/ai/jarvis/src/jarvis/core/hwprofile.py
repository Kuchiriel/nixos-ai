"""Perfil de hardware → flags SOTA do llama.cpp + melhor modelo.

Visão do usuário: um sistema que roda em QUALQUER hardware — do Termux num
celular velho a um datacenter com Teslas/TPUs/NPUs. O fluxo é:

    1. `hwdetect.detect()`   — hardware real (RAM, VRAM, CPU, GPU, NPU...)
    2. `hwprofile.pick_model()` — melhor modelo do catálogo para esse hardware
    3. `hwprofile.derive_flags()` — matemática → flags SOTA do llama-server
    4. `hwprofile.build_command()` — argv pronto para execução

A matemática (fórmulas reais do llama.cpp):

    KV cache bytes/token = 2 (K+V) × n_kv_heads × head_dim × n_layers × bytes
        (bytes: 2 = f16, 1 = q8_0; fonte: docs do llama.cpp + código)

    Peso de atenção por camada (projeções q/k/v/o):
        attn_params = 2 × hidden × (hidden + n_kv_heads × head_dim)

    Modelo GGUF ≈ params_b × QUANT_BYTES[quant] (empírico; catálogo pode
    sobrepor com o tamanho real do arquivo, ex: Qwen3.6-35B UD-Q4_K_M = 20.6GiB)

Os arquivos de arquitetura (layers, kv_heads, head_dim, hidden) foram obtidos
dos config.json oficiais no HuggingFace (ago/2026). Entradas marcadas
`approx=True` são estimativas — confirme no HF antes de usar em produção.

Saída útil para o NixOS: `render_models_nix(flags, model)` emite o bloco
`profiles.<nome>` pronto para colar em modules/ai/models.nix — o cálculo
dinâmico vira declaração (princípio NixOS: calcular uma vez, declarar sempre).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.hwdetect import HardwareProfile, classify

GB = 2**30

# Bytes por parâmetro por quantização GGUF (empírico, K-quants modernos)
QUANT_BYTES: dict[str, float] = {
    "Q2_K": 0.35, "Q3_K_M": 0.45, "Q4_0": 0.55, "Q4_K_M": 0.62,
    "Q5_K_M": 0.72, "Q6_K": 0.82, "Q8_0": 1.02, "F16": 2.0,
}

# Bytes por elemento do KV cache (llama.cpp: f16 = 2, q8_0 = 1)
KV_BYTES: dict[str, float] = {"f16": 2.0, "q8_0": 1.0}

# Folga de VRAM para buffers de computação, mmproj (visão) e runtime
VRAM_OVERHEAD_GB = 0.6
# Folga de RAM para o sistema operacional e serviços
RAM_OVERHEAD_GB = 1.5

# Eficiência real vs. largura de banda teórica (calibrada com relatos reais:
# Qwen3.6-35B offload ≈ 30 tps em 6GB/32GB; Qwen3-4B CPU ≈ 5-10 tps na VM)
EFF_FULL_GPU = 0.60
EFF_CPU = 0.45
EFF_MOE_OFFLOAD = 0.15


# ---------------------------------------------------------------------------
# Catálogo de modelos (arquitetura real dos config.json oficiais, ago/2026)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    params_b: float            # parâmetros totais (bilhões)
    layers: int
    kv_heads: int
    head_dim: int
    hidden: int
    ctx_max: int               # contexto nativo do modelo (tokens)
    moe: bool = False
    active_params_b: float | None = None   # MoE: parâmetros ativos por token
    routed_experts: int = 0    # MoE: experts roteados por camada
    shared_experts: int = 0    # MoE: experts compartilhados por camada
    vision: bool = False       # multimodal (mmproj / encoder)
    size_gb: float | None = None  # tamanho GGUF real (override da fórmula)
    quant: str = "Q4_K_M"
    min_ram_gb: float = 0.0    # RAM mínima (modelo + KV + folga)
    approx: bool = False       # arquitetura estimada (não do config oficial)
    note: str = ""


MODELS: list[ModelSpec] = [
    ModelSpec(
        key="qwen3-1.7b", name="Qwen3-1.7B (Q4_K_M)",
        params_b=1.7, layers=28, kv_heads=8, head_dim=128, hidden=2048,
        ctx_max=40960, min_ram_gb=4, note="SLM de bolso — Termux/celular",
    ),
    ModelSpec(
        key="qwen3-4b", name="Qwen3-4B (Q4_K_M)",
        params_b=4.0, layers=36, kv_heads=8, head_dim=128, hidden=2560,
        ctx_max=40960, size_gb=2.5, min_ram_gb=6,
        note="Lab/CPU: tool calling nativo via --jinja (o que o lab usa hoje)",
    ),
    ModelSpec(
        key="qwen3-8b", name="Qwen3-8B (Q4_K_M)",
        params_b=8.0, layers=36, kv_heads=8, head_dim=128, hidden=4096,
        ctx_max=40960, size_gb=5.2, min_ram_gb=10,
        note="Desktop CPU-only forte",
    ),
    ModelSpec(
        key="qwen3.6-27b", name="Qwen3.6-27B (Q4_K_M)",
        params_b=27.0, layers=64, kv_heads=4, head_dim=256, hidden=5120,
        ctx_max=32768, size_gb=16.7, min_ram_gb=24,
        note="Denso grande — workstation CPU ou GPU ≥ 24GB",
    ),
    ModelSpec(
        key="qwen3.6-35b-a3b", name="Qwen3.6-35B-A3B MoE + vision (UD-Q4_K_M)",
        params_b=35.9, layers=40, kv_heads=2, head_dim=256, hidden=4096,
        ctx_max=262144, moe=True, active_params_b=3.0, routed_experts=8,
        shared_experts=2, vision=True, size_gb=20.6, quant="Q4_K_M",
        min_ram_gb=28,
        note="O ALVO do host: 35B total/3B ativos, expert offload na RAM 32GB "
             "(atenção na GPU, experts na RAM via --n-cpu-moe). Validado por "
             "relatos reais em RTX 4050 6GB (~30 tps).",
    ),
    ModelSpec(
        key="qwen3-vl-235b-a22b", name="Qwen3-VL-235B-A22B MoE + vision",
        params_b=235.0, layers=64, kv_heads=8, head_dim=128, hidden=8192,
        ctx_max=131072, moe=True, active_params_b=22.0, routed_experts=8,
        shared_experts=2, vision=True, size_gb=130.0, quant="Q4_K_M",
        min_ram_gb=160, approx=True,
        note="Datacenter multi-GPU. ARQUITETURA APROXIMADA — confirme o "
             "config.json no HF antes de usar.",
    ),
]


def by_key(key: str) -> ModelSpec:
    for m in MODELS:
        if m.key == key:
            return m
    raise KeyError(f"modelo desconhecido: {key}")


# ---------------------------------------------------------------------------
# Matemática (fórmulas do llama.cpp)
# ---------------------------------------------------------------------------

def kv_bytes_per_token(m: ModelSpec, kv: str) -> float:
    """KV cache por token (bytes): 2 (K+V) × n_kv_heads × head_dim × layers × bytes."""
    return 2.0 * m.kv_heads * m.head_dim * m.layers * KV_BYTES[kv]


def kv_cache_gb(m: ModelSpec, ctx: int, kv: str) -> float:
    return kv_bytes_per_token(m, kv) * ctx / GB


def model_size_gb(m: ModelSpec, quant: str | None = None) -> float:
    if m.size_gb is not None:
        return m.size_gb
    return m.params_b * QUANT_BYTES[quant or m.quant]


def attn_params_per_layer(m: ModelSpec) -> float:
    """Parâmetros de atenção (projeções q/k/v/o) por camada."""
    k = m.kv_heads * m.head_dim
    return 2.0 * m.hidden * (m.hidden + k) + m.hidden * k  # q,o: h² ; k,v: h·k


def moe_expert_params_per_layer(m: ModelSpec) -> float:
    """Parâmetros de UM expert MoE (rotação) por camada (unidade: parâmetros)."""
    total_experts = m.routed_experts + m.shared_experts
    if total_experts == 0:
        return 0.0
    attn_total_b = attn_params_per_layer(m) * m.layers / 1e9   # params → bilhões
    return (m.params_b - attn_total_b) / m.layers / total_experts * 1e9


def gpu_params_per_layer(m: ModelSpec, n_cpu_moe: int, quant: str) -> float:
    """Parâmetros que ficam na GPU por camada com `--n-cpu-moe N`.

    Denso: a camada inteira. MoE: atenção + shared experts + N experts
    roteados (os demais routed experts vão para a RAM via --n-cpu-moe).
    """
    if not m.moe:
        return m.params_b * 1e9 / m.layers   # parâmetros (raw)
    exp = moe_expert_params_per_layer(m)     # parâmetros (raw)
    gpu_experts = min(m.shared_experts + n_cpu_moe, m.routed_experts + m.shared_experts)
    return attn_params_per_layer(m) + gpu_experts * exp


# ---------------------------------------------------------------------------
# Seleção de modelo + derivação de flags
# ---------------------------------------------------------------------------

@dataclass
class LlamaFlags:
    model_key: str
    ngl: int                   # -ngl (camadas na GPU)
    n_cpu_moe: int             # --n-cpu-moe (experts roteados na CPU)
    ctx: int                   # -c
    kv: str                    # f16 | q8_0 (-ctk/-ctv)
    fa: bool                   # -fa on (flash attention)
    threads: int               # -t
    ubatch: int                # -ub
    split_mode: str | None     # layer | row (multi-GPU)
    offload: str               # full | expert | partial | cpu
    forecast_tps: float = 0.0
    warnings: list[str] = field(default_factory=list)
    model: ModelSpec | None = None


def pick_model(hw: HardwareProfile) -> ModelSpec:
    """Escolhe o melhor modelo do catálogo para o hardware detectado."""
    tier = classify(hw)
    ram = hw.ram_gb + hw.unified_memory_gb
    vram = hw.gpu.vram_gb
    has_gpu = hw.gpu.backend != "" and vram > 0

    if tier == "datacenter":
        return by_key("qwen3-vl-235b-a22b")
    if tier == "multi-gpu":
        return by_key("qwen3.6-35b-a3b")
    if tier in ("workstation", "gaming-laptop", "apple-studio"):
        # host alvo: RTX 4050 6GB + 32GB RAM → MoE com vision + expert offload
        if ram >= 28:
            return by_key("qwen3.6-35b-a3b")
        if ram >= 24:
            return by_key("qwen3.6-27b")
        if ram >= 10:
            return by_key("qwen3-8b")
        return by_key("qwen3-4b")
    if tier == "desktop":
        if ram >= 24:
            return by_key("qwen3.6-27b")
        if ram >= 10:
            return by_key("qwen3-8b")
        return by_key("qwen3-4b")
    if tier in ("laptop", "phone"):
        if ram >= 10:
            return by_key("qwen3-4b")
        if ram >= 6:
            return by_key("qwen3-4b") if not hw.is_termux else by_key("qwen3-1.7b")
        return by_key("qwen3-1.7b")
    # unknown → conservador
    return by_key("qwen3-4b") if ram >= 6 else by_key("qwen3-1.7b")


def derive_flags(
    hw: HardwareProfile,
    model: ModelSpec | None = None,
    ctx_target: int | None = None,
    quant: str | None = None,
) -> LlamaFlags:
    """Deriva as flags SOTA do llama-server para o hardware + modelo.

    Decisões (em ordem):
      1. contexto: maior que cabe na RAM (modelo + KV + folga), ≤ ctx nativo
      2. quant do KV: f16 se a GPU cabe o modelo inteiro + KV; senão q8_0
      3. offload: full (tudo na GPU) | expert (MoE: atenção GPU, experts RAM)
         | partial (denso, camadas que cabem) | cpu (sem GPU)
      4. threads/ubatch por cenário; -fa on com GPU (todos os backends SOTA)
      5. split-mode para múltiplas GPUs (layer p/ denso, row p/ MoE)
    """
    model = model or pick_model(hw)
    quant = quant or model.quant
    ram = hw.ram_gb + hw.unified_memory_gb
    vram = hw.gpu.vram_gb
    if hw.gpu.backend == "metal" and vram == 0:
        vram = hw.unified_memory_gb   # Apple: RAM vira VRAM
    backend = hw.gpu.backend
    warnings: list[str] = []

    if model.approx:
        warnings.append(
            f"arquitetura de {model.key} é APROXIMADA — confirme o config.json "
            "no HF antes de produção"
        )

    size_gb = model_size_gb(model, quant)

    # ── 1. Contexto (tokens) ──────────────────────────────────────────────
    f16_per_tok = kv_bytes_per_token(model, "f16")
    target = min(model.ctx_max, ctx_target or 32768)
    if ram > size_gb + RAM_OVERHEAD_GB and f16_per_tok > 0:
        ctx_by_ram = int((ram - size_gb - RAM_OVERHEAD_GB) * GB / f16_per_tok)
    else:
        ctx_by_ram = 0
    ctx = max(2048, min(target, ctx_by_ram))
    if ctx < target:
        warnings.append(
            f"contexto limitado pela RAM: {ctx:,} (alvo {target:,}) — "
            f"o modelo pede {size_gb:.1f}GB e a RAM tem {ram:.1f}GB"
        )

    # ── 2. Offload + KV quant ─────────────────────────────────────────────
    threads = max(1, hw.cpu.threads or 1)
    fa = backend in ("cuda", "rocm", "metal", "vulkan")
    split_mode: str | None = None
    if hw.gpu.count > 1:
        split_mode = "row" if model.moe else "layer"

    kv = "f16"
    if backend and vram > 0:
        # multi-GPU: o modelo se distribui entre todas (split-mode layer|row)
        total_vram = vram * hw.gpu.count if hw.gpu.count > 1 else vram
        headroom = total_vram - VRAM_OVERHEAD_GB
        kv_f16_gb = kv_cache_gb(model, ctx, "f16")
        if headroom >= size_gb + kv_f16_gb + 0.5:
            offload = "full"
            ngl = model.layers
            n_cpu_moe = 0
        elif model.moe:
            # Expert offload: atenção na GPU, experts roteados na RAM
            offload = "expert"
            kv = "q8_0" if headroom < size_gb + kv_cache_gb(model, ctx, "f16") + 1.0 else "f16"
            kv_gb = kv_cache_gb(model, ctx, kv)
            # n-cpu-moe: quantos experts roteados por camada cabem na GPU
            n_cpu_moe = 2
            while n_cpu_moe < model.routed_experts:
                per_layer = gpu_params_per_layer(model, n_cpu_moe, quant)
                ngl = int((headroom - kv_gb) / (per_layer * QUANT_BYTES[quant] / 1e9))
                if ngl >= model.layers:
                    break
                if ngl >= 1:
                    break
                n_cpu_moe += 2  # reduz carga por camada até algo caber
            per_layer = gpu_params_per_layer(model, n_cpu_moe, quant)
            gb_per_layer = per_layer * QUANT_BYTES[quant] / 1e9
            ngl = max(1, min(model.layers, int((headroom - kv_gb) / gb_per_layer)))
            warnings.append(
                f"expert offload: atenção na GPU ({ngl}/{model.layers} camadas), "
                f"{model.routed_experts - n_cpu_moe} experts roteados por camada "
                f"na RAM ({ram:.0f}GB) — VRAM {vram:.0f}GB preservada"
            )
        else:
            # Denso parcial: camadas que cabem na VRAM
            offload = "partial"
            kv = "q8_0" if headroom < size_gb + kv_cache_gb(model, ctx, "f16") + 1.0 else "f16"
            kv_gb = kv_cache_gb(model, ctx, kv)
            gb_per_layer = size_gb / model.layers
            ngl = max(1, min(model.layers, int((headroom - kv_gb) / gb_per_layer)))
            n_cpu_moe = 0
            if ngl < model.layers:
                warnings.append(
                    f"offload parcial: {ngl}/{model.layers} camadas na GPU "
                    f"({ngl * gb_per_layer:.1f}GB), resto na RAM"
                )
    else:
        offload = "cpu"
        ngl = 0
        n_cpu_moe = 0
        kv = "f16"  # sem GPU, q8 não compensa (CPU lê KV desquantizado)
        if model.moe and ram >= size_gb + RAM_OVERHEAD_GB:
            warnings.append(
                "MoE em CPU puro: use --n-cpu-moe 0 (padrão) — todos os experts "
                "na RAM; considere um denso menor para mais t/s"
            )

    # ── 3. Forecast de t/s (largura de banda → tokens) ────────────────────
    from jarvis.core.hwdetect import memory_bandwidth_gb_s
    bw = memory_bandwidth_gb_s(hw)
    forecast = _forecast_tps(hw, model, offload, n_cpu_moe, bw, quant)

    ubatch = 1024 if offload != "cpu" else 512

    return LlamaFlags(
        model_key=model.key, ngl=ngl, n_cpu_moe=n_cpu_moe, ctx=ctx, kv=kv,
        fa=fa, threads=threads, ubatch=ubatch, split_mode=split_mode,
        offload=offload, forecast_tps=forecast, warnings=warnings, model=model,
    )


def _forecast_tps(
    hw: HardwareProfile, m: ModelSpec, offload: str, n_cpu_moe: int,
    bw: float, quant: str,
) -> float:
    """Estimativa de tokens/s: bytes por token ativo ÷ largura de banda real.

    Calibrada com relatos reais (ver constantes EFF_*):
      - full GPU:  denso ativo = modelo inteiro (bytes/token = params × quant)
      - MoE:       bytes/token = atenção + experts ativos (rotação)
      - offload:   experts roteados lidos da RAM (banda da RAM, eficiência baixa)
      - cpu:       modelo inteiro da RAM
    """
    bytes_per_param = QUANT_BYTES[quant]
    if offload == "full":
        active = m.params_b * bytes_per_param
        return max(1.0, bw * EFF_FULL_GPU / active)
    if offload == "expert":
        exp_b = moe_expert_params_per_layer(m) / 1e9            # params → bilhões
        active_ram = (m.routed_experts - n_cpu_moe) * exp_b     # experts da RAM
        active_gpu = m.active_params_b or (attn_params_per_layer(m) * m.layers / 1e9)
        active_total = active_ram + active_gpu
        return max(1.0, bw * EFF_MOE_OFFLOAD / active_total)
    if offload == "partial":
        active = m.params_b * bytes_per_param
        return max(1.0, bw * EFF_CPU / active)
    # cpu
    active = m.params_b * bytes_per_param
    return max(1.0, bw * EFF_CPU / active)


def build_command(flags: LlamaFlags, mmproj_path: str | None = None) -> list[str]:
    """Monta o argv do llama-server com as flags derivadas."""
    m = flags.model
    assert m is not None
    cmd = ["llama-server", "-m", f"<modelo: {m.key}>"]
    if mmproj_path:
        cmd += ["--mmproj", mmproj_path]
    cmd += ["--host", "0.0.0.0", "--port", "8080"]
    cmd += ["-c", str(flags.ctx), "-t", str(flags.threads), "-ub", str(flags.ubatch),
            "-ngl", str(flags.ngl)]
    cmd += ["-ctk", flags.kv, "-ctv", flags.kv]
    if flags.fa:
        cmd += ["-fa", "on"]
    if flags.n_cpu_moe:
        cmd += ["--n-cpu-moe", str(flags.n_cpu_moe)]
    if flags.split_mode:
        cmd += ["--split-mode", flags.split_mode]
    cmd += ["--jinja"]  # tool calling via chat template (Qwen3+)
    return cmd


# ---------------------------------------------------------------------------
# Renderer NixOS (cálculo dinâmico → declaração em models.nix)
# ---------------------------------------------------------------------------

def render_models_nix(flags: LlamaFlags, profile_name: str = "auto") -> str:
    """Emite o bloco `profiles.<nome>` pronto para colar em modules/ai/models.nix."""
    m = flags.model
    assert m is not None
    kv = flags.kv
    moe = f'--n-cpu-moe {flags.n_cpu_moe}' if flags.n_cpu_moe else ""
    fa = "on" if flags.fa else "off"
    lines = [f'    {profile_name} = {{', f'      model = "{m.key}";']
    if m.vision:
        lines.append('      mmproj = "llm-host-mmproj";  # vision')
    lines += [
        f'      threads = {flags.threads};',
        f'      ctxSize = {flags.ctx};',
        f'      ubatch = {flags.ubatch};',
        f'      gpuLayers = {flags.ngl};',
        f'      kvCache = "-fa {fa} -ctk {kv} -ctv {kv}";',
        f'      moeFlags = "{moe}";',
    ]
    if flags.offload != "cpu":
        lines.append('      user = "root";')
        lines.append('      scheduler = { policy = "fifo"; priority = 50; };')
    lines.append('    };')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Offload auxiliar (iGPU Intel/AMD integrada)
# ---------------------------------------------------------------------------

# Serviços auxiliares que rodam como processos separados do LLM principal
# e podem ser deslocados para iGPU via SYCL/OpenVINO.
# whisper.cpp 1.8.3: 12x boost em Intel iGPU (Phoronix, Jan/2026).
AUX_OFFLOAD_SERVICES: dict[str, dict[str, str]] = {
    "whisper": {
        "service": "llama-cpp-stt",
        "desc": "STT (whisper.cpp) — 12x boost via SYCL/OpenVINO no iGPU",
        "model": "faster-whisper-small",
        "nix_note": "Build whisper.cpp com SYCL/OpenVINO; runtime: intel-compute-runtime + onevpl",
    },
    "embed": {
        "service": "llama-cpp-embeddings",
        "desc": "Embeddings (nomic-embed) — livre para iGPU se o LLM principal usa dGPU",
        "model": "nomic-embed-text-v2-moe",
        "nix_note": "Embeddings já são leves; iGPU dá ganho marginal mas libera CPU",
    },
}


def aux_offload_recommendations(hw: HardwareProfile) -> list[dict[str, str]]:
    """Recomenda offload para iGPU integrada quando detectada.

    No host (Acer Nitro V15): RTX 4050 cuida do LLM (35B MoE via CUDA);
    iGPU Intel UHD 770 cuida do STT (whisper 12x boost via SYCL) — zero
    competição de VRAM, zero competição de bandwidth de memória.
    No lab: nada (VM sem iGPU).
    """
    recs: list[dict[str, str]] = []
    if not hw.aux_gpu_name:
        return recs
    igpu = hw.aux_gpu_name.lower()
    if "intel" in igpu:
        for svc_key, svc in AUX_OFFLOAD_SERVICES.items():
            recs.append({
                "service": svc["service"],
                "desc": svc["desc"],
                "model": svc["model"],
                "backend": "SYCL/OpenVINO",
                "nix_note": svc["nix_note"],
            })
    return recs


def _aux_to_nix(recs: list[dict[str, str]]) -> str:
    """Renderiza nota NixOS para o bloco models.nix sobre offload iGPU."""
    if not recs:
        return ""
    lines = [
        "    # ── Offload auxiliar (iGPU via SYCL/OpenVINO) ──",
        "    # Ativar no host: intel-compute-runtime + onevpl + whisper SYCL",
    ]
    for r in recs:
        lines.append(f"    # {r['service']}: {r['desc']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Relatório completo (para o CLI)
# ---------------------------------------------------------------------------

def full_report(hw: HardwareProfile, ctx_target: int | None = None) -> dict[str, Any]:
    """Relatório completo: hardware → modelo → flags → comando → previsão."""
    from jarvis.core.hwdetect import classify, memory_bandwidth_gb_s

    model = pick_model(hw)
    flags = derive_flags(hw, model, ctx_target=ctx_target)
    cmd = build_command(flags, mmproj_path="<mmproj>" if model.vision else None)
    return {
        "tier": classify(hw),
        "hardware": {
            "cpu": hw.cpu.vendor or "desconhecido",
            "cores": hw.cpu.cores, "threads": hw.cpu.threads,
            "ram_gb": round(hw.ram_gb + hw.unified_memory_gb, 1),
            "gpu": hw.gpu.name or "sem GPU detectada",
            "backend": hw.gpu.backend or "none",
            "vram_gb": hw.gpu.vram_gb, "gpus": hw.gpu.count,
            "npu": hw.npu_name or "nenhuma",
            "bandwidth_gb_s": memory_bandwidth_gb_s(hw),
            "platform": hw.platform,
        },
        "modelo": {
            "key": model.key, "nome": model.name,
            "moe": model.moe, "vision": model.vision,
            "approx": model.approx, "nota": model.note,
            "tamanho_gguf_gb": round(model_size_gb(model), 1),
        },
        "flags": {
            "ngl": flags.ngl, "n_cpu_moe": flags.n_cpu_moe, "ctx": flags.ctx,
            "kv": flags.kv, "fa": flags.fa, "threads": flags.threads,
            "ubatch": flags.ubatch, "split_mode": flags.split_mode,
            "offload": flags.offload,
        },
        "comando": cmd,
        "previsao_tps": round(flags.forecast_tps, 1),
        "avisos": flags.warnings,
        "models_nix": render_models_nix(flags),
        "aux_gpu": hw.aux_gpu_name or None,
        "aux_recs": aux_offload_recommendations(hw),
    }

@dataclass
class AuxiliaryOffloadEnv:
    """Variáveis de ambiente para isolar STT (Whisper) e TTS na iGPU / CPU."""
    whisper_backend: str        # openvino | sycl | vulkan | cpu
    whisper_env: dict[str, str] # Ex: {"CUDA_VISIBLE_DEVICES": "", "SYCL_DEVICE_FILTER": "gpu"}
    tts_backend: str            # cpu | openvino
    tts_env: dict[str, str]


def derive_aux_env(hw: HardwareProfile) -> AuxiliaryOffloadEnv:
    """Gera regras de ambiente para que STT/TTS não tomem VRAM da dGPU NVIDIA."""

    # Se temos iGPU Intel detectada
    if "intel" in hw.aux_gpu_name.lower() or "raptor lake" in hw.aux_gpu_name.lower():
        return AuxiliaryOffloadEnv(
            whisper_backend="openvino",
            whisper_env={
                "CUDA_VISIBLE_DEVICES": "",  # Força ignorar a RTX 4050
                "OPENVINO_DEVICE": "GPU",    # Direciona para Intel UHD/Arc
            },
            tts_backend="cpu",  # Kokoro-82M roda com <5ms em CPU multi-thread
            tts_env={"OMP_NUM_THREADS": "4"}
        )

    # Fallback genérico: se não tiver iGPU, roda áudio na CPU para preservar VRAM da dGPU
    return AuxiliaryOffloadEnv(
        whisper_backend="cpu",
        whisper_env={"CUDA_VISIBLE_DEVICES": ""},
        tts_backend="cpu",
        tts_env={"OMP_NUM_THREADS": "4"}
    )
