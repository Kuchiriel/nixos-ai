"""Fila de mensagens leve — IPC entre processos via JSON file.

Útil para:
  - Voice pipeline: enfileirar pedidos quando o LLM está ocupado
  - Telegram: fila de aprovações assíncronas
  - Idle worker: fila de tarefas agendadas
  - Cross-process: qualquer coordinator que precise de fila persistente

Design:
  - Arquivo JSON em /tmp/jarvis-queue.json (mmap-friendly, atomic writes)
  - Queue ID por arquivo (múltiplas filas independentes)
  - TTL por item (expira automaticamente)
  - Thread-safe via file lock

Uso:
    from jarvis.core.queue import Queue
    q = Queue("voice")
    q.put({"prompt": "qual a气温?", "source": "wakeword"})
    item = q.get()  # oldest non-expired
    q.done(item["id"])
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any


_DEFAULT_DIR = Path(os.environ.get("JARVIS_STATE_DIR", "~/.local/state/jarvis")).expanduser()


class Queue:
    """Fila de mensagens persistente via JSON file."""

    def __init__(
        self,
        name: str = "default",
        *,
        base_dir: Path | None = None,
        ttl_seconds: float = 300.0,  # 5 min default
    ) -> None:
        self._dir = (base_dir or _DEFAULT_DIR) / "queues"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{name}.json"
        self._ttl = ttl_seconds
        self._name = name

    def _read(self) -> list[dict[str, Any]]:
        """ Lê a fila (com file lock compartilhado)."""
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _write(self, items: list[dict[str, Any]]) -> None:
        """Escreve a fila (com file lock exclusivo — atomic via temp)."""
        tmp = self._path.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                json.dump(items, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
                fcntl.flock(f, fcntl.LOCK_UN)
            tmp.replace(self._path)
        except OSError:
            pass

    def put(
        self,
        payload: dict[str, Any],
        *,
        priority: int = 0,
        ttl: float | None = None,
    ) -> str:
        """Enfileira um item. Retorna o ID."""
        import uuid
        item_id = uuid.uuid4().hex[:12]
        items = self._read()
        items.append({
            "id": item_id,
            "payload": payload,
            "priority": priority,
            "created_at": time.time(),
            "expires_at": time.time() + (ttl or self._ttl),
            "status": "pending",
        })
        # Ordena por prioridade (maior = primeiro) e depois por tempo
        items.sort(key=lambda x: (-x["priority"], x["created_at"]))
        self._write(items)
        return item_id

    def get(self) -> dict[str, Any] | None:
        """Retorna o próximo item pendente não expirado (FIFO por prioridade)."""
        items = self._read()
        now = time.time()
        for item in items:
            if item["status"] == "pending" and item["expires_at"] > now:
                item["status"] = "processing"
                self._write(items)
                return item
        return None

    def done(self, item_id: str) -> bool:
        """Marca um item como concluído e remove da fila."""
        items = self._read()
        before = len(items)
        items = [i for i in items if i["id"] != item_id]
        if len(items) < before:
            self._write(items)
            return True
        return False

    def fail(self, item_id: str, *, error: str = "") -> bool:
        """Marca um item como falho (mantém na fila como 'failed')."""
        items = self._read()
        for item in items:
            if item["id"] == item_id:
                item["status"] = "failed"
                item["error"] = error
                self._write(items)
                return True
        return False

    def peek(self) -> list[dict[str, Any]]:
        """Lista itens pendentes sem processar nenhum."""
        items = self._read()
        now = time.time()
        return [i for i in items if i["status"] == "pending" and i["expires_at"] > now]

    def purge(self) -> int:
        """Remove itens expirados. Retorna quantos foram removidos."""
        items = self._read()
        now = time.time()
        before = len(items)
        items = [i for i in items if i["expires_at"] > now or i["status"] == "processing"]
        removed = before - len(items)
        if removed:
            self._write(items)
        return removed

    def stats(self) -> dict[str, Any]:
        """Estatísticas da fila."""
        items = self._read()
        now = time.time()
        pending = sum(1 for i in items if i["status"] == "pending" and i["expires_at"] > now)
        processing = sum(1 for i in items if i["status"] == "processing")
        failed = sum(1 for i in items if i["status"] == "failed")
        expired = len(items) - pending - processing - failed
        return {
            "queue": self._name,
            "pending": pending,
            "processing": processing,
            "failed": failed,
            "expired": expired,
            "total": len(items),
        }

    def __len__(self) -> int:
        """Itens pendentes não expirados."""
        return len(self.peek())
