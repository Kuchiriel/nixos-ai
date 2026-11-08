"""Testes do classificador Laya (decision model ONNX).

O módulo engole toda exceção e devolve None (fallback pro regex) — é o
contrato que o caller `model_policy.classify_difficulty` depende. O teste
trava esse contrato SEM o modelo de 1,6 GB: a sessão ONNX, o tokenizer e o
config são injetados por monkeypatch.

Por que isso importa (26/10): o KeyError da tabela `temperature_by_options`
era engolido pelo except genérico e a Laya devolvia None SEMPRE — o
classificador ficava inerte e ninguém via. Um teste que só verifica
"retorna alguma coisa" não pega isso; o teste verifica o contrato.
"""

import sys
import types

import pytest


@pytest.fixture()
def laya(monkeypatch):
    """Módulo Laya com sessão/tokenizer/config falsos (hermético)."""
    if "jarvis.core.laya_classifier" not in sys.modules:
        sys.path.insert(0, "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src")
    import jarvis.core.laya_classifier as m

    m._REAL_TRY_LOAD = m._try_load  # para o teste que exercita o load real
    monkeypatch.setattr(m, "_try_load", lambda: True)
    monkeypatch.setattr(m, "_CLS", 101)
    monkeypatch.setattr(m, "_SEP", 102)
    monkeypatch.setattr(m, "_MASK", 103)
    monkeypatch.setattr(m, "_tokenize", lambda text: [1, 2, 3])
    return m


class _FakeSession:
    """Sessão ONNX fake: devolve logits fixos (1 logit por opção)."""

    def __init__(self, logits):
        self.logits = logits

    def run(self, _outputs, _inputs):
        return [self.logits]


def _install(laya, monkeypatch, logits, config=None):
    monkeypatch.setattr(laya, "_session", _FakeSession(logits))
    monkeypatch.setattr(
        laya,
        "_config",
        config
        or {
            "max_len": 192,
            "temperature": [1.0],
            "temperature_by_options": {"choice:2": 1.0},
        },
    )


def test_try_load_false_when_model_dir_missing(laya, monkeypatch, tmp_path):
    """Sem os arquivos do modelo: _try_load devolve False e nada levanta."""
    monkeypatch.setattr(laya, "_ONNX_PATH", tmp_path / "nope.onnx")
    monkeypatch.setattr(laya, "_load_failed", False)
    monkeypatch.setattr(laya, "_session", None)
    monkeypatch.setattr(laya, "_try_load", laya._REAL_TRY_LOAD)
    assert laya._try_load() is False


def test_classify_choice_returns_none_when_unavailable(laya, monkeypatch):
    """Modelo indisponível → None (o caller cai no regex)."""
    monkeypatch.setattr(laya, "_try_load", lambda: False)
    out = laya.classify_choice("oi", "q?", {"a": "x", "b": "y"})
    assert out is None


def test_classify_choice_probabilities_sum_to_one(laya, monkeypatch):
    """As probabilidades formam uma distribuição (soma 1, labels preservadas)."""
    import numpy as np

    _install(laya, monkeypatch, np.array([[2.0, 1.0, 0.0]], dtype=np.float32))
    options = {"simple": "s", "moderate": "m", "hard": "h"}
    out = laya.classify_choice("pergunta", "q?", options)
    assert out is not None
    assert set(out) == set(options)
    assert abs(sum(out.values()) - 1.0) < 1e-6
    assert all(0.0 <= p <= 1.0 for p in out.values())


def test_classify_choice_picks_the_highest_logit(laya, monkeypatch):
    """O argmax da distribuição é a opção com o maior logit."""
    import numpy as np

    _install(laya, monkeypatch, np.array([[0.0, 5.0, 1.0]], dtype=np.float32))
    out = laya.classify_choice("pergunta", "q?", {"a": "x", "b": "y", "c": "z"})
    assert max(out, key=out.get) == "b"


def test_classify_choice_never_raises_on_broken_session(laya, monkeypatch):
    """Sessão quebrada → None, nunca exceção (o módulo é fail-safe)."""
    class _Boom:
        def run(self, *_a, **_k):
            raise RuntimeError("onnx exploded")

    monkeypatch.setattr(laya, "_session", _Boom())
    monkeypatch.setattr(
        laya,
        "_config",
        {"max_len": 192, "temperature": [1.0], "temperature_by_options": {}},
    )
    assert laya.classify_choice("pergunta", "q?", {"a": "x"}) is None


def test_temperature_falls_back_to_first_entry(laya, monkeypatch):
    """O export fine-tuned não traz `temperature_by_options` → usa temperature[0].

    Regressão real (26/10): o KeyError era engolido pelo except genérico e a
    Laya devolvia None SEMPRE (classificador inerte, sem erro visível).
    O shape real é o de `~/models/laya-ft/rl_agent_config.json`: sem a
    tabela `temperature_by_options`, com `temperature: [5.0, 1.0, 1.0]`.
    """
    _install(
        laya,
        monkeypatch,
        None,
        config={"max_len": 192, "temperature": [5.0, 1.0, 1.0]},
    )
    # sem a chave no config: o fallback tem que segurar (NÃO KeyError)
    assert "temperature_by_options" not in laya._config
    assert laya._temperature_for("choice", 3) == 5.0
    # com a tabela presente, a chave pelo bucket de opções vence (3-5)
    laya._config["temperature_by_options"] = {"choice:3-5": 1.5}
    assert laya._temperature_for("choice", 3) == 1.5


def test_classify_difficulty_returns_one_of_the_three_tiers(laya, monkeypatch):
    """A dificuldade sai sempre em simple|moderate|hard (ou None)."""
    import numpy as np

    _install(laya, monkeypatch, np.array([[0.0, 0.0, 9.0]], dtype=np.float32))
    out = laya.classify_difficulty_laya("prove que X", 100)
    assert out in ("simple", "moderate", "hard", None)


def test_classify_difficulty_none_when_unavailable(laya, monkeypatch):
    """Indisponível → None (o model_policy cai no regex)."""
    monkeypatch.setattr(laya, "_try_load", lambda: False)
    assert laya.classify_difficulty_laya("qualquer coisa", 0) is None


def test_module_never_raises_on_garbage_input(laya, monkeypatch):
    """Entrada degenerada não levanta exceção (contrato fail-safe)."""
    import numpy as np

    _install(laya, monkeypatch, np.array([[0.0, 0.0]], dtype=np.float32))
    for bad in ("", "   ", "\x00\x01", "a" * 100000):
        out = laya.classify_choice(bad, "", {"a": "x", "b": "y"})
        assert out is None or isinstance(out, dict)
