"""Testes do módulo centralizado de logging JSONL (core/logging.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core.logging import (
    Logger,
    compute_metrics,
    get_logger,
    read_events,
)


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """Diretório temporário para logs de teste."""
    d = tmp_path / "logs"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Logger básico
# ---------------------------------------------------------------------------


def test_logger_creates_file(log_dir: Path) -> None:
    logger = Logger("test_module", log_dir)
    logger.info("test_event", detail="hello")
    f = log_dir / "test_module.jsonl"
    assert f.exists()
    lines = f.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["module"] == "test_module"
    assert entry["event"] == "test_event"
    assert entry["level"] == "info"
    assert entry["detail"] == "hello"
    assert "ts" in entry
    assert "iso" in entry


def test_logger_warn_and_error(log_dir: Path) -> None:
    logger = Logger("test_levels", log_dir)
    logger.warn("warning_event", detail="warned")
    logger.error("error_event", detail="failed")
    lines = (log_dir / "test_levels.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["level"] == "warn"
    assert json.loads(lines[1])["level"] == "error"


def test_logger_extra_fields(log_dir: Path) -> None:
    logger = Logger("test_extra", log_dir)
    logger.info("with_extra", key1="val1", key2=42)
    entry = json.loads((log_dir / "test_extra.jsonl").read_text().strip())
    assert entry["key1"] == "val1"
    assert entry["key2"] == 42


def test_logger_empty_event_no_crash(log_dir: Path) -> None:
    logger = Logger("test_empty", log_dir)
    logger.info("bare_event")
    entry = json.loads((log_dir / "test_empty.jsonl").read_text().strip())
    assert entry["event"] == "bare_event"
    assert "detail" not in entry


# ---------------------------------------------------------------------------
# Rotação de arquivo
# ---------------------------------------------------------------------------


def test_rotation(log_dir: Path) -> None:
    logger = Logger("test_rotate", log_dir)
    # Força o arquivo a ficar grande (> MAX_FILE_BYTES = 10MB)
    f = log_dir / "test_rotate.jsonl"
    f.write_text("x" * (11 * 1024 * 1024))
    # Agora um emit deve rotacionar
    logger.info("after_rotation")
    assert f.exists()
    assert f.stat().st_size < 200  # arquivo novo é pequeno
    rotated = log_dir / "test_rotate.1.jsonl"
    assert rotated.exists()


# ---------------------------------------------------------------------------
# get_logger cache
# ---------------------------------------------------------------------------


def test_get_logger_cache(log_dir: Path) -> None:
    import jarvis.core.logging as mod
    mod._loggers.clear()
    a = get_logger("cached_mod", log_dir)
    b = get_logger("cached_mod", log_dir)
    assert a is b
    mod._loggers.clear()


# ---------------------------------------------------------------------------
# read_events
# ---------------------------------------------------------------------------


def test_read_events_all_modules(log_dir: Path) -> None:
    Logger("mod_a", log_dir).info("ev_a")
    Logger("mod_b", log_dir).info("ev_b")
    events = read_events(log_dir=log_dir)
    assert len(events) == 2
    modules = {e["module"] for e in events}
    assert modules == {"mod_a", "mod_b"}


def test_read_events_filtered(log_dir: Path) -> None:
    Logger("mod_x", log_dir).info("ev_x")
    Logger("mod_y", log_dir).info("ev_y")
    events = read_events("mod_x", log_dir=log_dir)
    assert len(events) == 1
    assert events[0]["module"] == "mod_x"


def test_read_events_since_ts(log_dir: Path) -> None:
    logger = Logger("ts_test", log_dir)
    logger.info("old_event")
    import time
    cutoff = time.time() + 0.1
    time.sleep(0.2)
    logger.info("new_event")
    events = read_events(since_ts=cutoff, log_dir=log_dir)
    assert len(events) == 1
    assert events[0]["event"] == "new_event"


def test_read_events_limit(log_dir: Path) -> None:
    logger = Logger("limit_test", log_dir)
    for i in range(10):
        logger.info(f"event_{i}")
    events = read_events(limit=3, log_dir=log_dir)
    assert len(events) == 3


# ---------------------------------------------------------------------------
# compute_metrics
# ---------------------------------------------------------------------------


def test_compute_metrics_empty() -> None:
    m = compute_metrics([])
    assert m["total_events"] == 0
    assert m["by_module"] == {}


def test_compute_metrics_aggregation() -> None:
    events = [
        {"module": "agent", "event": "tool_call", "level": "info"},
        {"module": "agent", "event": "tool_timeout", "level": "warn"},
        {"module": "heal", "event": "heal_restart", "level": "info"},
        {"module": "agent", "event": "tool_call", "level": "info"},
    ]
    m = compute_metrics(events)
    assert m["total_events"] == 4
    assert m["by_module"]["agent"] == 3
    assert m["by_module"]["heal"] == 1
    assert m["by_level"]["info"] == 3
    assert m["by_level"]["warn"] == 1
    assert m["by_event"]["tool_call"] == 2


# ---------------------------------------------------------------------------
# Instrumentação real: agent log
# ---------------------------------------------------------------------------


def test_agent_emits_logs(monkeypatch, tmp_path: Path) -> None:
    """Verifica que o agent emite eventos de log durante execução."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    from jarvis.core.logging import _loggers
    _loggers.clear()

    from jarvis.core.agent import Agent, AgentResult, command_allowed
    from jarvis.core.config import Config

    cfg = Config()

    # Mock simples: retorna resposta direta
    turn_n = {"n": 0}

    class FakeSession:
        def get(self, url, **kw):
            return type("R", (), {
                "json": lambda s: {"data": [{"id": "test-model"}]},
                "raise_for_status": lambda s: None,
            })()

        def post(self, url, **kw):
            turn_n["n"] += 1
            msg = {"role": "assistant", "content": "resposta ok"}
            return type("R", (), {
                "json": lambda s: {"choices": [{"message": msg}]},
                "raise_for_status": lambda s: None,
            })()

    agent = Agent(cfg, session=FakeSession())
    result = agent.run("teste de log")
    assert result.final_response == "resposta ok"

    # Verifica que os logs foram escritos
    log_file = tmp_path / "logs" / "agent.jsonl"
    assert log_file.exists()
    lines = log_file.read_text().strip().splitlines()
    events = [json.loads(l) for l in lines]
    event_names = [e["event"] for e in events]
    assert "agent_start" in event_names
    assert "agent_done" in event_names

    _loggers.clear()
