"""Busca no corpus offline de sobrevivência (N.O.M.A.D / Kiwix / FM 4-25.11).

Fonte única da busca offline: o `dev.py` (harness de texto) e o MCP
(`mcp_server.py`) chamam ESTE módulo — sem cópia da lógica nos dois lados.

Contrato com o modelo:
- **nunca inventa**: sem resultado, devolve "NO OFFLINE SOURCE ..." e o
  agente deve dizer que não tem fonte local;
- todo resultado traz a fonte (arquivo, tipo e licença);
- funciona **sem internet** e **sem LLM** — é o ramo offline da voz.

Arquitetura (medida em 14/11/2026, 15 perguntas de primeiros socorros em PT):

- **Primário**: `offline_fts` sobre `data/offline/corpus.db` (SQLite FTS5,
  18.943 docs). Mesmo índice e mesmo ranking do `~/bin/offline` do celular:
  15/15 no top-1, ~0,3 s, sem servidor de embedding.
- **Fallback**: `HybridSearch` no Qdrant `offline_survival` (quando o banco não
  existe), com expansão PT→EN e piso de similaridade densa.

Por que não usar só o híbrido: em 14/11 ele devolvia "Dulce de Leche" para
"picada de cobra" (1/15). Sem primeiros socorros no corpus e sem ponte PT→EN,
o vizinho mais próximo de uma emergência era uma receita.
"""

from __future__ import annotations

NO_SOURCE = (
    "NO OFFLINE SOURCE: the offline survival corpus has no answer for this "
    "query — say so, do not invent one."
)

HEADER = "Source: offline survival corpus (works without internet)."

SYNTHETIC_NOTE = (
    "NOTE: FirstAidQA hits are a synthetic corpus (CC BY 4.0) — treat them as a "
    "lead, not as a clinical source; prefer FM 4-25.11 / NOMAD when both appear."
)

# Piso do fallback híbrido: similaridade densa do top-1 (cosine 0..1).
# Medido no offline_survival: tema coberto >= 0.40; fora do corpus <= 0.30.
MIN_DENSE_SCORE = 0.34


def _expand_query(query: str) -> str:
    """Anexa termos EN quando a query é PT (ponte para o corpus em inglês)."""
    try:
        from jarvis.core.offline_fts import expand
    except Exception:
        return query
    weights, phrases, _gloss = expand(query)
    if not weights:
        return query
    return f"{query} {' '.join([*weights, *phrases])}"


def _dense_top_score(expanded: str, cfg) -> float:
    """Similaridade densa do melhor ponto (score cru, não o rank do hybrid)."""
    from jarvis.providers.llm import LLMClient
    from jarvis.providers.vector_store import QdrantStore
    from jarvis.core.rag import OFFLINE_COLLECTION

    llm = LLMClient(cfg)
    store = QdrantStore(cfg)
    hits = store.search(OFFLINE_COLLECTION, llm.embed(expanded), top_k=1)
    if not hits:
        return 0.0
    hit = hits[0]
    score = hit.get("score") if isinstance(hit, dict) else getattr(hit, "score", 0.0)
    try:
        return float(score or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _format_fts(hits: list[dict]) -> str:
    from jarvis.core.offline_fts import KIND_LABEL

    lines = [HEADER]
    for h in hits:
        label = KIND_LABEL.get(h.get("kind", ""), h.get("kind", ""))
        extra = f" · {h['license']}" if h.get("license") else ""
        lines.append(
            f"[{h['score']:.2f}] {h.get('source', '?')} · {label}{extra}\n"
            f"{h.get('title', '')}\n{h.get('snippet', '')}"
        )
    if any(h.get("kind") == "firstaidqa" for h in hits):
        lines.append(SYNTHETIC_NOTE)
    return "\n".join(lines)


def offline_search(query: str, max_results: int = 5) -> str:
    """Busca no corpus offline. Devolve texto formatado (nunca levanta).

    Args:
        query: pergunta de sobrevivência/emergência (PT ou EN).
        max_results: 1..10 (default 5).
    """
    try:
        try:
            top_k = int(max_results or 5)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(10, top_k))

        raw_query = (query or "").strip()
        if not raw_query:
            return NO_SOURCE

        # 1) FTS5: determinístico, sem embedding, mesmo índice do celular.
        try:
            from jarvis.core import offline_fts

            db_path = offline_fts.corpus_path()
        except Exception:
            offline_fts, db_path = None, None

        if offline_fts is not None and db_path:
            hits = offline_fts.search(raw_query, db_path, top_k)
            if not hits or hits[0]["score"] < offline_fts.MIN_SCORE:
                return NO_SOURCE
            return _format_fts(hits)

        # 2) fallback: híbrido (banco ausente) — corpus Qdrant + piso denso.
        from jarvis.core.rag import HybridSearch, OFFLINE_COLLECTION
        from jarvis.core.config import Config

        cfg = Config()
        expanded = _expand_query(raw_query)
        if _dense_top_score(expanded, cfg) < MIN_DENSE_SCORE:
            return NO_SOURCE

        hs = HybridSearch(config=cfg)
        results = hs.search(expanded, top_k=top_k, collection=OFFLINE_COLLECTION)
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
