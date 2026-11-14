"""Web search via Tavily (mesmo provedor do Roo Dev).

Chave pela abstração jarvis.core.keys ("tavily"):
env TAVILY_API_KEY (keys-wrapper.sh) ou /etc/jarvis-secrets/tavily.env.
Sem chave → mensagem ERROR clara (nunca exceção que quebre o agente).
"""

from __future__ import annotations

from typing import Any

TAVILY_ENDPOINT = "https://api.tavily.com/search"


def _api_key() -> str:
    """Resolve a chave Tavily pela abstração única de secrets."""
    from jarvis.core.keys import get
    return get("tavily")


def has_key() -> bool:
    """True se há chave configurada (arquivo ou env)."""
    return bool(_api_key())


def _offline_fallback(query: str, max_results: int, why: str) -> str:
    """Cai no corpus offline (N.O.M.A.D) quando a busca online nao responde.

    (14/11, sweep-2026-11) o dono pediu o offline como fallback de TODAS as
    buscas online. O corpus e local e deterministico (FTS5), entao responder
    offline e melhor do que devolver ERROR e deixar o agente sem resposta.
    A fonte vai escrita na resposta, para ninguem confundir offline com web.
    """
    try:
        from jarvis.core.offline import offline_search

        hits = offline_search(query, max_results=max_results)
    except Exception as exc:  # noqa: BLE001
        hits = ""
    if not hits or hits.startswith("ERROR") or hits.startswith("NO_SOURCE"):
        return (
            f"ERROR: web search indisponivel ({why}) e o corpus offline nao "
            f"respondeu tambem."
        )
    return (
        f"[fonte: corpus offline N.O.M.A.D — a busca online falhou ({why})]\n"
        + hits
    )


def web_search(query: str, *, max_results: int = 5) -> str:
    """Pesquisa web via Tavily, com FALLBACK no corpus offline.

    (14/11) o offline (N.O.M.A.D) e o fallback: sem chave, HTTP de erro,
    timeout ou excecao nao caem mais em ERROR seco, caem no corpus local.
    """
    query = (query or "").strip()
    if not query:
        return "ERROR: query vazia"
    key = _api_key()
    if not key:
        return _offline_fallback(
            query, max_results,
            "sem TAVILY_API_KEY; configure /etc/jarvis-secrets/tavily.env")
    try:
        import requests
    except ImportError:
        return "ERROR: requests não instalado"
    try:
        resp = requests.post(
            TAVILY_ENDPOINT,
            json={
                "api_key": key,
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(max_results, 10)),
                "include_answer": True,
            },
            timeout=30,
        )
        if resp.status_code in (401, 403):
            return _offline_fallback(
                query, max_results,
                f"Tavily rejeitou a chave ({resp.status_code})")
        if resp.status_code != 200:
            return _offline_fallback(
                query, max_results,
                f"Tavily HTTP {resp.status_code}: {(resp.text or '')[:100]}")
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — rede é best-effort
        return _offline_fallback(query, max_results, f"falha de rede: {exc}"[:80])
    lines: list[str] = []
    answer = (data.get("answer") or "").strip()
    if answer:
        lines.append(f"Resposta: {answer}")
    for r in data.get("results", [])[:max_results]:
        title = (r.get("title") or "").strip()
        url = (r.get("url") or "").strip()
        content = (r.get("content") or "").strip()[:400]
        lines.append(f"- {title} ({url})\n  {content}")
    return "\n".join(lines) if lines else "Sem resultados."


def to_dict(query: str, max_results: int = 5) -> dict[str, Any]:
    """Envelope estruturado (testável)."""
    out = web_search(query, max_results=max_results)
    return {"ok": not out.startswith("ERROR"), "result": out}
