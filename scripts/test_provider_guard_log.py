"""Tests for the provider guard's log parsing (persona `dev`, 24/11).

O guard existia para ver o provider cair (429) e trocar o modelo da sessao.
Medido em 24/11: ele estava CEGO no opencode 2.2.6 — zero das 172 linhas de
erro do log casavam com o regex, e a rotacao comparava uma classe que o
classificador nunca produzia. Estes testes fixam o contrato com o formato
REAL do log.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[1]
GUARD = PACK / "scripts" / "agent-provider-guard.py"


def _guard():
    spec = importlib.util.spec_from_file_location("provider_guard", GUARD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["provider_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


def _ago(minutes: int) -> str:
    """Timestamp ISO de N minutos atras (dentro da janela do parse)."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# Formato REAL do opencode 2.2.6 (medido no log vivo, 24/11):
#   timestamp=... level=ERROR run=... message="Failed to drain Session"
#       cause="AI.Error: API rate limit exceeded\n ..." sessionID=ses_...
def _line_2x() -> str:
    return (
        f'timestamp={_ago(5)} level=ERROR run=7101e745 '
        'message="Failed to drain Session" '
        'cause="AI.Error: API rate limit exceeded\\n    at PHe (/$bunfs/root/chunk.js:3:3000)" '
        'sessionID=ses_spawn1795170445151'
    )


# Formato antigo (1.x), que o guard ainda deve ler:
def _line_1x() -> str:
    return (
        f'timestamp={_ago(10)} level=ERROR message="stream error" '
        'providerID=nvidia modelID=nvidia/minimaxai/minimax-m3.1-flash '
        'session.id=ses_abc123 error.error="Too Many Requests: rate limited"'
    )


def _write(tmp_path: Path, *lines: str):
    p = tmp_path / "opencode.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_parses_the_opencode_2x_format(tmp_path: Path) -> None:
    """(24/11) O formato do 2.2.6: 'Failed to drain Session' + cause= + sessionID=."""
    mod = _guard()
    p = _write(tmp_path, _line_2x())
    events = mod.parse_events(p, 10_000)
    assert len(events) == 1
    e = events[0]
    assert e["session"] == "ses_spawn1795170445151"
    assert "API rate limit exceeded" in e["error"]
    assert e["class"] == "RATE"


def test_still_parses_the_old_format(tmp_path: Path) -> None:
    """O log antigo nao pode ser perdido (rotulo 'stream error' + error.error=)."""
    mod = _guard()
    p = _write(tmp_path, _line_1x())
    events = mod.parse_events(p, 10_000)
    assert len(events) == 1
    assert events[0]["provider"] == "nvidia"
    assert events[0]["session"] == "ses_abc123"
    assert events[0]["class"] == "RATE"


def test_rate_limit_class_is_in_the_rotate_list() -> None:
    """(24/11) A rotacao comparava 'RATE_LIMIT'; o classificador produz 'RATE'.

    Com a divergencia, a rotacao automatica (commit 86a5cc12, 15/11) nunca
    rodou. O contrato agora e' explicito: toda classe que indica provider
    caido esta na lista de rotacao.
    """
    mod = _guard()
    for cls in ("RATE", "QUOTA", "MODEL"):
        assert cls in mod.ROTATE_CLASSES
    assert mod.classify("AI.Error: API rate limit exceeded")[0] in mod.ROTATE_CLASSES
    assert mod.classify("AI.Error: Too Many Requests")[0] in mod.ROTATE_CLASSES
    assert mod.classify(
        "AI.Error: you have used up your daily free allocation of 10,000 neurons"
    )[0] in mod.ROTATE_CLASSES
    assert mod.classify(
        "AI.Error: Model 'nemotron-3-nano:30b' is currently unavailable."
    )[0] in mod.ROTATE_CLASSES


@pytest.mark.parametrize(
    "erro,classe",
    [
        ("AI.Error: API rate limit exceeded", "RATE"),
        ("AI.Error: Too Many Requests", "RATE"),
        ("AI.Error: Invalid request", "BADREQ"),
        ("AI.Error: nv-gate: request too large for the upstream context", "CTX"),
        ("AI.Error: you have used up your daily free allocation", "QUOTA"),
        ("AI.Error: Model 'x' is currently unavailable.", "MODEL"),
        ("AI.Error: something nobody saw before", "OTHER"),
    ],
)
def test_classification_uses_the_real_log_text(erro: str, classe: str) -> None:
    """(24/11) As classes vem do texto REAL do 2.2.6, nao do HTTP crabra."""
    mod = _guard()
    assert mod.classify(erro)[0] == classe


def test_ignores_lines_that_are_not_provider_errors(tmp_path: Path) -> None:
    mod = _guard()
    ruido = (
        'timestamp=2026-11-24T05:00:00.000Z level=INFO run=x '
        'message="spawning process" command=/bin/sh args="[]"'
    )
    p = _write(tmp_path, ruido)
    assert mod.parse_events(p, 10_000) == []
