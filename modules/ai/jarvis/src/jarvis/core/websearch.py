"""Web search via Tavily (mesmo provedor do Roo Dev).

Chave: /etc/jarvis-secrets/tavily.env (formato KEY=valor) ou env TAVILY_API_KEY.
Sem chave → mensagem ERROR clara (nunca exceção que quebre o agente).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

TAVILY_ENDPOINT = "https://api.tavily.com/search"
_KEY_FILE = Path("/etc/jarvis-secrets/tavily.env")


def _api_key() -> str:
    """Resolve a chave Tavily (arquivo → env). Vazio = não configurado."""
    try:
        if _KEY_FILE.exists():
            for line in _KEY_FILE.read_text().splitlines():
                line = line.strip()
                if line.startswith("TAVILY_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
                if line and "=" not in line and len(line) > 10:
                    return line
    except OSError:
        pass
    return os.environ.get("TAVILY_API_KEY", "").strip().strip("\"'")


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
