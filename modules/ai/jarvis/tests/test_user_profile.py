"""Testes do módulo de perfil de usuario dinâmico (core/user_profile.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core.user_profile import (
    DEFAULTS,
    UserProfile,
    build_context_block,
    inject_context,
    profile_forget,
    profile_set,
    profile_show,
)


# ---------------------------------------------------------------------------
# UserProfile CRUD
# ---------------------------------------------------------------------------


def test_load_defaults(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "nonexistent.json")
    assert p.get("language") == "pt-BR"
    assert p.get("verbosity") == "normal"
    assert p.get("tone") == "concise"
    assert p.get("expertise") == "advanced"


def test_set_and_get(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    p.set("verbosity", "verbose", source="cli")
    assert p.get("verbosity") == "verbose"
    assert p.meta("verbosity")["source"] == "cli"
    assert "updated_at" in p.meta("verbosity")


def test_persist_and_reload(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    p = UserProfile()
    p.load(path)
    p.set("tone", "friendly")
    p.save(path)

    p2 = UserProfile()
    p2.load(path)
    assert p2.get("tone") == "friendly"
    assert p2.get("language") == "pt-BR"  # default preservado


def test_forget(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    p.set("tone", "verbose")
    assert p.forget("tone") is True
    assert p.get("tone") == ""  # removido, get retorna empty
    assert p.get("tone", "fallback") == "fallback"
    # defaults originais preservados
    assert p.get("language") == "pt-BR"
    assert p.forget("nonexistent") is False


def test_all_returns_copy(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    d = p.all()
    d["language"] = "en-US"  # modifica a copia
    assert p.get("language") == "pt-BR"  # original inalterado


def test_unknown_key_returns_empty(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    assert p.get("unknown_key") == ""
    assert p.get("unknown_key", "fallback") == "fallback"


def test_empty_profile_path() -> None:
    p = UserProfile()
    p.load()  # usa o path default
    assert p.get("language") == "pt-BR"


def test_corrupted_file_uses_defaults(tmp_path: Path) -> None:
    path = tmp_path / "corrupted.json"
    path.write_text("not json {{{")
    p = UserProfile()
    p.load(path)
    assert p.get("language") == "pt-BR"


# ---------------------------------------------------------------------------
# Context injection
# ---------------------------------------------------------------------------


def test_build_context_block_includes_profile(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    p.set("verbosity", "minimal")
    ctx = build_context_block(p)
    assert "USER PREFERENCES:" in ctx
    assert "verbosity: minimal" in ctx


def test_build_context_block_minimal_no_system(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    p.set("verbosity", "minimal")
    ctx = build_context_block(p)
    # Minimal: no SYSTEM block
    assert "SYSTEM:" not in ctx


def test_build_context_block_verbose_has_system(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    p.set("verbosity", "verbose")
    ctx = build_context_block(p)
    assert "SYSTEM:" in ctx
    assert "ENVIRONMENT:" in ctx


def test_inject_context_appends_to_prompt(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    original = "You are JARVIS."
    result = inject_context(original, p)
    assert result.startswith("You are JARVIS.")
    assert "USER PREFERENCES:" in result
    assert len(result) > len(original)


def test_inject_context_empty_profile() -> None:
    """Profile vazio (sem load) gera contexto sem preferências."""
    p = UserProfile()
    # Sem carregar — _data vazio, mas CONTEXTUAL e SYSTEM aparecem
    result = inject_context("base prompt", p)
    assert result.startswith("base prompt")
    assert "ENVIRONMENT:" in result
    assert len(result) > len("base prompt")


def test_build_context_has_environment(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    ctx = build_context_block(p)
    assert "ENVIRONMENT:" in ctx
    assert "time:" in ctx


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def test_profile_show(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    output = profile_show(p)
    assert "User Profile:" in output
    assert "language" in output
    assert "pt-BR" in output


def test_profile_set(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    result = profile_set(p, "tone", "verbose")
    assert "tone = verbose" in result
    assert p.get("tone") == "verbose"


def test_profile_forget_existing(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    p.set("tone", "verbose")
    result = profile_forget(p, "tone")
    assert "removed" in result


def test_profile_forget_nonexistent(tmp_path: Path) -> None:
    p = UserProfile()
    p.load(tmp_path / "test.json")
    result = profile_forget(p, "nonexistent")
    assert "not found" in result


# ---------------------------------------------------------------------------
# Integration: Agent uses profile
# ---------------------------------------------------------------------------


def test_agent_loads_profile(monkeypatch, tmp_path: Path) -> None:
    """Verifica que o Agent carrega o profile e injeta no system prompt."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    # Salva um profile customizado
    p = UserProfile()
    p.load()
    p.set("tone", "verbose")
    p.save()

    from jarvis.core.logging import _loggers
    _loggers.clear()

    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    cfg = Config()
    turn_n = {"n": 0}

    class FakeSession:
        last_payload: dict = {}

        def get(self, url, **kw):
            return type("R", (), {
                "json": lambda s: {"data": [{"id": "test-model"}]},
                "raise_for_status": lambda s: None,
            })()

        def post(self, url, **kw):
            FakeSession.last_payload = kw.get("json", {})
            turn_n["n"] += 1
            msg = {"role": "assistant", "content": "ok"}
            return type("R", (), {
                "json": lambda s: {"choices": [{"message": msg}]},
                "raise_for_status": lambda s: None,
            })()

    agent = Agent(cfg, session=FakeSession())
    result = agent.run("teste")

    # Verifica que o system prompt contém o profile
    messages = FakeSession.last_payload.get("messages", [])
    system_msg = messages[0]["content"] if messages else ""
    assert "USER PREFERENCES:" in system_msg
    assert "tone: verbose" in system_msg

    _loggers.clear()


def test_agent_injects_environment_context(monkeypatch, tmp_path: Path) -> None:
    """Verifica que o contexto temporal e do sistema é injetado."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    from jarvis.core.logging import _loggers
    _loggers.clear()

    from jarvis.core.agent import Agent
    from jarvis.core.config import Config

    cfg = Config()
    turn_n = {"n": 0}

    class FakeSession:
        last_payload: dict = {}

        def get(self, url, **kw):
            return type("R", (), {
                "json": lambda s: {"data": [{"id": "test-model"}]},
                "raise_for_status": lambda s: None,
            })()

        def post(self, url, **kw):
            FakeSession.last_payload = kw.get("json", {})
            turn_n["n"] += 1
            msg = {"role": "assistant", "content": "ok"}
            return type("R", (), {
                "json": lambda s: {"choices": [{"message": msg}]},
                "raise_for_status": lambda s: None,
            })()

    agent = Agent(cfg, session=FakeSession())
    agent.run("teste")

    messages = FakeSession.last_payload.get("messages", [])
    system_msg = messages[0]["content"] if messages else ""
    assert "ENVIRONMENT:" in system_msg
    assert "time:" in system_msg

    _loggers.clear()
