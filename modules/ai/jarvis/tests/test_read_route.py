"""Contratos da rota READ + tool read_file do Agent (missão CASE 1/5).

Política: EXACT KNOWN FILE → read_file (zero RAG, zero LLM quando o path é
extraível). Pedidos compostos/perguntas seguem para RAG/agent.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from jarvis.core.agent import Agent
from jarvis.core.config import Config
from jarvis.core.router import handle_read, route_request


@pytest.fixture
def agent_cfg(tmp_path: Path) -> Config:
    """Config com state_dir isolado: Agent nunca toca $HOME (sandbox-safe)."""
    return replace(Config(), state_dir=tmp_path / "state")


# ---------------------------------------------------------------------------
# Classificação: leitura direta
# ---------------------------------------------------------------------------


def test_route_read_exact_file() -> None:
    for text in [
        "leia o arquivo README.md",
        "leia README.md",
        "ler o arquivo config.py",
        "read the file main.py",
        "cat /tmp/notas.txt",
        "leia ./docs/guia.md",
    ]:
        r = route_request(text)
        assert r.handler == "read", text
        assert r.hints.get("path"), text


def test_route_read_extracts_path() -> None:
    assert route_request("leia o arquivo README.md").hints["path"] == "README.md"
    assert route_request("cat /tmp/notas.txt").hints["path"] == "/tmp/notas.txt"
    assert route_request("leia ./docs/guia.md").hints["path"] == "./docs/guia.md"


def test_route_read_does_not_steal_rag() -> None:
    # Perguntas sobre conteúdo continuam no RAG (contrato pré-existente).
    assert route_request("me mostra o content de default.nix").handler == "rag"
    assert route_request("o que tem no flake.nix").handler == "rag"
    assert route_request("onde está implementado o wakeword?").handler == "rag"
    assert route_request("qual função implementa o hybrid search no repo?").handler == "rag"


def test_route_read_compound_goes_to_agent() -> None:
    # "leia X e explique" precisa de raciocínio → agent (com read_file tool).
    assert route_request("leia o arquivo config.py e me explique como funciona").handler == "agent"
    assert route_request("leia main.py e resuma o que ele faz").handler == "agent"


def test_route_read_without_path_falls_through() -> None:
    # Verbo de leitura sem path extraível → não é read (cai no RAG/agent).
    r = route_request("leia com atenção")
    assert r.handler != "read"


# ---------------------------------------------------------------------------
# handle_read: leitura direta
# ---------------------------------------------------------------------------


def test_handle_read_tmp_file(tmp_path: Path) -> None:
    f = tmp_path / "nota.txt"
    f.write_text("linha um\nlinha dois\n", encoding="utf-8")
    out = handle_read(str(f))
    assert out["route"] == "read"
    assert out["error"] is None
    assert out["total_lines"] == 2
    assert "linha um" in out["content"]


def test_handle_read_missing_file() -> None:
    out = handle_read("/nao/existe-xyz.txt")
    assert out["route"] == "read"
    assert out["content"] == ""
    assert out["error"]


# ---------------------------------------------------------------------------
# Agent: tool read_file nativa via LLM mockado
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, Any]:
        return self._payload


class _ReadProbeSession:
    """Primeiro turno: tool call nativa read_file. Segundo: resposta final."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.calls = 0
        self.last_payload: dict[str, Any] = {}

    def post(self, url: str, json: dict | None = None, timeout: object = None, **kw: object) -> Any:
        self.calls += 1
        self.last_payload = dict(json or {})
        if self.calls == 1:
            msg: dict[str, Any] = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-read-1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": self.path},
                    },
                }],
            }
        else:
            msg = {"role": "assistant", "content": "arquivo lido e resumido"}
        return _FakeResponse({"choices": [{"message": msg}]})


def test_agent_executes_read_file_tool(tmp_path: Path, agent_cfg: Config) -> None:
    f = tmp_path / "alvo.txt"
    f.write_text("conteudo secreto 123\n", encoding="utf-8")
    probe = _ReadProbeSession(str(f))
    agent = Agent(agent_cfg, session=probe)
    result = agent.run("leia o arquivo alvo")

    assert result.turns >= 2
    assert result.commands_run == []  # leitura não é comando shell
    assert "arquivo lido e resumido" in result.final_response
    # O payload anunciado ao LLM inclui read_file (CASE 1: sem RAG).
    tool_names = [t["function"]["name"] for t in probe.last_payload.get("tools", [])]
    assert "read_file" in tool_names


def test_agent_read_file_missing_returns_error(tmp_path: Path, agent_cfg: Config) -> None:
    probe = _ReadProbeSession("/nao/existe-xyz.txt")
    agent = Agent(agent_cfg, session=probe)
    result = agent.run("leia o que não existe")
    # Sem crash; o erro vira tool result e o loop conclui.
    assert result.turns >= 1
    assert "arquivo lido e resumido" in result.final_response
