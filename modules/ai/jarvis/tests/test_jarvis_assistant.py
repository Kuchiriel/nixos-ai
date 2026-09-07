"""Persona jarvis (MCU), matriz MCP, websearch e RAG-tilde — sem LLM, sem rede."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.persona import PersonaRegistry, filter_tools
from jarvis.core import websearch
from jarvis.core import keys as _keys
from jarvis.core import lang as _lang


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
    def test_no_key_gives_clear_error(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        assert not websearch.has_key()
        out = websearch.web_search("teste")
        assert out.startswith("ERROR:")
        assert "TAVILY_API_KEY" in out

    def test_empty_query(self):
        assert websearch.web_search("  ").startswith("ERROR:")

    def test_key_from_env(self, monkeypatch):
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


class TestSecrets:
    def test_env_wins(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")
        assert _keys.get("tavily") == "tvly-abc"
        assert _keys.has("tavily")

    def test_missing_is_empty(self, monkeypatch):
        for v in ("TAVILY_API_KEY", "HMD_API_ACCESS_TOKEN"):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("HOME", "/nonexistent-xyz")
        assert _keys.get("definitely-not-a-key") == ""

    def test_require_raises_clear(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setenv("HOME", "/nonexistent-xyz")
        import pytest
        # /etc legível só como root: aqui deve levantar (ou achar nada)
        try:
            val = _keys.require("tavily")
            assert val  # achou via arquivo legível
        except ValueError as e:
            assert "TAVILY_API_KEY" in str(e)


class TestLang:
    def test_default_pt(self, monkeypatch):
        monkeypatch.delenv("JARVIS_LANG", raising=False)
        monkeypatch.setenv("LANG", "C.UTF-8")
        monkeypatch.delenv("LC_ALL", raising=False)
        assert _lang.lang() == "pt"
        assert _lang.stt_code() == "pt"
        assert _lang.tts_code() == "p"
        assert "PT-BR" in _lang.name()

    def test_override_en(self, monkeypatch):
        monkeypatch.setenv("JARVIS_LANG", "en")
        assert _lang.lang() == "en"
        assert _lang.tts_code() == "a"
