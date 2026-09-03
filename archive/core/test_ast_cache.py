"""Testes do AST Hash Cache — Poneglyph Protocol.

Cobre:
  1. Cache hit/miss básico
  2. Invalidation por mudança de conteúdo
  3. Thread safety
  4. Cache corrompido
  5. Integração com ast_guard (validate_python_syntax_cached)
  6. Estatísticas do cache
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from jarvis.core.ast_cache import ASTHashCache, get_ast_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PYTHON = "x = 1\nprint(x)\n"
_INVALID_PYTHON = "def foo(\n  pass\n"
_VALID_PYTHON_CHANGED = "x = 2\nprint(x)\n"


# ---------------------------------------------------------------------------
# 1. Cache hit/miss básico
# ---------------------------------------------------------------------------

class TestASTHashCacheBasic:
    """Testes básicos do cache."""

    def test_miss_on_new_file(self, tmp_path: Path) -> None:
        """Arquivo novo → cache miss."""
        cache = ASTHashCache(cache_dir=tmp_path)
        assert not cache.is_valid("/tmp/test.py", _VALID_PYTHON)

    def test_hit_after_mark(self, tmp_path: Path) -> None:
        """Após mark_valid → cache hit."""
        cache = ASTHashCache(cache_dir=tmp_path)
        filepath = "/tmp/test.py"
        cache.mark_valid(filepath, _VALID_PYTHON)
        assert cache.is_valid(filepath, _VALID_PYTHON)

    def test_miss_on_content_change(self, tmp_path: Path) -> None:
        """Conteúdo muda → cache miss."""
        cache = ASTHashCache(cache_dir=tmp_path)
        filepath = "/tmp/test.py"
        cache.mark_valid(filepath, _VALID_PYTHON)
        assert not cache.is_valid(filepath, _VALID_PYTHON_CHANGED)

    def test_hit_after_re_mark(self, tmp_path: Path) -> None:
        """Após mudança + re-mark → cache hit."""
        cache = ASTHashCache(cache_dir=tmp_path)
        filepath = "/tmp/test.py"
        cache.mark_valid(filepath, _VALID_PYTHON)
        cache.mark_valid(filepath, _VALID_PYTHON_CHANGED)
        assert cache.is_valid(filepath, _VALID_PYTHON_CHANGED)


# ---------------------------------------------------------------------------
# 2. Invalidation
# ---------------------------------------------------------------------------

class TestASTHashCacheInvalidation:
    """Testes de invalidation."""

    def test_invalidate_removes_entry(self, tmp_path: Path) -> None:
        """invalidate() remove a entry do cache."""
        cache = ASTHashCache(cache_dir=tmp_path)
        filepath = "/tmp/test.py"
        cache.mark_valid(filepath, _VALID_PYTHON)
        assert cache.is_valid(filepath, _VALID_PYTHON)
        cache.invalidate(filepath)
        assert not cache.is_valid(filepath, _VALID_PYTHON)

    def test_clear_removes_all(self, tmp_path: Path) -> None:
        """clear() limpa todo o cache."""
        cache = ASTHashCache(cache_dir=tmp_path)
        cache.mark_valid("/tmp/a.py", _VALID_PYTHON)
        cache.mark_valid("/tmp/b.py", _VALID_PYTHON)
        cache.clear()
        assert not cache.is_valid("/tmp/a.py", _VALID_PYTHON)
        assert not cache.is_valid("/tmp/b.py", _VALID_PYTHON)


# ---------------------------------------------------------------------------
# 3. Persistência em disco
# ---------------------------------------------------------------------------

class TestASTHashCachePersistence:
    """Testes de persistência no disco."""

    def test_cache_survives_reload(self, tmp_path: Path) -> None:
        """Cache persiste entre instâncias (disco)."""
        cache1 = ASTHashCache(cache_dir=tmp_path)
        cache1.mark_valid("/tmp/test.py", _VALID_PYTHON)

        # Nova instância (recarrega do disco)
        cache2 = ASTHashCache(cache_dir=tmp_path)
        assert cache2.is_valid("/tmp/test.py", _VALID_PYTHON)

    def test_corrupted_cache_falls_back(self, tmp_path: Path) -> None:
        """Cache corrompido → fallback graceful."""
        cache_dir = tmp_path
        cache_file = cache_dir / "ast_hashes.json"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("NOT JSON {{{", encoding="utf-8")

        cache = ASTHashCache(cache_dir=cache_dir)
        # Não deve crashar
        assert not cache.is_valid("/tmp/test.py", _VALID_PYTHON)
        # Agora mark funciona
        cache.mark_valid("/tmp/test.py", _VALID_PYTHON)
        assert cache.is_valid("/tmp/test.py", _VALID_PYTHON)


# ---------------------------------------------------------------------------
# 4. Thread safety
# ---------------------------------------------------------------------------

class TestASTHashCacheThreadSafety:
    """Testes de concorrência."""

    def test_concurrent_marks(self, tmp_path: Path) -> None:
        """Múltiplas threads fazendo mark não causam crash."""
        cache = ASTHashCache(cache_dir=tmp_path)
        errors: list[str] = []

        def worker(i: int) -> None:
            try:
                for j in range(50):
                    filepath = f"/tmp/test_{i}_{j}.py"
                    cache.mark_valid(filepath, f"x = {j}\n")
                    cache.is_valid(filepath, f"x = {j}\n")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"

    def test_concurrent_read_write(self, tmp_path: Path) -> None:
        """Leituras e escritas concorrentes não corrompem."""
        cache = ASTHashCache(cache_dir=tmp_path)
        # Pré-popula
        for i in range(100):
            cache.mark_valid(f"/tmp/test_{i}.py", f"x = {i}\n")

        errors: list[str] = []

        def reader() -> None:
            try:
                for i in range(100):
                    cache.is_valid(f"/tmp/test_{i}.py", f"x = {i}\n")
            except Exception as e:
                errors.append(f"reader: {e}")

        def writer() -> None:
            try:
                for i in range(100):
                    cache.mark_valid(f"/tmp/new_{i}.py", f"y = {i}\n")
            except Exception as e:
                errors.append(f"writer: {e}")

        threads = [threading.Thread(target=reader) for _ in range(3)]
        threads += [threading.Thread(target=writer) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent errors: {errors}"


# ---------------------------------------------------------------------------
# 5. Integração com ast_guard
# ---------------------------------------------------------------------------

class TestASTCacheIntegration:
    """Testes de integração com validate_python_syntax_cached."""

    def test_cached_validation_hit(self, tmp_path: Path) -> None:
        """Validação com cache hit → bypass."""
        from jarvis.core.ast_guard import validate_python_syntax_cached

        filepath = str(tmp_path / "test.py")
        # Primeira validação → cache miss → ast.parse()
        is_valid, _ = validate_python_syntax_cached(_VALID_PYTHON, filepath)
        assert is_valid

        # Segunda validação → cache hit → bypass
        is_valid, _ = validate_python_syntax_cached(_VALID_PYTHON, filepath)
        assert is_valid

    def test_cached_validation_miss(self, tmp_path: Path) -> None:
        """Conteúdo muda → revalidação."""
        from jarvis.core.ast_guard import validate_python_syntax_cached

        filepath = str(tmp_path / "test.py")
        validate_python_syntax_cached(_VALID_PYTHON, filepath)

        # Conteúdo mudou → cache miss → revalida
        is_valid, _ = validate_python_syntax_cached(_VALID_PYTHON_CHANGED, filepath)
        assert is_valid

    def test_cached_validation_invalid(self, tmp_path: Path) -> None:
        """Código inválido → NÃO grava no cache."""
        from jarvis.core.ast_guard import validate_python_syntax_cached

        filepath = str(tmp_path / "test.py")
        is_valid, error = validate_python_syntax_cached(_INVALID_PYTHON, filepath)
        assert not is_valid
        assert error

        # Próxima validação com o mesmo código inválido → deve revalidar (não bater)
        # (porque o cache não gravou o hash inválido)
        is_valid2, _ = validate_python_syntax_cached(_INVALID_PYTHON, filepath)
        assert not is_valid2

    def test_no_filepath_fallback(self) -> None:
        """Sem filepath → fallback sem cache."""
        from jarvis.core.ast_guard import validate_python_syntax_cached

        is_valid, _ = validate_python_syntax_cached(_VALID_PYTHON)
        assert is_valid

    def test_invalid_without_cache(self, tmp_path: Path) -> None:
        """Código inválido sem filepath → detecta erro."""
        from jarvis.core.ast_guard import validate_python_syntax_cached

        is_valid, error = validate_python_syntax_cached(_INVALID_PYTHON, str(tmp_path / "test.py"))
        assert not is_valid
        assert "Linha" in error


# ---------------------------------------------------------------------------
# 6. Estatísticas
# ---------------------------------------------------------------------------

class TestASTCacheStats:
    """Testes de estatísticas."""

    def test_stats_empty(self, tmp_path: Path) -> None:
        """Cache vazio → stats corretas."""
        cache = ASTHashCache(cache_dir=tmp_path)
        stats = cache.stats()
        assert stats["entries"] == 0
        assert not stats["exists"]

    def test_stats_after_marks(self, tmp_path: Path) -> None:
        """Após marks → stats refletem entries."""
        cache = ASTHashCache(cache_dir=tmp_path)
        cache.mark_valid("/tmp/a.py", _VALID_PYTHON)
        cache.mark_valid("/tmp/b.py", _VALID_PYTHON)
        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["exists"]


# ---------------------------------------------------------------------------
# 7. Edge cases
# ---------------------------------------------------------------------------

class TestASTCacheEdgeCases:
    """Edge cases do cache."""

    def test_empty_content(self, tmp_path: Path) -> None:
        """Conteúdo vazio → hash válido."""
        cache = ASTHashCache(cache_dir=tmp_path)
        cache.mark_valid("/tmp/test.py", "")
        assert cache.is_valid("/tmp/test.py", "")

    def test_unicode_content(self, tmp_path: Path) -> None:
        """Conteúdo com unicode → hash consistente."""
        cache = ASTHashCache(cache_dir=tmp_path)
        content = "# comentário em PT-BR: ação, manhã, café\nx = 'olá'\n"
        cache.mark_valid("/tmp/test.py", content)
        assert cache.is_valid("/tmp/test.py", content)

    def test_very_long_content(self, tmp_path: Path) -> None:
        """Conteúdo longo (100KB) → hash rápido."""
        cache = ASTHashCache(cache_dir=tmp_path)
        content = "x = 1\n" * 20000  # ~120KB
        cache.mark_valid("/tmp/test.py", content)
        assert cache.is_valid("/tmp/test.py", content)

    def test_special_characters_in_path(self, tmp_path: Path) -> None:
        """Paths com caracteres especiais."""
        cache = ASTHashCache(cache_dir=tmp_path)
        filepath = "/tmp/test file (1).py"
        cache.mark_valid(filepath, _VALID_PYTHON)
        assert cache.is_valid(filepath, _VALID_PYTHON)
