"""Sampling por modelo: SSOT models.nix `routing.models.<id>.sampling`.

Contrato: sampling_for() lê do registry (JSON Nix ou fallback);
_resolve_temperature() vence explicit > env > registry > legado.
"""

from __future__ import annotations

import json

from jarvis.core.config import Config
from jarvis.core.model_registry import ModelRegistry


def _reg_json(tmp_path, monkeypatch):
    data = {
        "version": 1, "default": "bonsai", "maxResident": 1,
        "models": {
            "bonsai": {"tier": "speed",
                       "capabilities": ["general"],
                       "sampling": {"temperature": 0.5, "top_p": 0.9,
                                    "top_k": 20, "min_p": 0.0,
                                    "presence_penalty": 0.0,
                                    "repetition_penalty": 1.0}},
            "jarvis-fast": {"tier": "fast",
                            "capabilities": ["general"],
                            "sampling": {"temperature": 0.7, "top_p": 0.8,
                                         "top_k": 20, "min_p": 0.0,
                                         "presence_penalty": 1.5,
                                         "repetition_penalty": 1.0}},
            "sem-sampling": {"tier": "fast", "capabilities": ["general"]},
        },
    }
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(data))
    monkeypatch.setenv("JARVIS_MODEL_REGISTRY", str(p))
    return ModelRegistry.load()


def test_sampling_for_do_json(tmp_path, monkeypatch):
    reg = _reg_json(tmp_path, monkeypatch)
    assert reg.sampling_for("bonsai")["temperature"] == 0.5
    assert reg.sampling_for("jarvis-fast")["top_p"] == 0.8
    assert reg.sampling_for("sem-sampling") == {}
    assert reg.sampling_for("inexistente") == {}


def test_fallback_tem_sampling_vendor():
    import os
    os.environ.pop("JARVIS_MODEL_REGISTRY", None)
    reg = ModelRegistry.load(path="/definitivamente/inexistente.json")
    assert reg.sampling_for("bonsai")["temperature"] == 0.5
    assert reg.sampling_for("jarvis-fast")["temperature"] == 0.7
    assert reg.sampling_for("jarvis-strong")["temperature"] == 1.0
    assert reg.sampling_for("jarvis-raw")["temperature"] == 0.7
    assert reg.sampling_for("jarvis-raw-strong")["top_k"] == 20


def _client(monkeypatch, served, env_temp="-1", model="bonsai"):
    from unittest.mock import Mock
    from jarvis.providers.llm import LLMClient
    monkeypatch.setenv("JARVIS_LLM_TEMPERATURE", env_temp)
    cfg = Config(llm_temperature=float(env_temp), llm_model=model)
    c = LLMClient(cfg, session=Mock())
    monkeypatch.setattr(c, "_served_model_id", lambda: served)
    return c


def test_resolve_explicit_vence(tmp_path, monkeypatch):
    _reg_json(tmp_path, monkeypatch)
    c = _client(monkeypatch, "bonsai")
    assert c._resolve_temperature(0.0) == 0.0


def test_resolve_registry_vence_legado(tmp_path, monkeypatch):
    _reg_json(tmp_path, monkeypatch)
    c = _client(monkeypatch, "bonsai")
    # Legado diria 0.0 p/ bonsai; registry diz 0.5 (Prism).
    assert c._resolve_temperature(None) == 0.5


def test_resolve_env_vence_registry(tmp_path, monkeypatch):
    _reg_json(tmp_path, monkeypatch)
    c = _client(monkeypatch, "bonsai", env_temp="0.2")
    assert c._resolve_temperature(None) == 0.2


def test_resolve_legado_bonsai_nunca_greedy(tmp_path, monkeypatch):
    # Servidor fora do registry: bonsai cai no legado → 0.5 (vendor),
    # nunca 0.0 (greedy colapsa, medido 25/09).
    _reg_json(tmp_path, monkeypatch)
    c = _client(monkeypatch, "bonsai-desconhecido", model="")
    assert c._resolve_temperature(None) == 0.5
