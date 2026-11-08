"""Busca no corpus offline de sobrevivência (N.O.M.A.D / Kiwix).

Fonte única da busca offline: o `dev.py` (harness de texto) e o MCP
(`mcp_server.py`) chamam ESTE módulo — sem cópia da lógica nos dois lados.

Contrato com o modelo:
- **nunca inventa**: sem resultado, devolve "NO OFFLINE SOURCE ..." e o
  agente deve dizer que não tem fonte local;
- todo resultado traz o caminho do arquivo de origem;
- funciona **sem internet** (é o ramo offline da voz, antes da web).
"""

from __future__ import annotations

NO_SOURCE = (
    "NO OFFLINE SOURCE: the offline survival corpus has no answer for this "
    "query — say so, do not invent one."
)

HEADER = "Source: offline survival corpus (works without internet)."


def offline_search(query: str, max_results: int = 5) -> str:
    """Busca no corpus offline. Devolve texto formatado (nunca levanta).

    Args:
        query: pergunta de sobrevivência/emergência.
        max_results: 1..10 (default 5).
    """
    try:
        from jarvis.core.rag import HybridSearch, OFFLINE_COLLECTION
        from jarvis.core.config import Config

        try:
            top_k = int(max_results or 5)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(10, top_k))

        hs = HybridSearch(config=Config())
        results = hs.search(query or "", top_k=top_k, collection=OFFLINE_COLLECTION)
        if not results:
            return NO_SOURCE
        lines = [HEADER]
        for r in results:
            payload = r.payload or {}
            src = payload.get("path") or payload.get("source_id") or "?"
            content = " ".join(str(payload.get("content", "")).split())
            lines.append(f"[{r.score:.2f}] {src}\n{content[:300]}")
        return "\n".join(lines)
    except Exception as e:  # fail-safe: o caller decide o fallback
        return f"ERROR: {e}"
