"""Testes do guardrail arquivar→verificar→remover.

Cada teste reproduz um modo de falha real (o meu inclusive).
"""

from __future__ import annotations

from typing import Any

from jarvis.core.safe_archive import archive_then_delete, payload_hash


class FakeStore:
    """Store em memória com chaves para simular os erros do Qdrant real."""

    def __init__(self, *, aceita_escrita: bool = True, grava: bool = True) -> None:
        self.dados: dict[str, dict[Any, dict]] = {}
        self.aceita_escrita = aceita_escrita   # True = mente como o Qdrant
        self.grava = grava                     # False = aceita e não grava
        self.deletados: list[tuple[str, list]] = []

    def _c(self, name: str) -> dict:
        return self.dados.setdefault(name, {})

    def get_points(self, collection: str, ids: list[Any]) -> list[dict]:
        c = self._c(collection)
        return [{"id": i, "payload": c[i]["payload"], "vector": c[i].get("vector")}
                for i in ids if i in c]

    def upsert(self, collection: str, points: list[dict]) -> None:
        if not self.aceita_escrita:
            raise RuntimeError("sem escrita")
        if self.grava:
            for p in points:
                self._c(collection)[p["id"]] = p

    def delete_points(self, collection: str, ids: list[Any]) -> None:
        self.deletados.append((collection, list(ids)))
        for i in ids:
            self._c(collection).pop(i, None)

    def count(self, collection: str) -> int:
        return len(self._c(collection))


def _loja(**kw) -> FakeStore:
    s = FakeStore(**kw)
    s.dados["mem"] = {
        1: {"payload": {"text": "E2E test fact", "kind": "fact"}, "vector": [0.1, 0.2]},
        2: {"payload": {"text": "memoria real do agente", "kind": "fact"}, "vector": [0.3, 0.4]},
    }
    return s


def test_dry_run_nao_escreve_e_nao_remove() -> None:
    s = _loja()
    r = archive_then_delete(s, "mem", "arquivo", [1, 2], dry_run=True)
    assert r.reason == "dry_run" and r.verified
    assert s.deletados == [] and s.count("arquivo") == 0
    assert s.count("mem") == 2


def test_caminho_feliz_verifica_e_remove() -> None:
    s = _loja()
    r = archive_then_delete(s, "mem", "arquivo", [1], dry_run=False,
                            provenance={"_archived_at": "2026-09-25"})
    assert r.verified and r.archived == 1 and r.removed == 1
    assert r.safe
    assert s.count("arquivo") == 1 and s.count("mem") == 1
    # a cópia conserva o payload original
    pl = s.get_points("arquivo", [1])[0]["payload"]
    assert pl["text"] == "E2E test fact" and pl["_archived_at"] == "2026-09-25"


def test_aceita_escrita_mas_nao_grava_nao_remove() -> None:
    """O MEU ERRO: HTTP 200, nada gravado, e mesmo assim removeu."""
    s = _loja(grava=False)
    r = archive_then_delete(s, "mem", "arquivo", [1, 2], dry_run=False)
    assert not r.verified
    assert r.removed == 0
    assert r.reason.startswith("copia_incompleta")
    assert s.deletados == [], "NÃO pode remover sem cópia verificada"
    assert s.count("mem") == 2, "origem intacta"


def test_falha_de_escrita_nao_remove() -> None:
    s = _loja(aceita_escrita=False)
    r = archive_then_delete(s, "mem", "arquivo", [1], dry_run=False)
    assert not r.verified and r.removed == 0
    assert "falha_escrita" in r.reason
    assert s.count("mem") == 2


def test_id_inexistente_aborta() -> None:
    s = _loja()
    r = archive_then_delete(s, "mem", "arquivo", [1, 999], dry_run=False)
    assert not r.verified and r.removed == 0
    assert "fonte_devolveu_1_de_2" == r.reason
    assert s.count("mem") == 2


def test_payload_alterado_na_copia_aborta() -> None:
    """Store que 'grava' mas corrompe o payload: tem de ser detectado."""
    s = _loja()

    def put(collection, points):
        for p in points:
            s.dados.setdefault(collection, {})[p["id"]] = {**p, "payload": {**p["payload"], "text": "CORROMPIDO"}}
    s.upsert = put  # type: ignore[assignment]
    r = archive_then_delete(s, "mem", "arquivo", [1], dry_run=False)
    assert not r.verified and r.removed == 0
    assert any("payload" in m for m in r.mismatches)
    assert s.count("mem") == 2


def test_lista_vazia_nao_faz_nada() -> None:
    r = archive_then_delete(_loja(), "mem", "arquivo", [], dry_run=False)
    assert r.reason == "nada_a_fazer" and r.safe and r.removed == 0


def test_payload_hash_estavel() -> None:
    assert payload_hash({"a": 1, "b": 2}) == payload_hash({"b": 2, "a": 1})
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})
    assert payload_hash(None) == payload_hash({})


def test_safe_exige_verificacao() -> None:
    """`safe` nunca pode ser True sem verified e removed == requested."""
    from jarvis.core.safe_archive import ArchiveResult
    s = _loja(grava=False)
    r = archive_then_delete(s, "mem", "arquivo", [1], dry_run=False)
    assert not r.safe
    # nem um ArchiveResult forjado passa
    forjado = ArchiveResult(requested=1, archived=1, verified=False, removed=1)
    assert not forjado.safe
    mentiroso = ArchiveResult(requested=2, archived=2, verified=True, removed=1)
    assert not mentiroso.safe
