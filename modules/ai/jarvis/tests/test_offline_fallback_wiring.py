"""O corpus offline (N.O.M.A.D) como fallback da busca online e como dado adicional.

POR QUE (14/11, sweep-2026-11): o dono pediu o offline_search (o corpus de
sobrevivencia do N.O.M.A.D, ja exposto como tool do MCP) como fallback de
TODAS as buscas online e como dado adicional nas outras buscas dos MCPs. O
que estava feito: o offline_search existia como tool propria, mas nao era
fallback de nada (o web_search devolvia ERROR seco sem a chave do Tavily) e
o rag_search nao olhava o corpus offline.
"""
from __future__ import annotations

import jarvis.core.websearch as ws


def _sem_chave(monkeypatch):
    monkeypatch.setattr(ws, "_api_key", lambda: "")


def _com_chave_invalida(monkeypatch):
    monkeypatch.setattr(ws, "_api_key", lambda: "chave-invalida-de-teste")


def test_web_search_sem_chave_cai_no_offline(monkeypatch):
    _sem_chave(monkeypatch)
    out = ws.web_search("tratamento de agua contaminada em emergencia")
    assert not out.startswith("ERROR"), out[:200]
    assert "fonte: corpus offline" in out


def test_web_search_com_chave_rejeitada_cai_no_offline(monkeypatch):
    """O HTTP e MOCKADO: o teste nao pode depender da rede (no sandbox o
    Tavily dava timeout, aqui dava 401, e o teste mudava de resposta)."""
    _com_chave_invalida(monkeypatch)

    class _Resp:
        status_code = 401
        text = "unauthorized"

    class _FakeRequests:
        @staticmethod
        def post(*a, **k):
            return _Resp()

    monkeypatch.setitem(__import__("sys").modules, "requests", _FakeRequests)
    out = ws.web_search("water treatment emergency")
    assert not out.startswith("ERROR"), out[:200]
    assert "fonte: corpus offline" in out
    assert "401" in out


def test_web_search_com_query_vazia_da_erro():
    assert ws.web_search("").startswith("ERROR")


def test_offline_e_anexado_na_busca_semantica(monkeypatch):
    """O rag_search (semantico) anexa o corpus offline, marcado."""
    from jarvis.core import devtools

    def _fake_search(query, top_k=5):
        return [{"payload": {"content": "doc do codigo", "path": "x.py"},
                 "score": 0.9}]

    class _FakeHybrid:
        def search(self, query, top_k=5):
            return _fake_search(query, top_k)

    monkeypatch.setattr("jarvis.core.rag.HybridSearch", _FakeHybrid)
    out = devtools.semantic_search("qualquer coisa", top_k=2)
    assert out.get("ok"), out
    # o offline vem num campo SEPARADO: o contrato de retorno nao muda
    # (quem consome conta os hits do HybridSearch)
    assert out.get("offline"), out
    assert out.get("offline_source") == "offline/NOMAD", out
    assert all(r.get("source") != "offline/NOMAD" for r in out.get("results", []))


def test_busca_semantica_nao_quebra_se_o_offline_falhar(monkeypatch):
    """O offline e adicional: se ele falhar, a busca semantica segue igual."""
    from jarvis.core import devtools

    class _FakeHybrid:
        def search(self, query, top_k=5):
            return [{"payload": {"content": "doc", "path": "x.py"}, "score": 0.5}]

    monkeypatch.setattr("jarvis.core.rag.HybridSearch", _FakeHybrid)
    monkeypatch.setattr(
        "jarvis.core.offline.offline_search",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("corpus fora")),
    )
    out = devtools.semantic_search("qualquer coisa", top_k=2)
    assert out.get("ok"), out
    assert out.get("total", 0) >= 1
