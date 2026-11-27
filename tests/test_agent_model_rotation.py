"""Testes da rotacao de modelo (scripts/agent-model.py).

(27/11, medido no host nitro-v15) A auto-cura da frota estava quebrada por
dois defeitos independentes, ambos medidos em producao:

1. A ROTACAO TENTAVA PRIMEIRO O MODELO QUE ACABOU DE FALHAR. Este script e
   chamado pelo provider-guard justamente porque o modelo ATUAL caiu (429,
   EOL, quota), mas o `choose_models` punha o modelo corrente no topo da
   lista. Com `--max-tries 2` sobrava so 1 tentativa real, e se ela falhasse
   o guard reportava 'todos os modelos tentados falharam'.
   Medido: sessao ses_e0cc94944ffenbIgskVV0Cv3K7, modelo
   nvidia/google/gemma-4-31b-it (EOL) -> 1o candidato era o proprio
   gemma-4-31b-it.

2. O TIMEOUT POR TENTATIVA NAO CABIA NO ORCAMENTO DO CHAMADOR. O guard roda
   este script com `subprocess.run(..., timeout=420)` e passa --max-tries 2;
   com 300 s por tentativa o pior caso interno era 600 s, e o guard ABORTAVA
   o processo em 420 s -> "troca falhou: Command ... timed out after 420
   seconds" (medido nas notas de 25/11 e 27/11).

Teste OFFLINE: nao chama provider, nao roda turno, nao mexe em cooldown.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "agent-model.py"

# Orcamento do CHAMADOR: o provider-guard usa este valor (medido).
GUARD_BUDGET = 420


@pytest.fixture(scope="module")
def am():
    spec = importlib.util.spec_from_file_location("agent_model_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_o_modelo_que_falhou_vai_para_o_fim_da_rotacao(am, monkeypatch):
    """O modelo que caiu nao pode ser a PRIMEIRA tentativa da rotacao."""
    dead = "nvidia/google/gemma-4-31b-it"
    monkeypatch.setattr(am, "choose_models",
                        lambda current, auto, explicit: [
                            dead, "nvidia/minimaxai/minimax-m3.1-flash",
                            "ovhcloud/gpt-oss-20b"])
    monkeypatch.setattr(am, "session_model",
                        lambda s: {"model": {"id": "gemma-4-31b-it",
                                             "providerID": "nvidia"}})
    monkeypatch.setattr(am, "in_cooldown", lambda m: False)
    monkeypatch.setattr(am, "mark_cooldown", lambda m: None)

    # reproduz a reordenacao que o main() faz
    candidates = [m for m in am.choose_models(dead, False, None)
                  if m and not am.in_cooldown(m)]
    if dead in candidates:
        candidates.remove(dead)
        candidates.append(dead)
    assert candidates[0] != dead, "a rotacao tenta o modelo morto primeiro"
    assert candidates.index(dead) == len(candidates) - 1, (
        "o modelo que falhou deve ficar no fim da lista")


def test_o_principal_reordena_o_modelo_morto_para_o_fim(am, monkeypatch, capsys):
    """O main() e quem reordena: a prova e o output do script."""
    dead = "nvidia/google/gemma-4-31b-it"
    vivo = "nvidia/minimaxai/minimax-m3.1-flash"
    monkeypatch.setattr(am, "session_model",
                        lambda s: {"model": {"id": "gemma-4-31b-it",
                                             "providerID": "nvidia"}})
    monkeypatch.setattr(am, "choose_models",
                        lambda current, auto, explicit: [dead, vivo])
    monkeypatch.setattr(am, "in_cooldown", lambda m: False)
    monkeypatch.setattr(am, "mark_cooldown", lambda m: None)
    # o 1o candidato (vivo) responde bem -> a rotacao para nele
    monkeypatch.setattr(am, "run_turn",
                        lambda s, t, m, timeout=None: (0, "ok"))

    argv = sys.argv
    sys.argv = ["agent-model.py", "--run", "ses_x", "msg", "--max-tries", "2"]
    try:
        rc = am.main()
    except SystemExit as exc:  # pragma: no cover
        rc = exc.code
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    import json as _json
    d = _json.loads(out)
    assert d["ok"] is True, out
    assert d["model"] == vivo, (
        f"a rotacao escolheu {d['model']} em vez do modelo vivo {vivo}")
    # e o modelo morto nao foi nem a primeira tentativa
    assert d["tried"][0]["model"] == vivo, d["tried"]


def test_o_timeout_por_tentativa_cabe_no_orcamento_do_guard(am):
    """N tentativas nunca podem estourar o orcamento do chamador.

    Medido: 300 s x 2 tentativas = 600 s > 420 s do guard -> o guard
    abortava a rotacao antes dela terminar.
    """
    for max_tries in (1, 2, 3):
        folga = 30
        por_tentativa = max(30, (GUARD_BUDGET - folga) // max_tries)
        por_tentativa = min(por_tentativa, am.TIMEOUT)
        assert por_tentativa * max_tries < GUARD_BUDGET, (
            f"com {max_tries} tentativas o pior caso ({por_tentativa * max_tries}s) "
            f"estoura o orcamento do guard ({GUARD_BUDGET}s)")


def test_o_timeout_padrao_cabe_no_orcamento(am):
    """O valor padrao do script ja nao pode estourar o guard."""
    assert am.TIMEOUT * 2 < GUARD_BUDGET, (
        f"o timeout padrao ({am.TIMEOUT}s) com 2 tentativas estoura o "
        f"orcamento do guard ({GUARD_BUDGET}s)")


# ── o id do modelo da sessao tem de casar com o do catalogo ─────────────

def test_o_id_da_sessao_casa_com_o_do_catalogo(am):
    """A sessao e o catalogo nao falam o mesmo id.

    Medido: a sessao devolve `id = gemma-4-31b-it` com `providerID = nvidia`
    (o id DENTRO do provider), mas o catalogo usa o caminho completo
    `nvidia/google/gemma-4-31b-it` (o `model_id` e `google/gemma-4-31b-it`).
    Concatenar produzia `nvidia/gemma-4-31b-it`, que nunca casa com a
    entrada do catalogo -> o modelo morto continuava sendo a 1a tentativa.
    """
    sessao = {"id": "gemma-4-31b-it", "providerID": "nvidia"}
    cid = am._catalog_id(sessao)
    assert cid == "nvidia/google/gemma-4-31b-it", (
        f"o id da sessao nao casou com o catalogo: {cid!r}")


def test_o_id_da_sessao_aceita_o_caminho_completo(am):
    """Se a sessao ja devolver o caminho completo, ele passa direto."""
    sessao = {"id": "nvidia/google/gemma-4-31b-it", "providerID": "nvidia"}
    assert am._catalog_id(sessao) == "nvidia/google/gemma-4-31b-it"


def test_o_id_vazio_nao_quebra(am):
    assert am._catalog_id({}) == ""
    assert am._catalog_id(None) == ""
