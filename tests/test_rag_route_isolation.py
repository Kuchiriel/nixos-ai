"""Garante que colecao isolada nao escreve em `books` (24/11)."""
import dataclasses
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from jarvis.core.config import get_config
from jarvis.core.rag import HybridIndexer


class RouteIsolationTests(unittest.TestCase):
    def _target(self, path: str, collection: str) -> str:
        cfg = dataclasses.replace(get_config(), qdrant_collection_code=collection)
        idx = HybridIndexer(cfg)
        # captura o collection usado no upsert sem gravar
        calls = []
        with patch.object(idx._store, "upsert",
                          side_effect=lambda c, p: calls.append(c)):
            idx.ensure_collection()
            idx.index_file(path, content="# teste de roteamento\ntexto", force=True)
        return calls[0] if calls else ""

    def test_books_path_with_isolated_collection_stays_isolated(self):
        target = str(pathlib.Path.home() / "Books" / "test-route.md")
        got = self._target(target, "jarvis_test_route_isolation")
        self.assertEqual("jarvis_test_route_isolation", got)

    def test_default_collection_keeps_books_routing(self):
        target = str(pathlib.Path.home() / "Books" / "test-route.md")
        got = self._target(target, "code_index")
        self.assertEqual("books", got)


if __name__ == "__main__":
    unittest.main()
