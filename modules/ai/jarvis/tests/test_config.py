"""Testes da configuração central (env-driven)."""

import os

from jarvis.core.config import Config, get_config


def test_defaults_are_local() -> None:
    cfg = Config()
    assert cfg.llm_base_url == "http://127.0.0.1:8080/v1"
    assert cfg.qdrant_url == "http://127.0.0.1:6333"
    assert cfg.state_dir.is_absolute()


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_LLM_BASE_URL", "http://localhost:9999/v1")
    monkeypatch.setenv("JARVIS_QDRANT_URL", "http://localhost:7000")
    monkeypatch.setenv("JARVIS_EMBED_DIM", "512")
    cfg = get_config()
    assert cfg.llm_base_url == "http://localhost:9999/v1"
    assert cfg.qdrant_url == "http://localhost:7000"
    assert cfg.embed_dim == 512


def test_ensure_state_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "jarvis-state"))
    cfg = get_config()
    path = cfg.ensure_state_dir()
    assert path.exists()
    assert path.is_dir()
