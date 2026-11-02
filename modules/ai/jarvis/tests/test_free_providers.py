"""Invariantes da fonte única de providers cloud (modules/ai/free-providers.json).

CONTEXTO (02/11): o opencode calcula o limiar de auto-compactação como
`context - maxOutputTokens` quando o modelo NÃO declara `limit.input` —
e esse valor é EXATAMENTE o teto da API (prompt_tokens + max_tokens ≤
context). Folga zero + o check de overflow usar a contagem do turno
ANTERIOR = HTTP 400 "context_length" (medido no NIM: 262146 > 262144).

O `headroom` declarado por provider no JSON vira `limit.input` no
home.nix (via lib/opencode-limits.nix). Estes testes existem para que
NENHUM provider novo entre sem a folga — a classe de bug volta em
silêncio se alguém copiar um bloco de provider sem o headroom.
"""

import json
from pathlib import Path

import pytest


def _find_providers_json() -> Path | None:
    """Procura o JSON subindo a árvore (o pacote nix só leva ./jarvis)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "free-providers.json"
        if candidate.is_file():
            return candidate
    return None


JSON_PATH = _find_providers_json()

# No sandbox do build nix (src = ./jarvis) o JSON não existe — o mesmo
# motivo do fallback em model_policy.py. Testes pulam em vez de quebrar
# o build do pacote.
pytestmark = pytest.mark.skipif(
    JSON_PATH is None,
    reason="free-providers.json fora do pacote (sandbox nix) — invariantes validadas no repo",
)

VALID_STATUS = {
    "active",
    "rate_limited",
    "untested",
    "unstable",
    "agentic_only",
    "disabled",
}


@pytest.fixture(scope="module")
def data() -> dict:
    assert JSON_PATH is not None
    return json.loads(JSON_PATH.read_text())


def test_json_has_providers_and_layers(data):
    assert data["providers"], "free-providers.json sem providers"
    assert data["cascade_layers"], "free-providers.json sem cascade_layers"


def test_every_provider_declares_headroom(data):
    """Sem headroom → usable == teto da API → 400 no turno seguinte."""
    for name, prov in data["providers"].items():
        assert "headroom" in prov, f"provider '{name}' sem headroom"
        assert isinstance(prov["headroom"], int), f"headroom de '{name}' não é int"
        assert prov["headroom"] > 0, f"headroom de '{name}' precisa ser > 0"


def test_headroom_covers_measured_growth(data):
    """Medido no NIM (2287 passos minimax): p99=12308, max=28333.

    O headroom precisa cobrir o p99 com folga; abaixo de 20k a classe
    de bug volta (3 passos > 20k em 2287 = 0.13%).
    """
    for name, prov in data["providers"].items():
        assert prov["headroom"] >= 20000, f"headroom de '{name}' abaixo do piso medido"


def test_every_model_has_sane_limits(data):
    # maxTokens que o opencode realmente pede = min(output, 32000)
    # (ProviderTransform.OUTPUT_TOKEN_MAX). O prompt ceiling do modelo
    # é context - maxTokens (a API conta prompt + max_tokens ≤ context).
    for pname, prov in data["providers"].items():
        for model in prov["models"]:
            where = f"{pname}/{model.get('id')}"
            assert model.get("id"), f"{where} sem id"
            assert model.get("name"), f"{where} sem name"
            assert model["context"] > 0, f"{where} sem context"
            assert model["output"] > 0, f"{where} sem output"
            assert model["output"] <= model["context"], (
                f"{where}: output > context é impossível (o request nunca cabe)"
            )
            assert model["context"] - min(model["output"], 32000) > 0, (
                f"{where}: não sobra prompt depois do output (nunca cabe)"
            )
            assert model["status"] in VALID_STATUS, f"{where}: status '{model['status']}' desconhecido"


def test_explicit_input_never_exceeds_context(data):
    """`input` é opcional; quando presente, é o orçamento de prompt."""
    for pname, prov in data["providers"].items():
        for model in prov["models"]:
            if "input" in model:
                where = f"{pname}/{model['id']}"
                assert 0 < model["input"] <= model["context"], f"{where}: input fora do range"


def test_minimax_declared_with_measured_context(data):
    """Regressão do 400 (02/11): o minimax precisa existir aqui.

    Fora do JSON ele vinha só do catálogo models.dev → sem limit.input →
    usable = 262144 - 32000 = teto exato → 400.
    """
    nvidia = data["providers"]["nvidia"]
    models = {m["id"]: m for m in nvidia["models"]}
    minimax = models.get("minimaxai/minimax-m3.1-flash")
    assert minimax is not None, "minimax não declarado no provider nvidia"
    assert minimax["context"] == 262144, "contexto do minimax mudou (medido: 262144)"
    assert minimax["status"] == "active"
    assert nvidia["headroom"] >= 20000
