"""Testes da detecção de consolidação (read-only)."""

from __future__ import annotations

import math

from jarvis.core.consolidate import (
    DUP_COSINE,
    SUPERSEDE_COSINE,
    cosine,
    detect,
    heat,
)


def _ev(i: str, text: str, ts: float) -> dict:
    return {"id": i, "text": text, "ts": ts, "kind": "fact"}


def test_cosine_identico_e_ortogonal() -> None:
    assert abs(cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(cosine([1.0, 0.0], [0.0, 1.0])) < 1e-9
    assert cosine([1.0], []) == 0.0
    assert cosine([], []) == 0.0
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0  # dimensão diferente


def test_heat_decai_com_recencia() -> None:
    agora = 1_000_000_000.0
    recente = heat(0, agora - 86400, now=agora)        # 1 dia
    velho = heat(0, agora - 30 * 86400, now=agora)     # 30 dias
    assert recente > velho
    assert velho < 0.5


def test_heat_sobe_com_acesso() -> None:
    agora = 1_000_000_000.0
    assert heat(10, agora, now=agora) > heat(0, agora, now=agora)


def test_detecta_duplicata_quase_identica() -> None:
    evs = [
        _ev("a", "usuário prefere PT-BR e vírgula de milhar", 1000.0),
        _ev("b", "usuário prefere PT-BR e vírgula de milhar.", 2000.0),
    ]
    v = {"a": [1.0, 0.0], "b": [1.0, 0.01]}
    rep = detect(evs, v, now=3000.0)
    assert rep.scanned == 2
    kinds = {f.kind for f in rep.findings}
    assert "duplicate" in kinds


def test_detecta_supersede_mesmo_assunto() -> None:
    evs = [
        _ev("a", "default do agente é PT-BR", 1000.0),
        _ev("b", "default do agente é INGLÊS neste projeto", 2000.0),
    ]
    v = {"a": [1.0, 0.0, 0.0], "b": [0.85, 0.5, 0.0]}
    rep = detect(evs, v, now=3000.0)
    sup = rep.by_kind("supersede")
    assert sup, "cos≈0.86 deveria cruzar o limiar de supersede"
    assert sup[0].newer_id == "b" and sup[0].older_id == "a"


def test_nao_marca_ortogonais() -> None:
    evs = [_ev("a", "tema A", 1000.0), _ev("b", "tema B totalmente outro", 2000.0)]
    v = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    rep = detect(evs, v, now=3000.0)
    assert not rep.by_kind("duplicate")
    assert not rep.by_kind("supersede")


def test_sem_vetores_so_sai_cold() -> None:
    evs = [_ev("a", "velho", 0.0)]
    rep = detect(evs, None, now=10 * 86400)
    assert [f.kind for f in rep.findings] == ["cold"]
    assert "sem vetor" in rep.findings[0].detail


def test_detect_nao_muta_entrada() -> None:
    """Read-only é contrato, não promessa."""
    evs = [_ev("a", "x", 1000.0), _ev("b", "x", 2000.0)]
    antes = [dict(e) for e in evs]
    detect(evs, {"a": [1.0, 0.0], "b": [1.0, 0.0]}, now=3000.0)
    assert evs == antes


def test_relatorio_serializa() -> None:
    import json
    evs = [_ev("a", "x", 1000.0), _ev("b", "x", 2000.0)]
    rep = detect(evs, {"a": [1.0, 0.0], "b": [1.0, 0.0]}, now=3000.0)
    d = json.loads(json.dumps(rep.as_dict()))
    assert d["scanned"] == 2 and d["duplicate"] >= 1


def test_limiares_sao_ordenados() -> None:
    assert DUP_COSINE > SUPERSEDE_COSINE
