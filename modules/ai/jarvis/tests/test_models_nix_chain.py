"""Cadeia models.nix → registry JSON → Python (§17/ADR-005).

models.nix é SSOT (routing + sampling + endpoints); o Nix gera
/etc/jarvis/model-registry.json; ModelRegistry/select_model consomem.
Estes testes travam a cadeia contra drift (mutação em qualquer elo
quebra aqui — nunca fallback silencioso em produção).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REGISTRY_JSON = Path("/etc/jarvis/model-registry.json")


def _needs_registry():
    if not REGISTRY_JSON.exists():
        pytest.skip("sem /etc/jarvis/model-registry.json (fora do NixOS)")


def test_registry_models_carry_tier_caps_ctx_sampling() -> None:
    """Todo modelo do registry tem tier/capabilities/ctx/sampling."""
    _needs_registry()
    from jarvis.core.model_registry import ModelRegistry

    reg = ModelRegistry.load()
    assert reg.models, "registry vazio"
    for mid, m in reg.models.items():
        assert getattr(m, "tier", None), f"{mid} sem tier"
        assert set(getattr(m, "capabilities", ())), f"{mid} sem capabilities"
        assert getattr(m, "raw", {}).get("ctx", 0) > 0, f"{mid} sem ctx"
        s = reg.sampling_for(mid)
        assert s.get("temperature") is not None, f"{mid} sem sampling"


def test_select_model_returns_registry_ids() -> None:
    """select_model só devolve ids do registry (nada hardcoded)."""
    _needs_registry()
    from jarvis.core.model_registry import ModelRegistry
    from jarvis.core.model_policy import select_model

    reg = ModelRegistry.load()
    mid, reason = select_model({"capabilities": {"coding", "tools"}})
    assert mid in reg.models, f"{mid} fora do registry"
    assert reason.get("selected", mid) == mid


def test_temperature_order_explicit_env_registry() -> None:
    """Ordem de vitória: explicit > cfg/env > registry (models.nix dixit)."""
    _needs_registry()
    from types import SimpleNamespace
    from jarvis.core.model_registry import ModelRegistry
    from jarvis.providers.llm import LLMClient

    reg = ModelRegistry.load()
    cfg = SimpleNamespace(llm_temperature=-1.0, llm_model="bonsai",
                          llm_base_url="http://127.0.0.1:8080/v1")
    client = LLMClient.__new__(LLMClient)
    client._cfg = cfg
    assert client._resolve_temperature(0.0) == 0.0  # explicit vence tudo
    assert client._resolve_temperature(None) == float(
        reg.sampling_for("bonsai")["temperature"])  # registry, não default py
