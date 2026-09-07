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


def web_search(query: str, *, max_results: int = 5) -> str:
    """Pesquisa web via Tavily. Retorna texto ou mensagem ERROR:."""
    query = (query or "").strip()
    if not query:
        return "ERROR: query vazia"
    key = _api_key()
    if not key:
        return (
            "ERROR: web search indisponível (sem TAVILY_API_KEY). "
            "Configure /etc/jarvis-secrets/tavily.env ou exporte TAVILY_API_KEY."
        )
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
            return "ERROR: Tavily rejeitou a chave (401/403) — verifique TAVILY_API_KEY"
        if resp.status_code != 200:
            return f"ERROR: Tavily HTTP {resp.status_code}: {(resp.text or '')[:120]}"
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — rede é best-effort
        return f"ERROR: falha no web search: {exc}"[:200]
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
