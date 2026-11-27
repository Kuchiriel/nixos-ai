"""Tests for the provider guard's log parsing (persona `dev`, 24/11).

O guard existia para ver o provider cair (429) e trocar o modelo da sessao.
Medido em 24/11: ele estava CEGO no opencode 2.2.6 — zero das 172 linhas de
erro do log casavam com o regex, e a rotacao comparava uma classe que o
classificador nunca produzia. Estes testes fixam o contrato com o formato
REAL do log.
"""
from __future__ import annotations

import importlib.util
import json
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


# (26/11, medido no log vivo, lane endpoint-ovhcloud) O texto real de EOL e
# de 429 do opencode 2.2.6 NAO casa com os padroes de 24/11: o 2.2.6 escreve
# "has reached its end of life ... and is no longer available" (e nao "is
# currently unavailable"), e o 429 vem como "Provider request failed with HTTP
# 429" com o corpo da cota. Medido em 7 dias: 63 eventos, 43 caidos em OTHER
# (28 EOL, 11 HTTP 429, 4 overloaded) — e OTHER nao esta em ROTATE_CLASSES,
# entao essas 43 nao viravam rotacao: a sessao ficava no modelo morto.
@pytest.mark.parametrize(
    "erro,classe",
    [
        ("AI.Error: The model 'google/gemma-4-31b-it' has reached its end of "
         "life on 2026-11-24T09:00:00Z and is no longer available.", "MODEL"),
        ("AI.Error: The model 'google/diffusiongemma-26b-a4b-it' has reached "
         "its end of life on 2026-11-12T09:00:00Z and is no longer available.",
         "MODEL"),
        ("AI.Error: Provider request failed with HTTP 429: [{'error': {'code': "
         "429, 'message': 'You exceeded your current quota'}}]", "RATE"),
        ("AI.Error: Service temporarily overloaded", "RATE"),
    ],
)
def test_classification_covers_the_measured_2x_texts(erro: str, classe: str) -> None:
    """(26/11) O texto que o 2.2.6 escreve HOJE precisa cair numa classe
    rotacionavel: EOL e 429 caiam em OTHER e ficavam sem rotacao."""
    mod = _guard()
    assert mod.classify(erro)[0] == classe


def test_every_classified_failure_is_rotatable_or_explicitly_not() -> None:
    """(26/11) Nenhum texto de provider real pode cair em OTHER sem querer:
    OTHER nao esta em ROTATE_CLASSES, entao o evento morre no log."""
    mod = _guard()
    for erro in (
        "AI.Error: The model 'google/gemma-4-31b-it' has reached its end of "
        "life on 2026-11-24T09:00:00Z and is no longer available.",
        "AI.Error: Provider request failed with HTTP 429: quota exceeded",
        "AI.Error: Service temporarily overloaded",
        "AI.Error: API rate limit exceeded",
        "AI.Error: Too Many Requests",
        "AI.Error: Model 'x' is currently unavailable.",
    ):
        classe = mod.classify(erro)[0]
        assert classe != "OTHER", erro
        assert classe in mod.ROTATE_CLASSES, (erro, classe)


def test_provider_and_model_are_recovered_from_the_error_text() -> None:
    """(26/11) Nas linhas do 2.2.6 providerID= e modelID= nao existem (medido:
    0 de 63 linhas ERROR tem qualquer um dos dois), entao o provider e o model
    vinham vazios e a nota saia como 'PROVIDER OTHER em /'. O texto do erro
    traz o nome do modelo morto, que e' o que a nota precisa dizer."""
    mod = _guard()
    erro = ("AI.Error: The model 'google/gemma-4-31b-it' has reached its end "
            "of life on 2026-11-24T09:00:00Z and is no longer available.")
    model = mod.model_from_error(erro)
    assert model == "google/gemma-4-31b-it"


def test_provider_is_recovered_from_the_model_name() -> None:
    """(26/11) O prefixo do catalogo e' o provider ('nvidia/google/...' no
    /api/models), e o texto do erro traz o id do modelo sem prefixo. Sem isso
    a chave de cooldown fica por (classe, provider vazio, sessao)."""
    mod = _guard()
    catalogo = {
        "nvidia": {"google/gemma-4-31b-it": "nvidia/google/gemma-4-31b-it",
                   "google/diffusiongemma-26b-a4b-it":
                       "nvidia/google/diffusiongemma-26b-a4b-it"},
        "openrouter": {"google/gemma-4-31b-it:free":
                       "openrouter/google/gemma-4-31b-it:free"},
    }
    assert mod.provider_for_model("google/gemma-4-31b-it", catalogo) == "nvidia"
    assert mod.provider_for_model(
        "google/diffusiongemma-26b-a4b-it", catalogo) == "nvidia"
    # id completo (o log 1.x traz providerID= e modelID=) tambem resolve
    assert mod.provider_for_model(
        "nvidia/google/gemma-4-31b-it", catalogo) == "nvidia"
    # nada inventado: modelo fora do catalogo fica sem provider
    assert mod.provider_for_model("google/model-que-nao-existe", catalogo) == ""


def test_event_without_model_in_text_uses_the_session_model(tmp_path: Path) -> None:
    """(26/11) 30 dos 58 eventos de 7 dias nao nomeiam o modelo no texto
    (429 com corpo de cota, overloaded, CTX). Para esses, provider e model
    vem do modelo ATUAL da sessao — e a mesma fonte que o agent-model.py usa
    para escolher o proximo modelo."""
    mod = _guard()
    linha = (
        f'timestamp={_ago(5)} level=ERROR run=7101e745 '
        'message="Failed to drain Session" '
        'cause="AI.Error: Provider request failed with HTTP 429: '
        '[{\\"error\\": {\\"code\\": 429}}]" '
        'sessionID=ses_spawn1795170445151'
    )
    p = _write(tmp_path, linha)
    chamadas: list[str] = []

    def lookup(session: str) -> tuple[str, str]:
        chamadas.append(session)
        return ("nvidia", "minimaxai/minimax-m3.1-flash")

    events = mod.parse_events(p, 10_000, session_lookup=lookup)
    assert len(events) == 1
    e = events[0]
    assert e["class"] == "RATE"
    assert e["provider"] == "nvidia"
    assert e["model"] == "minimaxai/minimax-m3.1-flash"
    assert chamadas == ["ses_spawn1795170445151"]


def test_event_with_model_in_text_does_not_call_the_session(tmp_path: Path) -> None:
    """O texto do erro ja diz o modelo: nao ha por que chamar a API."""
    mod = _guard()
    linha = (
        f'timestamp={_ago(5)} level=ERROR run=7101e745 '
        'message="Failed to drain Session" '
        'cause="AI.Error: The model \'google/gemma-4-31b-it\' has reached its '
        'end of life on 2026-11-24T09:00:00Z and is no longer available." '
        'sessionID=ses_spawn1795170445151'
    )
    p = _write(tmp_path, linha)

    def lookup(session: str) -> tuple[str, str]:  # pragma: no cover
        raise AssertionError("nao deveria consultar a sessao")

    events = mod.parse_events(p, 10_000, session_lookup=lookup)
    assert len(events) == 1
    e = events[0]
    assert e["class"] == "MODEL"
    assert e["model"] == "google/gemma-4-31b-it"
    assert e["provider"] == "nvidia"


def test_eol_model_is_marked_in_the_cooldown_the_rotation_reads(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """(27/11, medido) O EOL repetia 6 vezes em 24h na mesma sessao: o guard
    so tinha a chave de dedupe local (classe|provider|sessao, 900 s) e nunca
    marcava o modelo morto no cooldown que o agent-model.py consulta
    (provider-cooldown.json, por id do catalogo)."""
    mod = _guard()
    cooldown = tmp_path / "provider-cooldown.json"
    monkeypatch.setattr(mod, "MODEL_COOLDOWN", cooldown)
    monkeypatch.setattr(mod, "_opencode_providers", lambda: {
        "nvidia": {"google/gemma-4-31b-it": "nvidia/google/gemma-4-31b-it"}})
    mod.mark_model_cooldown("nvidia", "google/gemma-4-31b-it")
    data = json.loads(cooldown.read_text(encoding="utf-8"))
    assert "nvidia/google/gemma-4-31b-it" in data
    assert data["nvidia/google/gemma-4-31b-it"] > 0


def test_model_cooldown_needs_a_known_catalog_pair(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nada e' inventado: so marca quando o config do opencode conhece o
    par provider/modelo (o id do catalogo e' provider + "/" + modelo)."""
    mod = _guard()
    cooldown = tmp_path / "provider-cooldown.json"
    monkeypatch.setattr(mod, "MODEL_COOLDOWN", cooldown)
    monkeypatch.setattr(mod, "_opencode_providers", lambda: {
        "nvidia": {"google/gemma-4-31b-it": "nvidia/google/gemma-4-31b-it"}})
    mod.mark_model_cooldown("", "google/gemma-4-31b-it")
    mod.mark_model_cooldown("nvidia", "")
    mod.mark_model_cooldown("openrouter", "google/gemma-4-31b-it")
    assert not cooldown.exists()


def test_ignores_lines_that_are_not_provider_errors(tmp_path: Path) -> None:
    mod = _guard()
    ruido = (
        'timestamp=2026-11-24T05:00:00.000Z level=INFO run=x '
        'message="spawning process" command=/bin/sh args="[]"'
    )
    p = _write(tmp_path, ruido)
    assert mod.parse_events(p, 10_000) == []
