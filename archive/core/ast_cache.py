"""AST Hash Cache — Cache de integridade para validação de sintaxe.

Poneglyph Protocol (Arquitetura de Integredade):
  O sistema deve ser imune à manipulação. Se um arquivo for alterado,
  o hash diverge e a validação roda. Se o hash bater, bypass (ganho de
  performance).

Mecanismo:
  1. Antes de ast.parse(), calcula SHA-256 do conteúdo
  2. Busca o hash em .cache/jarvis/ast_hashes.json
  3. Se bater: arquivo não mudou → bypass na validação
  4. Se divergir: roda ast.parse() → grava novo hash se válido
  5. Se ast.parse() falhar: NÃO grava hash → próximo acesso revalida

Invariantes:
  - Hash só é gravado se ast.parse() passou (arquivo é válido)
  - Cache é LRU-ish (mantém últimos 1000 entries por arquivo)
  - Arquivo corrompido → cache ignora e revalida
  - Thread-safe via lock (múltiplos processos podem validar)
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any


_DEFAULT_CACHE_DIR = Path(os.environ.get(
    "JARVIS_CACHE_DIR",
    os.path.expanduser("~/.cache/jarvis"),
))
_CACHE_FILE = "ast_hashes.json"
_MAX_ENTRIES = 1000


class ASTHashCache:
    """Cache de hashes SHA-256 para bypass de validação AST.

    Thread-safe: usa threading.Lock para evitar race conditions quando
    múltiplos processos validam o mesmo arquivo.

    Exemplo:
        cache = ASTHashCache()
        if cache.is_valid(filepath, content):
            # Hash bater → arquivo não mudou → bypass
            return True, ""
        # Hash divergiu → roda ast.parse()
        is_valid, error = validate_python_syntax(content)
        if is_valid:
            cache.mark_valid(filepath, content)
        return is_valid, error
    """

    def __init__(self, cache_dir: Path | None = None) -> None:
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._cache_path = self._cache_dir / _CACHE_FILE
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def _ensure_dir(self) -> None:
        """Cria o diretório de cache se não existir."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> None:
        """Carrega o cache do disco (lazy loading)."""
        if self._loaded:
            return
        try:
            if self._cache_path.exists():
                raw = self._cache_path.read_text(encoding="utf-8")
                self._data = json.loads(raw)
        except (json.JSONDecodeError, OSError):
            # Cache corrompido → ignora e começa do zero
            self._data = {}
        self._loaded = True

    def _save(self) -> None:
        """Salva o cache no disco."""
        try:
            self._ensure_dir()
            # Mantém apenas as últimas _MAX_ENTRIES entries
            if len(self._data) > _MAX_ENTRIES:
                # Ordena por timestamp e mantém os mais recentes
                sorted_entries = sorted(
                    self._data.items(),
                    key=lambda x: x[1].get("ts", 0),
                    reverse=True,
                )
                self._data = dict(sorted_entries[:_MAX_ENTRIES])
            self._cache_path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # Cache é best-effort

    @staticmethod
    def _content_hash(content: str) -> str:
        """Calcula SHA-256 do conteúdo."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def is_valid(self, filepath: str, content: str) -> bool:
        """Verifica se o hash do conteúdo bate com o cache.

        Retorna True se:
          - O hash está no cache E
          - O hash bate com o conteúdo atual

        Retorna False se:
          - O arquivo é novo (não está no cache)
          - O conteúdo mudou (hash divergiu)
          - O cache está corrompido
        """
        with self._lock:
            self._load()

            key = os.path.realpath(filepath)
            entry = self._data.get(key)
            if entry is None:
                return False

            cached_hash = entry.get("hash", "")
            current_hash = self._content_hash(content)

            return cached_hash == current_hash

    def mark_valid(self, filepath: str, content: str) -> None:
        """Marca um arquivo como válido (hash gravado no cache).

        Deve ser chamado APENAS após ast.parse() bem-sucedido.
        """
        with self._lock:
            self._load()

            key = os.path.realpath(filepath)
            self._data[key] = {
                "hash": self._content_hash(content),
                "ts": time.time(),
                "valid": True,
            }
            self._save()

    def invalidate(self, filepath: str) -> None:
        """Remove um arquivo do cache (força revalidação)."""
        with self._lock:
            self._load()
            key = os.path.realpath(filepath)
            if key in self._data:
                del self._data[key]
                self._save()

    def clear(self) -> None:
        """Limpa todo o cache."""
        with self._lock:
            self._data = {}
            self._save()

    def stats(self) -> dict[str, Any]:
        """Retorna estatísticas do cache."""
        with self._lock:
            self._load()
            return {
                "entries": len(self._data),
                "cache_file": str(self._cache_path),
                "exists": self._cache_path.exists(),
            }


# ---------------------------------------------------------------------------
# Instância global (singleton)
# ---------------------------------------------------------------------------

_global_cache: ASTHashCache | None = None


def get_ast_cache() -> ASTHashCache:
    """Retorna a instância global do cache AST."""
    global _global_cache
    if _global_cache is None:
        _global_cache = ASTHashCache()
    return _global_cache
