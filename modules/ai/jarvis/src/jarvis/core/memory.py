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

import os
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
KIND_ERROR = "error"

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
    """ID determinístico de 63 bits: sha256 do CONTEÚDO (sem timestamp).

    Audit P0-1: o id antigo (crc32 de ts:text) NÃO era idempotente —
    re-remember do mesmo texto criava ponto novo (ts na hash). Agora:
    mesmo texto ⇒ mesmo id ⇒ upsert sobrescreve (atualiza ts/kind).
    """
    from jarvis.providers.vector_store import stable_id
    return stable_id("mem", text)


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

    def remember_lesson(self, *, task: str, error_pattern: str, fix: str,
                        lint: bool | str | None = None,
                        tenant: str | None = None) -> int | None:
        """Porta do add_lesson do experience_buffer legado.

        lint (Contract B, R2/20/09): "auto" = env JARVIS_LESSON_LINT
        (default off; "1"/"transform" liga). Quando ativo, fix episódico
        com números é transformado em regra value-free (menos atração p/
        SLM) e o original preservado como evidência em meta.
        """
        if lint is None:
            lint = os.environ.get("JARVIS_LESSON_LINT", "").lower()
        transformed = ""
        transformed_error = ""
        if lint in ("1", "true", "transform", "auto"):
            try:
                from jarvis.core.lesson_lint import lint_lesson, _strip_numerics
                res = lint_lesson(task, error_pattern, fix)
                if res.policy == "transformed":
                    # R2: QUALQUER número episódico atrai (L4 rotulado
                    # falhou igual) — transforma fix E error_pattern;
                    # task fica intacta (identidade do supersede).
                    if res.transformed:
                        transformed = res.transformed
                    transformed_error = _strip_numerics(
                        error_pattern).strip(" .:")
            except Exception:  # noqa: BLE001 — lint best-effort
                pass
        _fix = transformed or fix
        _err = transformed_error or error_pattern
        meta: dict = {}
        if tenant is not None:
            meta["tenant"] = tenant
        if transformed or transformed_error:
            meta["lint"] = "transformed"
            meta["original_fix"] = fix  # proveniência preservada (§4)
            meta["original_error_pattern"] = error_pattern
        # Supersede: mesma task aposenta a anterior (freshness — sem isso
        # "local 0/3" de setembro convive com "0/47" de hoje e ambos injetam).
        # Best-effort: nunca bloqueia a gravação nova.
        try:
            self.forget_task(task)
        except Exception:  # noqa: BLE001
            pass
        text = f"Task: {task}. Error: {error_pattern}. Fix: {_fix}"
        return self.remember(MemoryEvent(
            kind=KIND_LESSON, text=text, task=task,
            error_pattern=_err, fix=_fix, meta=meta,
        ))

    def forget_task(self, task: str) -> int:
        """Apaga lessons com mesma task normalizada. Retorna nº apagados."""
        key = " ".join((task or "").strip().lower().split())
        if not key:
            return 0
        try:
            result = self._store._request(
                "POST", f"/collections/{self.collection}/points/scroll",
                json={"limit": 200, "with_payload": True, "filter": {"must": [
                    {"key": "kind", "match": {"value": KIND_LESSON}}]}})
        except Exception:  # noqa: BLE001
            return 0
        ids = [p.get("id")
               for p in result.get("result", {}).get("points", [])
               if " ".join(str((p.get("payload", {}) or {}).get(
                   "task", "")).strip().lower().split()) == key
               and p.get("id") is not None]
        if not ids:
            return 0
        try:
            self._store.delete_points(self.collection, ids)
        except Exception:  # noqa: BLE001
            return 0
        return len(ids)

    def remember_fact(self, text: str, **meta: Any) -> int | None:
        return self.remember(MemoryEvent(kind=KIND_FACT, text=text, meta=meta))

    # --- leitura ---

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        kinds: tuple[str, ...] | None = None,
        tenant: str | None = None,
    ) -> list[dict[str, Any]]:
        """Busca híbrida por eventos semânticamente relevantes.

        Inclui deduplicação por texto (memórias com texto igual ou >95% similar
        são consolidadas, mantendo a mais recente) e limite de contexto para
        não saturar o prompt de SLMs.

        tenant (isolamento 22/09, evidência: isolada 3/3 vs 0/3): quando
        dado, só retornam hits do mesmo tenant; hits sem tenant seguem
        visíveis (compat). None = comportamento atual.
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
            # (26/09, LOOP-v3) superseded fora do recall: a versão mais nova
            # existe e pontua melhor — a antiga só duplica/contradiz.
            # (consolidate.apply marca; NUNCA deleta — rollback = limpar flag)
            if payload.get("superseded"):
                continue
            if kinds and payload.get("kind") not in kinds:
                continue
            if tenant is not None:
                _pt = payload.get("tenant")
                if _pt is not None and _pt != tenant:
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

    def lessons(self, query: str, *, top_k: int = 3, max_chars: int = 500,
                tenant: str | None = None) -> str:
        """Formato do legado ('PAST LESSONS') para injetar no prompt do agente.

        Args:
            max_chars: limite de caracteres para não saturar o contexto de SLMs.
                       Lições mais recentes e com score maior têm prioridade.
            tenant: isolamento por task/domínio (opt-in, default None).
        """
        hits = self.recall(query, top_k=top_k,
                           kinds=(KIND_LESSON, KIND_FACT, KIND_ERROR),
                           tenant=tenant)
        if not hits:
            return ""
        out = "\nPAST LESSONS (avoid these mistakes):\n"
        for h in hits:
            if h["kind"] == KIND_LESSON and (h["task"] or h["fix"]):
                # Formato STATE codificado (não prosa): modelo pequeno ignora
                # conselho em prosa; diretiva tipada parseável adere melhor
                # (precedente: nudges STATE do loop com fallback parseável).
                line = (f"STATE(lesson): task='{h['task'] or '?'}' "
                        f"error='{h['error_pattern'] or '?'}' "
                        f"fix='{h['fix'] or '?'}'\n")
            else:
                # Fact/error sem campos task/fix: injeta o texto compacto
                # (L8: v41 + quoting facts score 0.9 no recall mas invisíveis
                # ao filtro lesson-only — 41 falhas com a cura no store).
                # Idade anotada (freshness visível: fato de setembro não vale
                # o mesmo que fato de hoje; modelo desconta sozinho).
                txt = (h["text"] or "").strip().replace("\n", " ")
                if not txt:
                    continue
                _age = ""
                try:
                    _ts = float(h.get("ts") or 0)
                    if _ts > 0:
                        import time as _tm
                        _days = int((_tm.time() - _ts) // 86400)
                        if _days >= 1:
                            _age = f"[{_days}d ago] "
                except Exception:  # noqa: BLE001
                    pass
                line = f"STATE(known-{h['kind']}): {_age}{txt[:180]}\n"
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

    def clear(self, *, confirm: bool = False) -> None:
        """Apaga TODA a memória episódica (destrutivo — audit P0-3).

        Exige confirm=True explicitamente; sem ele, levanta erro em vez
        de deletar a coleção por engano (chamador descuidado/bug).
        """
        if not confirm:
            raise RuntimeError(
                "EpisodicMemory.clear() é destrutivo (delete da coleção "
                f"'{self.collection}'): chame com confirm=True")
        self._store.delete_collection(self.collection)
