"""O harness tem que registrar em arquivo (o dono perde os erros no TUI)."""
import io

from jarvis.cli import dev


def test_ttee_writes_to_every_stream():
    a, b = io.StringIO(), io.StringIO()
    dev._Tee(a, b).write("erro X")
    assert a.getvalue() == "erro X"
    assert b.getvalue() == "erro X"


def test_devlog_writes_line(tmp_path, monkeypatch):
    log = tmp_path / "dev.log"
    monkeypatch.setitem(dev._LOG, "path", log)
    dev._devlog("olá")
    assert "olá" in log.read_text()


def test_tavily_resolves_from_litellm_env(monkeypatch, tmp_path):
    from jarvis.core import keys
    env = tmp_path / "litellm.env"
    env.write_text('export TAVILY_API_KEY="tvly-fake-123"\n')
    monkeypatch.setitem(keys._SOURCES["tavily"], "files", [str(env)])
    assert keys.get("tavily") == "tvly-fake-123"
