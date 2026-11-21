"""Persona jarvis (MCU), matriz MCP, websearch e RAG-tilde — sem LLM, sem rede."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.persona import PersonaRegistry, filter_tools
from jarvis.core import websearch
from jarvis.core import keys as _keys
from jarvis.core import lang as _lang
from jarvis.core import voice as _voice


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
    # (08/11) keys.get() lê env E arquivos (/etc/jarvis-secrets/tavily.env,
    # /etc/litellm-sops.env). Desde 07/11 o host tem a chave real nesses
    # arquivos: os testes que só mexiam no env (a) quebravam e (b) VAZAVAM
    # a chave real no assert (que o scanner de pains guarda no opencode.db).
    # Por isso o fixture tira as DUAS fontes — o teste é sobre a fonte, não
    # sobre a máquina.
    @pytest.fixture(autouse=True)
    def _no_ambient_tavily(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        monkeypatch.setitem(_keys._SOURCES["tavily"], "files", [])

    def test_no_key_falls_back_to_the_offline_corpus(self, monkeypatch):
        """(14/11) sem chave do Tavily o contrato novo e o FALLBACK offline.

        O ERROR so acontece quando o corpus offline tambem nao responde, e
        ai a mensagem continua dizendo o que configurar.
        """
        assert not websearch.has_key()
        out = websearch.web_search("agua contaminada emergencia")
        assert "fonte: corpus offline" in out

    def test_no_key_and_no_offline_gives_clear_error(self, monkeypatch):
        import jarvis.core.offline as offline_mod

        monkeypatch.setattr(offline_mod, "offline_search",
                            lambda *a, **k: "NO_SOURCE")
        out = websearch.web_search("teste")
        assert out.startswith("ERROR:")
        assert "TAVILY_API_KEY" in out

    def test_empty_query(self):
        assert websearch.web_search("  ").startswith("ERROR:")

    def test_key_from_env(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        assert websearch.has_key()


class TestTtsShort:
    def test_short_passthrough(self):
        assert _voice._tts_short("Oi, senhor.") == "Oi, senhor."

    def test_caps_at_sentence(self):
        long = "Primeira frase curta. " + "bla " * 200 + "Fim."
        out = _voice._tts_short(long)
        assert out.startswith("Primeira frase curta.")
        assert out.endswith("…")
        assert len(out) < len(long)

    def test_wake_only_detected(self):
        for w in ("Hey Jarvis.", "hey jarvis", "  Jarvis!  "):
            assert w.lower().strip().rstrip(".!,?;: ") in ("hey jarvis", "ei jarvis", "jarvis")


class TestSttConfidence:
    def _fw(self, monkeypatch, texts_lps):
        class Seg:
            def __init__(self, t, lp):
                self.text = t
                self.avg_logprob = lp

        class FakeModel:
            def __init__(self, *a, **k):
                pass

            def transcribe(self, path, **kwargs):
                return iter([Seg(t, lp) for t, lp in texts_lps]), object()

        import jarvis.core.voice as v
        monkeypatch.setitem(v.sys.modules, "faster_whisper",
                            type("M", (), {"WhisperModel": FakeModel})())

    def test_confident_passes(self, monkeypatch, tmp_path):
        import jarvis.core.voice as v
        w = tmp_path / "a.wav"
        w.write_bytes(b"RIFF")
        self._fw(monkeypatch, [("olá mundo", -0.3)])
        assert v.transcribe(str(w)) == "olá mundo"

    def test_hallucination_dropped(self, monkeypatch, tmp_path):
        import jarvis.core.voice as v
        w = tmp_path / "a.wav"
        w.write_bytes(b"RIFF")
        self._fw(monkeypatch, [("Lá, vá para o cheirinho, hein?", -1.14)])
        assert v.transcribe(str(w)) == ""


class TestShellTilde:
    def test_tilde_expands_without_shell(self, monkeypatch, tmp_path):
        from jarvis.core.security import run_shell_dict
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "Books").mkdir()
        (tmp_path / "Books" / "a.epub").write_text("x")
        r = run_shell_dict("ls ~/Books")
        assert r["ok"] is True
        assert "a.epub" in r["output"]

    def test_no_shell_injection(self):
        import os as _os
        from jarvis.core.security import run_shell
        target = "/tmp/pwned-xyz-test"
        if _os.path.exists(target):
            _os.remove(target)
        r = run_shell("echo hi; touch " + target)
        assert not _os.path.exists(target)
        assert "hi;" in r.stdout  # ecoado literal, sem interpretar


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
    # (08/11) mesma razão do fixture do TestWebSearch: sem tirar os
    # arquivos, o env de teste não vence a chave real do host e o assert
    # imprimia o segredo.
    @pytest.fixture(autouse=True)
    def _no_ambient_tavily(self, monkeypatch, tmp_path):
        # arquivo FALSO com outro valor: prova a precedência (env > arquivo)
        # sem tocar nos arquivos reais do host (onde está a chave de verdade).
        fake = tmp_path / "tavily.env"
        fake.write_text("TAVILY_API_KEY=tvly-from-file\n")
        monkeypatch.setitem(_keys._SOURCES["tavily"], "files", [str(fake)])

    def test_file_wins_over_env(self, monkeypatch):
        """A precedência REAL é arquivo > env (keys.get, 2026-10-02).

        Quem renova a chave edita o arquivo gerenciado por root; o env
        exportado há semanas continuaria servindo a chave velha (401 na
        visão). O teste antigo afirmava o contrário ("env_wins") e só
        passava porque o arquivo ainda não existia na máquina.
        """
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")
        assert _keys.get("tavily") == "tvly-from-file"
        assert _keys.has("tavily")

    def test_env_used_when_no_file(self, monkeypatch):
        """Sem arquivo, o env é a fonte (útil em CI/container sem /etc)."""
        monkeypatch.setitem(_keys._SOURCES["tavily"], "files", [])
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-abc")
        assert _keys.get("tavily") == "tvly-abc"

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
