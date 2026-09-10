"""Book tools do Agent: book_search/book_resume (read-only, sem aprovação)."""
import json as jsonlib

from jarvis.core.agent import Agent
from jarvis.core.config import Config


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class BookSession:
    """Turno 1 emite book_search; turno 2 finaliza com a observation."""

    def __init__(self):
        self.calls = 0
        self.last_tool_result = ""

    def get(self, url, timeout=5):
        return _Resp({"data": [{"id": "x"}]})

    def post(self, url, json=None, timeout=120, **kw):
        self.calls += 1
        msgs = (json or {}).get("messages", [])
        for m in reversed(msgs):
            if m.get("role") == "tool":
                self.last_tool_result = m.get("content", "")
                break
        if self.calls == 1:
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{
                       "id": "call-1", "type": "function",
                       "function": {
                           "name": "book_search",
                           "arguments": jsonlib.dumps(
                               {"query": "dragão", "book": "lotm"})}}]}
        else:
            msg = {"role": "assistant",
                   "content": f"achei: {self.last_tool_result[:60]}"}
        return _Resp({"choices": [{"message": msg}]})


def _hits(*a, **k):
    return [{"book": "lotm", "chapter": 7, "title": "Dragão",
             "score": 0.9, "content": "o dragão cuspiu fogo" * 10}]


def test_exec_book_search_formats(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.audiobook.search_books", _hits)
    out = Agent._exec_book("book_search", {"query": "dragão"})
    assert "lotm cap.7" in out and "dragão" in out


def test_exec_book_resume_formats(monkeypatch) -> None:
    monkeypatch.setattr(
        "jarvis.core.audiobook.resume_book",
        lambda **k: {"ok": True, "book": "lotm", "chapter": 7,
                     "position": 3, "reason": "bookmark"})
    out = Agent._exec_book("book_resume", {"book": "lotm"})
    assert "book=lotm chapter=7 position=3 reason=bookmark" in out


def test_exec_book_no_hits(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.audiobook.search_books",
                        lambda *a, **k: [])
    assert Agent._exec_book("book_search", {"query": "zzz"}) == "no hits"


def test_exec_book_error_is_honest(monkeypatch) -> None:
    def _boom(*a, **k):
        raise RuntimeError("qdrant fora")
    monkeypatch.setattr("jarvis.core.audiobook.search_books", _boom)
    out = Agent._exec_book("book_search", {"query": "x"})
    assert out.startswith("ERROR: book failed:")


def test_agent_loop_runs_book_search(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.audiobook.search_books", _hits)
    cfg = Config()
    agent = Agent(cfg, session=BookSession())
    result = agent.run("onde está a parte do dragão?")
    assert "lotm cap.7" in result.final_response
    assert result.turns == 2
