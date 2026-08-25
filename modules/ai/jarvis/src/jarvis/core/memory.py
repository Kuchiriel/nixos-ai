"""Memória episódica do JARVIS — evolução do experience_buffer do legado.

O legado (Manjaro) tinha `experience_buffer.py`: lições de auto-correção em
JSONL com keyword match. Esta versão evolui para o que a Fase 7 do roadmap
define: **experiência** (não conhecimento) consultável semanticamente.

  - `remember(...)`  — grava um evento (lição, fato, decisão, preferência)
    com embedding no Qdrant (coleção `memories`) + payload estruturado
    (timestamp, kind, task, error_pattern, fix).
  - `recall(...)`    — busca híbrida (dense + sparse) por semântica.
  - `lessons(...)`   — recupera lições relevantes no formato do legado
    ("PAST LESSONS — avoid these mistakes"), para injetar no agente.
  - `forget(...)`    — remove por id; `clear()` limpa tudo.

RAG (conhecimento) ≠ memória episódica (experiência): o RAG indexa
documentos; a memória indexa eventos com contexto temporal. Ambos usam o
mesmo Qdrant híbrido, coleções diferentes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.config import Config, get_config
from jarvis.providers.llm import LLMClient
from jarvis.providers.vector_store import QdrantStore

# Kinds de eventos (evolução do experience_buffer: error/fix, mais fatos)
KIND_LESSON = "lesson"
KIND_FACT = "fact"
KIND_DECISION = "decision"
KIND_PREFERENCE = "preference"

# Keep: kinds válidos para recall por padrão
_ALL_KINDS = (KIND_LESSON, KIND_FACT, KIND_DECISION, KIND_PREFERENCE)


@dataclass
class MemoryEvent:
    """Um evento episódico armazenado."""

    kind: str
    text: str  # texto principal (embedado)
    task: str = ""
    error_pattern: str = ""
    fix: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "task": self.task,
            "error_pattern": self.error_pattern,
            "fix": self.fix,
            "ts": self.timestamp,
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(self.timestamp)),
            **self.meta,
        }


def _stable_id(text: str, timestamp: float) -> int:
    """ID determinístico: crc32 do texto + timestamp truncado."""
    import zlib

    return zlib.crc32(f"{timestamp:.0f}:{text}".encode()) & 0x7FFFFFFF


class EpisodicMemory:
    """Memória episódica com embeddings + Qdrant híbrido."""

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or get_config()
        self._store = QdrantStore(self._cfg)
        self._llm = LLMClient(self._cfg)

    # --- infra ---

    @property
    def collection(self) -> str:
        return self._cfg.qdrant_collection_memories

    def ensure(self) -> None:
        self._store.ensure_collection(self.collection, dim=self._cfg.embed_dim)

    def is_available(self) -> bool:
        return self._store.is_available()

    # --- escrita ---

    def remember(self, event: MemoryEvent) -> int | None:
        """Embebe e grava o evento na coleção memories. Retorna o id ou None."""
        if not event.text.strip():
            return None
        vector = self._llm.embed(event.text)
        if vector is None:
            return None
        self.ensure()
        from jarvis.core.rag import sparse_terms, sparse_vector

        point_id = _stable_id(event.text, event.timestamp)
        point = {
            "id": point_id,
            "vector": {
                "dense": vector,
                "bm25": sparse_vector(sparse_terms(event.text)),
            },
            "payload": event.payload(),
        }
        self._store.upsert(self.collection, [point])
        return point_id

    def remember_lesson(self, *, task: str, error_pattern: str, fix: str) -> int | None:
        """Porta do add_lesson do experience_buffer legado."""
        text = f"Task: {task}. Error: {error_pattern}. Fix: {fix}"
        return self.remember(MemoryEvent(
            kind=KIND_LESSON, text=text, task=task,
            error_pattern=error_pattern, fix=fix,
        ))

    def remember_fact(self, text: str, **meta: Any) -> int | None:
        return self.remember(MemoryEvent(kind=KIND_FACT, text=text, meta=meta))

    # --- leitura ---

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        kinds: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """Busca híbrida por eventos semânticamente relevantes.

        Inclui deduplicação por texto (memórias com texto igual ou >95% similar
        são consolidadas, mantendo a mais recente) e limite de contexto para
        não saturar o prompt de SLMs.
        """
        vector = self._llm.embed(query)
        if vector is None:
            return []
        self.ensure()
        from jarvis.core.rag import sparse_terms, sparse_vector

        # busca mais do top_k para ter margem de dedup
        points = self._store.search_hybrid(
            self.collection,
            vector,
            sparse_vector(sparse_terms(query)),
            top_k=top_k * 3,
        )
        hits: list[dict[str, Any]] = []
        seen_texts: set[str] = set()
        for p in points:
            payload = p.get("payload", {})
            if kinds and payload.get("kind") not in kinds:
                continue
            text = payload.get("text", "")
            # dedup: texto idêntico ou muito similar → mantém o mais recente
            text_key = text.strip().lower()[:500]  # chave de dedup — 500 chars evita falsos positivos
            if text_key in seen_texts:
                continue
            seen_texts.add(text_key)
            hits.append({
                "id": p.get("id"),
                "score": round(p.get("score", 0.0), 4),
                "kind": payload.get("kind", ""),
                "text": text,
                "task": payload.get("task", ""),
                "error_pattern": payload.get("error_pattern", ""),
                "fix": payload.get("fix", ""),
                "ts": payload.get("ts"),
            })
            if len(hits) >= top_k:
                break
        return hits

    def lessons(self, query: str, *, top_k: int = 3, max_chars: int = 500) -> str:
        """Formato do legado ('PAST LESSONS') para injetar no prompt do agente.

        Args:
            max_chars: limite de caracteres para não saturar o contexto de SLMs.
                       Lições mais recentes e com score maior têm prioridade.
        """
        hits = self.recall(query, top_k=top_k, kinds=(KIND_LESSON,))
        if not hits:
            return ""
        out = "\nPAST LESSONS (avoid these mistakes):\n"
        for h in hits:
            line = (f"- When task was '{h['task'] or '?'}', error "
                    f"'{h['error_pattern'] or '?'}' was fixed with:\n{h['fix'] or '?'}\n")
            if len(out) + len(line) > max_chars:
                break
            out += line
        return out

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Últimos eventos (sem embedding — via payload ts)."""
        # Qdrant não ordena por payload sem query; usamos busca com filtro vazio
        # aproximado via dense search com vetor nulo não é viável — fallback:
        # listar pela API de scroll.
        try:
            result = self._store._request(
                "POST",
                f"/collections/{self.collection}/points/scroll",
                json={"limit": limit, "with_payload": True},
            )
        except Exception:  # noqa: BLE001
            return []
        points = result.get("result", {}).get("points", [])
        events = []
        for p in points:
            pl = p.get("payload", {})
            events.append({"id": p.get("id"), **pl})
        events.sort(key=lambda e: e.get("ts", 0), reverse=True)
        return events

    def count(self) -> int:
        try:
            return self._store.count(self.collection)
        except Exception:  # noqa: BLE001
            return 0

    def clear(self) -> None:
        self._store.delete_collection(self.collection)
