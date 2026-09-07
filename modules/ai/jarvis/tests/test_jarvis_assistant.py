"""Persona jarvis (MCU), matriz MCP, websearch e RAG-tilde — sem LLM, sem rede."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.persona import PersonaRegistry, filter_tools
from jarvis.core import websearch


class TestJarvisPersona:
    def test_jarvis_exists_with_mcu_voice(self):
        p = PersonaRegistry().get("jarvis")
        assert p is not None
        assert "senhor" in p.system_prompt_additions.lower()
        assert "rag" in p.system_prompt_additions.lower()
        assert "web_search" in p.system_prompt_additions

    def test_jarvis_is_default(self):
        assert PersonaRegistry().select_for_task("qualquer coisa").id == "jarvis"
        assert PersonaRegistry().select_for_task("").id == "jarvis"

    def test_jarvis_tag(self):
        assert "default" in PersonaRegistry().get("jarvis").tags


class TestCapabilityMatrix:
    NAMES = ["read_file", "write_file", "execute_shell", "web_search",
             "semantic_search", "rag_index", "capture_screen", "nix_eval"]

    def test_jarvis_gets_all(self):
        p = PersonaRegistry().get("jarvis")
        assert filter_tools(self.NAMES, p) == self.NAMES
        assert filter_tools(self.NAMES, None) == self.NAMES

    def test_researcher_filtered(self):
        p = PersonaRegistry().get("researcher")
        got = filter_tools(self.NAMES, p)
        assert "web_search" in got
        assert "read_file" in got
        assert "write_file" in got  # researcher pode escrever (policy)
        assert "execute_shell" not in got
        assert "capture_screen" not in got
        assert "nix_eval" not in got


class TestWebSearch:
    def test_no_key_gives_clear_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(websearch, "_KEY_FILE", tmp_path / "nope.env")
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert not websearch.has_key()
        out = websearch.web_search("teste")
        assert out.startswith("ERROR:")
        assert "TAVILY_API_KEY" in out

    def test_empty_query(self):
        assert websearch.web_search("  ").startswith("ERROR:")

    def test_key_from_env(self, monkeypatch, tmp_path):
        monkeypatch.setattr(websearch, "_KEY_FILE", tmp_path / "nope.env")
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        assert websearch.has_key()


class TestRagTilde:
    def test_iter_expands_tilde(self, monkeypatch, tmp_path):
        import pytest
        pytest.importorskip("requests")  # cadeia providers.* exige requests
        monkeypatch.setenv("HOME", str(tmp_path))
        sub = tmp_path / "proj"
        sub.mkdir()
        (sub / "main.py").write_text("print('oi')\n")
        from jarvis.core.rag import iter_indexable_files
        got = list(iter_indexable_files("~/proj"))
        assert got == [str(sub / "main.py")]
