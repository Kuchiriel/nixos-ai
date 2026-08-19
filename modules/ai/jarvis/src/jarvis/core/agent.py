"""Agente de tool calling do JARVIS — implementação própria, inspirada no
conceito de agentes terminais (ex: `earendil-works/pi`, empacotado pelo
`pi.nix` do lukasl-dev). NÃO usa o código do pi: o loop de tool calling é
escrito do zero para o nosso stack, com as três camadas de segurança que o
host precisa (o pi executa qualquer comando sem aprovação):

  1. **Allowlist** — comandos read-only (diagnóstico) sempre permitidos;
  2. **Aprovação** — qualquer comando fora da allowlist exige confirmação
     humana (stdin ou botões no Telegram) quando `--approve` é passado;
     sem `--approve`, é negado;
  3. **Audit trail** — toda execução (ou negação) vai para um JSONL no
     state_dir, com timestamp, comando, exit code e resultado truncado.

Extras do JARVIS: memória episódica (lição automática quando um comando
falha), cliente MCP próprio (mcp-nixos, anti-alucinação) e perfis adaptativos
por modelo.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from typing import Any

import requests

from jarvis.core.config import Config, get_config
from jarvis.providers.mcp import MCPClient, MCPError, parse_command, to_function_tools

# ---------------------------------------------------------------------------
# Constantes (espelho do pi.nix, parametrizadas via Config/env)
# ---------------------------------------------------------------------------

MAX_TURNS = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", "8"))
MAX_REPAIR_RETRIES = int(os.environ.get("JARVIS_AGENT_MAX_REPAIR_RETRIES", "2"))

# Comandos read-only seguros — permitidos sem aprovação (diagnóstico/self-heal).
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
    "df", "free", "ps", "pgrep", "ss", "ip", "uname", "uptime",
    "date", "echo", "hostname", "id", "whoami",
    "systemctl is-active", "systemctl status", "systemctl list-units",
    "journalctl", "nix flake check", "nix eval", "nix build --dry-run",
    "nixos-rebuild dry-build", "nixos-rebuild build",
)

# Padrões de tool_call que o Qwen2.5 vaza como texto puro no `content`
# (bug documentado com llama.cpp + tool_choice=auto). Além da tag nativa
# <tool_call>...</tool_call>, o modelo costuma devolver o JSON dentro de um
# code block (```json ... ```) ou solto no texto — e o JSON tem objetos
# ANINHADOS ("arguments": {...}), que um regex simples de chaves não captura.
# A extração usa balanceamento de chaves (veja extract_fallback_tool_call).
TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
CODEBLOCK_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": (
                "Execute a shell command on the local NixOS system. "
                "Read-only diagnostic commands are allowed; commands with "
                "side effects will require human approval."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "string",
                        "description": "The exact shell command to execute.",
                    }
                },
                "required": ["cmd"],
            },
        },
    }
]


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


class AuditLog:
    """JSONL de auditoria: uma linha por execução/negação de tool."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def _append(self, entry: dict[str, Any]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record(self, *, cmd: str, allowed: bool, approved: bool, exit_code: int | None, output: str) -> None:
        self._append({
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "cmd": cmd,
            "allowed": allowed,
            "approved": approved,
            "exit_code": exit_code,
            "output_preview": output[:500],
        })


# ---------------------------------------------------------------------------
# Execução segura de comandos
# ---------------------------------------------------------------------------


def command_allowed(cmd: str, allowed_prefixes: tuple[str, ...] | None = None) -> bool:
    """True se o comando começa com um prefixo read-only da allowlist."""
    prefixes = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES
    stripped = cmd.strip()
    if not stripped:
        return False
    return any(stripped.startswith(p) for p in prefixes)


def run_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Executa via `shlex` (sem shell=True) — mais seguro e auditável."""
    argv = shlex.split(cmd)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def human_approve(cmd: str, prompt: str = "Permitir execução? [y/N] ") -> bool:
    """Pede confirmação humana no stdin."""
    print(f"⚠  Comando com efeito: {cmd}")
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes", "s", "sim")


# ---------------------------------------------------------------------------
# Perfis adaptativos (7B na VM vs 32B bare-metal)
# ---------------------------------------------------------------------------


def detect_profile(model_id: str) -> dict[str, Any]:
    m = model_id.lower()
    if "32b" in m or "30b" in m:
        return {
            "name": "large",
            "temperature": 0.0,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens_per_turn": 768,
        }
    if "7b" in m:
        return {
            "name": "small",
            "temperature": 0.0,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens_per_turn": 1024,
        }
    return {
        "name": "default",
        "temperature": 0.0,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_tokens_per_turn": 1024,
    }


def _extract_json_object(text: str) -> str | None:
    """Extrai o primeiro objeto JSON balanceado de um texto.

    Percorre o texto procurando um `{` que inicie um objeto com
    `"name"` e `"arguments"` (shape de tool call) e faz o balanceamento
    de chaves/colchetes/strings para obter o JSON completo — inclusive
    com objetos aninhados dentro de `arguments`.
    """
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth_braces = 0
        depth_brackets = 0
        in_string = False
        escaped = False
        j = i
        while j < n:
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth_braces += 1
                elif ch == "}":
                    depth_braces -= 1
                    if depth_braces == 0:
                        candidate = text[i : j + 1]
                        if '"name"' in candidate and '"arguments"' in candidate:
                            return candidate
                        break
                elif ch == "[":
                    depth_brackets += 1
                elif ch == "]":
                    depth_brackets -= 1
            j += 1
        i = j + 1
    return None


def extract_fallback_tool_call(content: str | None) -> dict[str, Any] | None:
    """Recupera tool_call vazado como texto (formato nativo do Qwen)."""
    if not content:
        return None
    # 1) tag nativa <tool_call>{...}</tool_call>
    match = TOOL_CALL_TAG_RE.search(content)
    # 2) JSON em code block ```json {...} ```
    if not match:
        match = CODEBLOCK_JSON_RE.search(content)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("name"):
            return _normalize_tool_call(parsed)
    # 3) JSON solto no texto (balanceamento de chaves)
    raw = _extract_json_object(content)
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict) and parsed.get("name"):
            return _normalize_tool_call(parsed)
    return None


def _normalize_tool_call(parsed: dict[str, Any]) -> dict[str, Any] | None:
    name = parsed.get("name")
    if not name:
        return None
    arguments = parsed.get("arguments", {})
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    return {"name": name, "arguments": arguments}


# ---------------------------------------------------------------------------
# Loop do agente
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    final_response: str = ""
    turns: int = 0
    commands_run: list[str] = field(default_factory=list)
    commands_denied: list[str] = field(default_factory=list)


class Agent:
    """Loop agente: chat + tools contra um servidor OpenAI-compatível.

    Tools disponíveis:
      - `execute_shell` (allowlist + aprovação + audit)
      - tools MCP read-only (ex: mcp-nixos via `mcp_servers`), que passam
        pelo mesmo audit trail.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        approve: bool = False,
        allowed_prefixes: tuple[str, ...] | None = None,
        audit_path: Path | None = None,
        system_prompt: str | None = None,
        session: requests.Session | None = None,
        mcp_servers: dict[str, str] | None = None,
        memory: Any | None = None,
        approver: Callable[[str], bool] | None = None,
    ) -> None:
        self._cfg = config or Config()
        self._base = self._cfg.llm_base_url.rstrip("/")
        self._approve = approve
        # callable de aprovação — default: terminal (stdin); canais (Telegram)
        # injetam o deles (ex: botões inline)
        self._approver = approver or human_approve
        self._allowed = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES
        self._audit = AuditLog(audit_path)
        self._session = session or requests.Session()
        self._mcp_servers = mcp_servers or {}
        self._memory = memory  # EpisodicMemory opcional (auto-aprendizado)
        self._mcp_clients: dict[str, MCPClient] = {}
        self._mcp_tools: list[dict[str, Any]] = []
        self._system_prompt = system_prompt or (
            "You are JARVIS, a pragmatic system administration assistant on "
            "NixOS. RESPOND ALWAYS IN BRAZILIAN PORTUGUESE (pt-BR), even if "
            "the user writes in English; keep answers concise and direct, "
            "extracting the maximum from the minimum (no filler). "
            "Use the execute_shell tool to gather data or perform actions. "
            "Read-only diagnostic commands run automatically; commands with "
            "side effects require human approval. When you decide to call a "
            "tool, ALWAYS wrap the call exactly as "
            "<tool_call>{\"name\": ..., \"arguments\": {...}}</tool_call> "
            "and never mix a tool call with prose in the same message."
        )

    # --- servidor ---

    def _model_id(self) -> str:
        try:
            resp = self._session.get(f"{self._base}/models", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                return data["data"][0].get("id", "")
        except (requests.RequestException, ValueError):
            pass
        return ""

    def _chat(self, messages: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
        tools = list(TOOLS)
        if self._mcp_tools:
            tools.extend(to_function_tools(self._mcp_tools))
        payload: dict[str, Any] = {
            "model": self._cfg.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": profile["tool_choice"],
            "temperature": profile["temperature"],
            "max_tokens": profile["max_tokens_per_turn"],
            "parallel_tool_calls": profile["parallel_tool_calls"],
            # json_object reduz repair loops em ~50% com SLMs — o modelo
            # gera JSON válido por constrangimento, não por tentativa.
            "response_format": {"type": "json_object"},
        }
        resp = self._session.post(f"{self._base}/chat/completions", json=payload, timeout=self._cfg.llm_timeout)
        resp.raise_for_status()
        return resp.json()

    # --- MCP ---

    def _connect_mcp(self) -> None:
        """Inicia os clientes MCP configurados e descobre as tools."""
        for name, cmdline in self._mcp_servers.items():
            if name in self._mcp_clients:
                continue
            command, args = parse_command(cmdline)
            client = MCPClient(command, args, name="jarvis-agent")
            try:
                client.start()
                tools = client.list_tools()
            except (MCPError, OSError) as exc:
                # MCP indisponível nunca derruba o agente: segue sem as tools
                print(f"[agent] MCP '{name}' indisponível: {exc}", file=sys.stderr)
                client.close()
                continue
            self._mcp_clients[name] = client
            self._mcp_tools.extend(tools)

    def _call_mcp_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Executa uma tool MCP no cliente dono dela. Retorna texto."""
        for client in self._mcp_clients.values():
            try:
                return client.call_tool(name, arguments)
            except MCPError as exc:
                if "tool" not in str(exc):
                    continue
                return f"ERROR: {exc}"
        return f"ERROR: tool MCP desconhecida: {name}"

    def _close_mcp(self) -> None:
        for client in self._mcp_clients.values():
            client.close()
        self._mcp_clients.clear()
        self._mcp_tools = []

    # --- tool ---

    def _execute_tool(self, cmd: str, result: AgentResult) -> str:
        allowed = command_allowed(cmd, self._allowed)
        approved = False
        if not allowed:
            if not self._approve:
                result.commands_denied.append(cmd)
                self._audit.record(cmd=cmd, allowed=False, approved=False, exit_code=None, output="")
                return (
                    f"ERROR: command not in allowlist and approval is disabled "
                    f"(run with --approve to allow human confirmation). "
                    f"Command was: {cmd}"
                )
            if not self._approver(cmd):
                result.commands_denied.append(cmd)
                self._audit.record(cmd=cmd, allowed=False, approved=False, exit_code=None, output="")
                return f"ERROR: command denied by human. Command was: {cmd}"
            approved = True

        result.commands_run.append(cmd)
        try:
            res = run_shell(cmd, timeout=120)
            output = res.stdout if res.returncode == 0 else res.stderr
            if not output.strip():
                output = f"Command executed with exit code {res.returncode}"
            self._audit.record(cmd=cmd, allowed=allowed, approved=approved, exit_code=res.returncode, output=output)
            # auto-aprendizado: comando falhou → grava lição na memória episódica
            if res.returncode != 0 and self._memory is not None:
                self._learn(cmd, output)
            return output
        except subprocess.TimeoutExpired:
            self._audit.record(cmd=cmd, allowed=allowed, approved=approved, exit_code=None, output="[timeout]")
            if self._memory is not None:
                self._learn(cmd, "timeout after 120s")
            return "ERROR: command timed out after 120s."
        except Exception as exc:  # noqa: BLE001 — falha vira mensagem p/ o modelo
            self._audit.record(cmd=cmd, allowed=allowed, approved=approved, exit_code=None, output=str(exc))
            if self._memory is not None:
                self._learn(cmd, str(exc))
            return f"ERROR: {exc}"

    def _learn(self, cmd: str, error_output: str) -> None:
        """Grava uma lição episódica quando um comando falha (experience_buffer)."""
        try:
            self._memory.remember_lesson(
                task=f"agent shell: {cmd}",
                error_pattern=error_output[:200],
                fix="",  # o modelo descobre a correção; lição registra o erro
            )
        except Exception:  # noqa: BLE001 — memória nunca deve quebrar o agente
            pass

    # --- loop principal ---

    def run(self, user_prompt: str) -> AgentResult:
        result = AgentResult()
        self._connect_mcp()
        try:
            return self._run_loop(user_prompt, result)
        finally:
            self._close_mcp()

    def _lessons_block(self, user_prompt: str) -> str:
        """PAST LESSONS da memória episódica como restrições obrigatórias.

        Porta do cascade_planner do legado: o plano/agente deve respeitar
        lições de erros passados antes de agir ("MANDATORY CONSTRAINTS").
        Retorna vazio se não houver memória ou lições relevantes.
        """
        if self._memory is None:
            return ""
        try:
            return self._memory.lessons(user_prompt, top_k=3)
        except Exception:  # noqa: BLE001 — memória nunca deve quebrar o agente
            return ""

    def _run_loop(self, user_prompt: str, result: AgentResult) -> AgentResult:
        profile = detect_profile(self._model_id())
        lessons = self._lessons_block(user_prompt)
        system = self._system_prompt
        if lessons:
            system += (
                "\n\nMANDATORY CONSTRAINTS from past experience — if a PAST LESSON "
                "warns against a specific change or command, you MUST avoid it:\n"
                + lessons
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        repair_attempts = 0

        # O Qwen pequeno (7B) tende a continuar chamando tools mesmo com dados
        # suficientes. No penúltimo turno, injetamos um aviso de "responda já".
        for turn in range(MAX_TURNS):
            if turn == MAX_TURNS - 2 and messages:
                messages.append({
                    "role": "system",
                    "content": (
                        "You already have enough information to answer the user's "
                        "request. STOP calling tools now and give the final answer "
                        "in plain text, using the tool results you already have."
                    ),
                })
            result.turns = turn + 1
            data = self._chat(messages, profile)
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls")

            recovered = False
            if not tool_calls:
                fallback = extract_fallback_tool_call(content)
                if fallback is not None:
                    tool_calls = [{
                        "id": "fallback-0",
                        "type": "function",
                        "function": {
                            "name": fallback["name"],
                            "arguments": json.dumps(fallback["arguments"]),
                        },
                    }]
                    recovered = True

            messages.append({
                "role": "assistant",
                "content": "" if (tool_calls and not recovered) else content,
                "tool_calls": tool_calls,
            })

            if not tool_calls:
                result.final_response = content
                return result

            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                raw_args = tool_call["function"]["arguments"]
                if isinstance(raw_args, (dict, list)):
                    args = raw_args
                elif not raw_args or not raw_args.strip():
                    args = {}
                else:
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        repair_attempts += 1
                        if repair_attempts > MAX_REPAIR_RETRIES:
                            result.final_response = (
                                f"Erro: JSON de argumentos malformado após {MAX_REPAIR_RETRIES} tentativas: {raw_args}"
                            )
                            return result
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", ""),
                            "name": func_name,
                            "content": (
                                f"ERROR: invalid JSON in arguments: {raw_args!r}. "
                                "Reissue the tool call with strictly valid JSON arguments."
                            ),
                        })
                        continue

                if func_name == "execute_shell":
                    output = self._execute_tool(args.get("cmd", ""), result)
                elif self._mcp_clients:
                    output = self._call_mcp_tool(func_name, args)
                else:
                    output = f"Unknown tool: {func_name}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "name": func_name,
                    "content": output,
                })

        result.final_response = (
            f"Erro: número máximo de iterações ({MAX_TURNS}) atingido sem resposta final."
        )
        return result


def main_agent(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis agent [--approve] \"prompt\"."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis agent", description="Agente tool-calling JARVIS")
    parser.add_argument("prompt", help="o que o agente deve fazer")
    parser.add_argument("--approve", action="store_true", help="permite aprovação humana para comandos com efeito")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    args = parser.parse_args(argv)

    cfg = get_config()
    state = cfg.ensure_state_dir()
    agent = Agent(cfg, approve=args.approve, audit_path=state / "agent-audit.jsonl")
    result = agent.run(args.prompt)

    print(result.final_response)
    if result.commands_run:
        print(f"\n# comandos executados ({len(result.commands_run)}):")
        for c in result.commands_run:
            print(f"  · {c}")
    if result.commands_denied:
        print(f"\n# comandos negados ({len(result.commands_denied)}):")
        for c in result.commands_denied:
            print(f"  · {c}")
    if result.commands_denied:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main_agent())
