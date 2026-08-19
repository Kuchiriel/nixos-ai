"""Cliente MCP (Model Context Protocol) stdio mínimo, sem dependências externas.

Implementa o suficiente do protocolo para consumir servidores MCP via
JSON-RPC 2.0 sobre stdin/stdout:

  - `initialize` + `notifications/initialized` (handshake)
  - `tools/list`          → descoberta de ferramentas
  - `tools/call`          → execução de ferramenta

Foi validado contra o `mcp-nixos` (2.4.3, em nixpkgs 26.05): expõe 2 tools
(`nix`, `nix_versions`) e responde a consultas de packages/options reais.

Uso no JARVIS: o `Agent` carrega as tools MCP (ex: nixos) e as expõe ao LLM
como function tools junto com `execute_shell` — mas com a diferença de que
as tools MCP são **read-only** (consulta) e passam pelo mesmo audit trail.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import threading
from typing import Any, Callable


class MCPError(RuntimeError):
    pass


class MCPClient:
    """Cliente MCP sobre um subprocess (stdio transport)."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        protocol_version: str = "2024-11-05",
        name: str = "jarvis",
        version: str = "0.1.0",
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._protocol_version = protocol_version
        self._client_info = {"name": name, "version": version}
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, Any] = {}
        self._reader: threading.Thread | None = None

    # --- lifecycle ---

    def start(self) -> None:
        """Inicia o subprocess e faz o handshake MCP."""
        if self._proc is not None:
            return
        argv = [self._command, *self._args]
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=self._env,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        result = self._request("initialize", {
            "protocolVersion": self._protocol_version,
            "capabilities": {},
            "clientInfo": self._client_info,
        })
        self._notify("notifications/initialized", {})
        return result  # type: ignore[return-value]

    def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
            self._proc = None

    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # --- descoberta de tools ---

    def list_tools(self) -> list[dict[str, Any]]:
        """Retorna as tools expostas pelo servidor (formato MCP)."""
        result = self._request("tools/list", {})
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Executa uma tool e retorna o conteúdo da resposta."""
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        # MCP: result.content = [{type: "text", text: "..."}] ou isError
        if result.get("isError"):
            texts = _content_text(result.get("content", []))
            raise MCPError(f"tool {name} falhou: {texts or 'sem detalhe'}")
        return _content_text(result.get("content", []))

    # --- JSON-RPC ---

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP client não iniciado")
        with self._lock:
            msg_id = self._next_id
            self._next_id += 1
            self._pending[msg_id] = None
            payload = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}) + "\n"
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()

        # espera a resposta correspondente
        for _ in range(600):  # até ~60s
            with self._lock:
                got = self._pending.get(msg_id)
            if got is not None:
                with self._lock:
                    del self._pending[msg_id]
                if "error" in got:
                    raise MCPError(f"MCP {method}: {got['error']}")
                return got.get("result", {})
            if self._proc.poll() is not None:
                raise MCPError(f"MCP process terminou durante {method}")
            threading.Event().wait(0.1)
        raise MCPError(f"timeout aguardando {method}")

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPError("MCP client não iniciado")
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
        self._proc.stdin.write(payload)
        self._proc.stdin.flush()

    def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("method"):  # notificação do servidor (ex: logging) — ignora
                continue
            msg_id = msg.get("id")
            if msg_id is not None:
                with self._lock:
                    if msg_id in self._pending:
                        self._pending[msg_id] = msg


def _content_text(content: list[dict[str, Any]] | None) -> str:
    if not content:
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif isinstance(item, dict) and item.get("type") == "resource":
            parts.append(str(item))
    return "\n".join(parts)


def parse_command(value: str) -> tuple[str, list[str]]:
    """Divide \"cmd arg1 arg2\" em (comando, args) — ex: \"nix run ... --\"."""
    parts = shlex.split(value)
    if not parts:
        raise MCPError("comando MCP vazio")
    return parts[0], parts[1:]


# ---------------------------------------------------------------------------
# Conveniência: tools MCP → formato function tools do chat completions
# ---------------------------------------------------------------------------


def to_function_tools(mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converte tools MCP no formato `tools` da API OpenAI-compatível."""
    out = []
    for t in mcp_tools:
        schema = t.get("inputSchema") or {"type": "object", "properties": {}}
        out.append({
            "type": "function",
            "function": {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "parameters": schema,
            },
        })
    return out


def from_function_call(name: str, arguments: str) -> dict[str, Any]:
    """Normaliza um function call do LLM para arguments dict (json ou vazio)."""
    if not arguments or not arguments.strip():
        return {}
    try:
        parsed = json.loads(arguments)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


# Re-export para uso no agente
Executor = Callable[[str, dict[str, Any]], Any]
