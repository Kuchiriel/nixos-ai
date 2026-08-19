"""Testes do perfil de hardware → flags SOTA do llama.cpp (hwdetect + hwprofile).

Cobre a matemática do KV cache (fórmula exata do llama.cpp), a seleção de
modelo por tier, a derivação de flags para os cenários-chave (host 6GB VRAM/
32GB RAM, lab CPU, datacenter multi-GPU) e o forecast de t/s.
"""

from jarvis.core.hwdetect import CpuInfo, GpuInfo, HardwareProfile, classify
from jarvis.core.hwprofile import (
    LlamaFlags, aux_offload_recommendations, by_key, derive_flags, full_report,
    kv_bytes_per_token, kv_cache_gb, moe_expert_params_per_layer, pick_model,
    render_models_nix, derive_aux_env
)


# ---------------------------------------------------------------------------
# Fixtures de hardware (cenários reais)
# ---------------------------------------------------------------------------

def _hw(ram=32.0, vram=0.0, backend="", gpus=0, threads=8, cores=8,
        termux=False, unified=0.0) -> HardwareProfile:
    return HardwareProfile(
        cpu=CpuInfo(cores=cores, threads=threads, vendor="Intel"),
        gpu=GpuInfo(name="Test GPU" if backend else "", vram_gb=vram,
                    backend=backend, count=gpus),
        ram_gb=ram, unified_memory_gb=unified, is_termux=termux,
        platform="termux" if termux else "linux",
    )


HOST_NITRO = _hw(ram=32.0, vram=6.0, backend="cuda", gpus=1, threads=12)
LAB_VM = _hw(ram=8.0, vram=0.0, backend="", threads=4, cores=4)
PHONE = _hw(ram=4.0, threads=4, termux=True)
DATACENTER = _hw(ram=512.0, vram=80.0, backend="cuda", gpus=4, threads=64)
DESKTOP_CPU = _hw(ram=24.0, threads=12, cores=12)
APPLE = _hw(ram=64.0, unified=64.0, backend="metal")


# ---------------------------------------------------------------------------
# Matemática do KV cache (fórmula exata do llama.cpp)
# ---------------------------------------------------------------------------

def test_kv_bytes_qwen3_4b() -> None:
    """Qwen3-4B: 36 layers, 8 kv_heads, head_dim 128 → 147.456 B/token f16."""
    m = by_key("qwen3-4b")
    assert kv_bytes_per_token(m, "f16") == 2 * 8 * 128 * 36 * 2
    assert kv_bytes_per_token(m, "q8_0") == 2 * 8 * 128 * 36 * 1
    # 16K ctx f16 = 2.25 GB (147.456 B/tok × 16.384 / 2³⁰) — confere com o
    # valor conhecido: LLaMA-70B a 32K f16 ≈ 10.5GB (mesma fórmula)
    assert round(kv_cache_gb(m, 16384, "f16"), 3) == 2.25


def test_kv_bytes_qwen3_6_35b() -> None:
    """Qwen3.6-35B-A3B: 40 layers, 2 kv_heads, head_dim 256 → 40.960 B/tok q8."""
    m = by_key("qwen3.6-35b-a3b")
    assert kv_bytes_per_token(m, "f16") == 2 * 2 * 256 * 40 * 2
    assert kv_bytes_per_token(m, "q8_0") == 2 * 2 * 256 * 40 * 1
    # 16K ctx q8_0 = 0.625 GB (cabe folgado na VRAM de 6GB junto com atenção)
    assert kv_cache_gb(m, 16384, "q8_0") == 0.625


# ---------------------------------------------------------------------------
# Classificação e seleção de modelo
# ---------------------------------------------------------------------------

def test_classify_tiers() -> None:
    assert classify(HOST_NITRO) == "gaming-laptop"
    assert classify(LAB_VM) == "laptop"
    assert classify(PHONE) == "phone"
    assert classify(DATACENTER) == "datacenter"
    assert classify(DESKTOP_CPU) == "desktop"
    assert classify(APPLE) == "apple-studio"


def test_pick_model_by_tier() -> None:
    assert pick_model(HOST_NITRO).key == "qwen3.6-35b-a3b"   # host: MoE + vision
    assert pick_model(LAB_VM).key == "qwen3-4b"              # lab: CPU SLM
    assert pick_model(PHONE).key == "qwen3-1.7b"             # termux: SLM de bolso
    assert pick_model(DATACENTER).key == "qwen3-vl-235b-a22b"  # datacenter
    assert pick_model(DESKTOP_CPU).key == "qwen3.6-27b"      # 24GB RAM
    assert pick_model(APPLE).key == "qwen3.6-35b-a3b"        # unified 64GB


# ---------------------------------------------------------------------------
# Derivação de flags (os 3 cenários-chave + bordas)
# ---------------------------------------------------------------------------

def test_host_nitro_expert_offload() -> None:
    """RTX 4050 6GB / 32GB RAM → MoE com expert offload, KV q8_0, -fa on."""
    flags = derive_flags(HOST_NITRO)
    assert flags.model_key == "qwen3.6-35b-a3b"
    assert flags.offload == "expert"
    assert 1 <= flags.ngl < flags.model.layers   # NÃO cabe tudo (só atenção)
    assert flags.n_cpu_moe >= 2
    assert flags.kv == "q8_0"          # VRAM apertada → KV quantizado
    assert flags.fa is True            # cuda → flash attention
    assert flags.ctx <= 32768
    # VRAM 6GB: atenção + experts na GPU + KV q8 + overhead não podem estourar
    from jarvis.core.hwprofile import QUANT_BYTES, gpu_params_per_layer, kv_cache_gb
    per_layer_gb = (gpu_params_per_layer(flags.model, flags.n_cpu_moe, "Q4_K_M")
                    * QUANT_BYTES["Q4_K_M"] / 1e9)
    used = flags.ngl * per_layer_gb + kv_cache_gb(flags.model, flags.ctx, "q8_0") + 0.6
    assert used <= 6.5, f"VRAM estourada: {used:.1f}GB > 6GB"
    assert flags.forecast_tps > 1.0   # unidade certa (bugs de mistura B/raw dão 1.0)


def test_expert_params_sane() -> None:
    """Unidades: expert por camada deve ser positivo e da ordem de dezenas de M."""
    m = by_key("qwen3.6-35b-a3b")
    exp = moe_expert_params_per_layer(m)
    assert 10e6 < exp < 500e6          # regressão do bug params_b (B) vs raw


def test_lab_vm_cpu_only() -> None:
    """Lab (VM, sem GPU) → CPU puro, KV f16 (sem GPU q8 não compensa)."""
    flags = derive_flags(LAB_VM)
    assert flags.model_key == "qwen3-4b"
    assert flags.offload == "cpu"
    assert flags.ngl == 0
    assert flags.n_cpu_moe == 0
    assert flags.kv == "f16"
    assert flags.fa is False
    assert flags.ctx >= 2048


def test_datacenter_full_offload_split() -> None:
    """4× Tesla 80GB → tudo na GPU, KV f16, split-mode row (MoE)."""
    flags = derive_flags(DATACENTER)
    assert flags.offload == "full"
    assert flags.ngl == flags.model.layers
    assert flags.kv == "f16"
    assert flags.split_mode == "row"
    assert flags.fa is True


def test_ctx_limited_by_ram() -> None:
    """RAM apertada → contexto encolhe (nunca estoura a memória)."""
    tiny = _hw(ram=6.0, vram=0.0, threads=2)
    flags = derive_flags(tiny)
    assert flags.ctx >= 2048
    assert any("limitado pela RAM" in w for w in flags.warnings)


def test_moe_warns_on_cpu() -> None:
    """MoE em CPU puro avisa (sem GPU, expert offload não se aplica)."""
    flags = derive_flags(_hw(ram=32.0, vram=0.0, threads=8),
                         model=by_key("qwen3.6-35b-a3b"))
    assert flags.offload == "cpu"
    assert any("CPU puro" in w for w in flags.warnings)


# ---------------------------------------------------------------------------
# Comando + renderer NixOS
# ---------------------------------------------------------------------------

def test_build_command_shape() -> None:
    flags = derive_flags(HOST_NITRO)
    cmd = flags_to_cmd(flags)
    assert cmd[0] == "llama-server"
    joined = " ".join(cmd)
    assert "-ngl" in joined and "--n-cpu-moe" in joined
    assert "-ctk q8_0 -ctv q8_0" in joined
    assert "-fa on" in joined and "--jinja" in joined


def flags_to_cmd(flags: LlamaFlags) -> list[str]:
    from jarvis.core.hwprofile import build_command
    return build_command(flags, mmproj_path="<mmproj>" if flags.model.vision else None)


def test_render_models_nix_block() -> None:
    """O bloco emitido é válido como fragmento Nix (colar em models.nix)."""
    flags = derive_flags(HOST_NITRO)
    block = render_models_nix(flags, "host")
    assert block.startswith("    host = {")
    assert "model = \"qwen3.6-35b-a3b\"" in block
    assert "mmproj = \"llm-host-mmproj\"" in block
    assert "gpuLayers = " in block
    assert "--n-cpu-moe" in block
    assert "fifo" in block          # scheduler tempo real no host


def test_full_report_shape() -> None:
    report = full_report(HOST_NITRO)
    assert report["tier"] == "gaming-laptop"
    assert report["modelo"]["key"] == "qwen3.6-35b-a3b"
    assert report["flags"]["offload"] == "expert"
    assert report["previsao_tps"] > 0
    assert "models_nix" in report
    assert report["comando"][0] == "llama-server"


# ---------------------------------------------------------------------------
# Robustez: hardware desconhecido / sem arquitetura não quebra
# ---------------------------------------------------------------------------

def test_unknown_hardware_never_crashes() -> None:
    hw = HardwareProfile()  # tudo zero/desconhecido
    flags = derive_flags(hw)
    assert flags.ctx >= 2048
    assert flags.threads >= 1
    assert flags.forecast_tps > 0


# ---------------------------------------------------------------------------
# iGPU integrada (offload auxiliar: whisper STT via SYCL/OpenVINO)
# ---------------------------------------------------------------------------

def _host_with_igpu() -> HardwareProfile:
    """Host alvo real: RTX 4050 (dGPU) + Intel UHD 770 (iGPU)."""
    hw = HardwareProfile(
        cpu=CpuInfo(cores=12, threads=16, vendor="Intel"),
        gpu=GpuInfo(name="NVIDIA GeForce RTX 4050 Laptop", vram_gb=6.0,
                    backend="cuda", count=1, compute_cap="8.9"),
        ram_gb=32.0, aux_gpu_name="Intel Corporation Raptor Lake-S GT1 [UHD Graphics 770]",
    )
    return hw


def test_aux_offload_recommendations_host() -> None:
    """Host com iGPU Intel → recomenda whisper STT via SYCL/OpenVINO."""
    hw = _host_with_igpu()
    recs = aux_offload_recommendations(hw)
    assert len(recs) >= 1
    assert any(r["service"] == "llama-cpp-stt" for r in recs)
    assert all(r["backend"] == "SYCL/OpenVINO" for r in recs)
    # o LLM principal continua na dGPU — offload auxiliar não muda o perfil
    flags = derive_flags(hw)
    assert flags.offload == "expert"
    assert flags.model_key == "qwen3.6-35b-a3b"


def test_aux_offload_no_igpu() -> None:
    """Sem iGPU (lab VM) → nenhuma recomendação auxiliar."""
    assert aux_offload_recommendations(LAB_VM) == []


def test_full_report_includes_aux() -> None:
    r = full_report(_host_with_igpu())
    assert r["aux_gpu"] and "UHD" in r["aux_gpu"]
    assert r["aux_recs"] and r["aux_recs"][0]["backend"] == "SYCL/OpenVINO"

def test_derive_aux_env_intel_igpu():
    hw = HardwareProfile(
        cpu=CpuInfo(cores=10, threads=16, vendor="Intel"),
        gpu=GpuInfo(name="NVIDIA GeForce RTX 4050 Laptop GPU", vram_gb=6.0, backend="cuda", count=1),
        ram_gb=32.0,
        aux_gpu_name="Intel Corporation Raptor Lake-S GT1 [UHD Graphics 770]",
    )
    aux_env = derive_aux_env(hw)
    assert aux_env.whisper_backend == "openvino"
    assert aux_env.whisper_env["OPENVINO_DEVICE"] == "GPU"
    assert aux_env.whisper_env["CUDA_VISIBLE_DEVICES"] == ""
    assert aux_env.tts_backend == "cpu"


def test_derive_aux_env_fallback_cpu():
    hw = HardwareProfile(
        cpu=CpuInfo(cores=8, threads=8, vendor="Intel"),
        gpu=GpuInfo(name="NVIDIA GeForce RTX 3060", vram_gb=6.0, backend="cuda", count=1),
        ram_gb=16.0,
        aux_gpu_name="",
    )
    aux_env = derive_aux_env(hw)
    assert aux_env.whisper_backend == "cpu"
    assert aux_env.whisper_env["CUDA_VISIBLE_DEVICES"] == ""
    assert aux_env.tts_backend == "cpu"
