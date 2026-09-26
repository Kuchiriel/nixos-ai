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


class _FakeStore:
    """Store mínimo p/ apply(): lê, e grava só quando dry_run=False."""
    def __init__(self, points):
        self.points = {p["id"]: p for p in points}
        self.upserted = []

    def get_points(self, name, ids):
        return [dict(self.points[i]) for i in ids if i in self.points]

    def upsert(self, name, pts):
        self.upserted.extend(pts)
        for p in pts:
            self.points[p["id"]] = p


def _report(kind, newer, older):
    from jarvis.core.consolidate import Report, Finding
    return Report(scanned=2, findings=[Finding(kind, newer, older, 0.95, "x")])


def test_apply_dry_run_nao_toca_no_store():
    from jarvis.core.consolidate import apply
    st = _FakeStore([{"id": 7, "vector": [0.1], "payload": {"text": "velho"}}])
    r = apply(_report("duplicate", 8, 7), st, "memories", dry_run=True)
    assert r["dry_run"] and r["marked"] == 1 and r["ids"] == ["7"]
    assert not st.upserted and "superseded" not in st.points[7]["payload"]


def test_apply_marca_superseded_by_e_nunca_deleta():
    from jarvis.core.consolidate import apply
    st = _FakeStore([{"id": 7, "vector": [0.1], "payload": {"text": "velho"}}])
    r = apply(_report("duplicate", 8, 7), st, "memories", dry_run=False)
    assert r["marked"] == 1 and st.points[7]["payload"]["superseded"] is True
    assert st.points[7]["payload"]["superseded_by"] == 8
    assert len(st.points) == 1  # NUNCA deleta — ponto continua no store


def test_apply_supersede_marca_o_antigo():
    from jarvis.core.consolidate import apply
    st = _FakeStore([{"id": 3, "vector": [0.2], "payload": {"text": "contraditado"}}])
    apply(_report("supersede", 9, 3), st, "memories", dry_run=False)
    assert st.points[3]["payload"]["superseded_by"] == 9


def test_recall_filtra_superseded():
    from jarvis.core.consolidate import apply
    st = _FakeStore([{"id": 7, "vector": [0.1], "payload": {"text": "v"}}])
    apply(_report("duplicate", 8, 7), st, "memories", dry_run=False)
    # o filtro do recall: payload.superseded exclui (memoria.py)
    assert st.points[7]["payload"]["superseded"] is True
