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
from typing import Callable, Any

# Re-export from security.py for backward compatibility
from jarvis.core.security import command_allowed, has_chaining_operators, run_shell  # noqa: F401


def detect_profile(model_id: str) -> dict[str, Any]:
    """Detect model profile from model name. Used by tests and REPL.

    Analyzes the model ID string to determine the appropriate inference
    profile (large, small, tiny, or default) based on parameter count.

    Args:
        model_id: The identifier of the model (e.g., "llama-3-70b", "qwen-7b").

    Returns:
        A dictionary containing the profile configuration:
        - name (str): Profile category ('large', 'small', 'tiny', 'default').
        - max_tokens (int): Recommended maximum output tokens.
        - max_tokens_per_turn (int): Max tokens per generation turn.
        - temperature (float): Recommended temperature setting.
        - tool_choice (str): Tool choice strategy.
    """
    m = model_id.lower()
    
    # Extract total parameters from name
    total_b_match = re.search(r"(?<![a-z])(\d+(?:\.\d+)?)b(?!\w)", m)
    total_b = float(total_b_match.group(1)) if total_b_match else None
    
    if total_b is not None and total_b >= 30:
        return {"name": "large", "max_tokens": 768, "max_tokens_per_turn": 768, "temperature": 0.0, "tool_choice": "auto"}
    elif total_b is not None and total_b >= 7:
        return {"name": "small", "max_tokens": 1024, "max_tokens_per_turn": 1024, "temperature": 0.0, "tool_choice": "auto"}
    elif total_b is not None and total_b < 7:
        return {"name": "tiny", "max_tokens": 512, "max_tokens_per_turn": 512, "temperature": 0.0, "tool_choice": "none"}
    else:
        return {"name": "default", "max_tokens": 1024, "max_tokens_per_turn": 1024, "temperature": 0.0, "tool_choice": "auto"}


def _normalize_tool_call(tc: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a tool call to a standard format.
    
    Handles:
    - arguments as string (JSON) or dict
    - missing name
    - empty arguments
    - preserves non-dict arguments (lists, numbers)
    
    Raises:
        json.JSONDecodeError: If arguments is an invalid JSON string.
    """
    if not isinstance(tc, dict):
        return None
    
    name = tc.get("name") or tc.get("function", {}).get("name")
    if not name:
        return None
    
    # Get arguments
    args = tc.get("arguments") or tc.get("function", {}).get("arguments", {})
    
    # Parse string arguments
    if isinstance(args, str):
        if not args.strip():
            args = {}
        else:
            args = json.loads(args)  # Raises JSONDecodeError for invalid JSON
    
    # Preserve non-dict types (lists, numbers) - don't force to dict
    
    return {"name": name, "arguments": args}


def _extract_json_object(text: str) -> str | None:
    """Extract a balanced JSON object from text."""
    if not text:
        return None
    # Find first {
    start = text.find('{')
    if start < 0:
        return None
    # Count braces to find matching closing }
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                candidate = text[start:i+1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None
    return None


def extract_fallback_tool_call(text: str | None) -> dict[str, Any] | None:
    """Extract tool call from text when native tool calls fail.
    
    Supports:
    - <tool_call>...</tool_call> format
    - JSON in code blocks
    - Bare JSON inline
    
    Returns normalized tool call with arguments parsed.
    """
    if not text:
        return None
    
    result = None
    
    # Look for <tool_call> format
    match = re.search(r'<tool_call>({.*?})</tool_call>', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Look for JSON in code blocks
    if result is None:
        match = re.search(r'```(?:json)?\s*({\s*"name"\s*:\s*"[^"]+"[^}]*})\s*```', text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    
    # Look for bare JSON with name and arguments
    if result is None:
        match = re.search(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:', text)
        if match:
            start = text.rfind('{', 0, match.start() + 1)
            if start >= 0:
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                result = json.loads(text[start:i+1])
                            except json.JSONDecodeError:
                                pass
                            break
    
    # Normalize: parse string arguments
    if result is not None and isinstance(result.get("arguments"), str):
        args_str = result["arguments"]
        if args_str.strip():
            try:
                result["arguments"] = json.loads(args_str)
            except json.JSONDecodeError:
                pass  # Keep as string if invalid
    
    return result

from jarvis.core.logging import get_logger
from jarvis.core.user_profile import UserProfile, inject_context
from jarvis.core.loop_detector import LoopDetector, RecoveryAction
from jarvis.core.context_budget import ContextBudget
from jarvis.core.validator import ToolValidator

from jarvis.core.config import Config, get_config
from jarvis.providers.mcp import MCPClient, MCPError, parse_command, to_function_tools

# ---------------------------------------------------------------------------
# Constantes (espelho do pi.nix, parametrizadas via Config/env)
# ---------------------------------------------------------------------------

MAX_TURNS: int = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", "8"))

# Comandos read-only seguros — permitidos sem aprovação (diagnóstico/self-heal).
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
    "df", "free", "ps", "pgrep", "ss", "ip", "uname", "uptime",
    "date", "echo", "hostname", "id", "whoami",
    "systemctl is-active", "systemctl status", "systemctl list-units",
    "journalctl", "nix flake check", "nix eval", "nix build --dry-run",
    "nixos-rebuild dry-build", "nixos-rebuild build",
)

# Limite de caracteres para output de tool — evita saturar o contexto do LLM.
# 8000 chars ≈ 2000 tokens, suficiente para a maioria dos comandos.
TOOL_OUTPUT_MAX_CHARS: int = int(os.environ.get("JARVIS_TOOL_OUTPUT_MAX_CHARS", "8000"))

from jarvis.core.tool_patterns import CODEBLOCK_JSON_RE
from jarvis.core.tool_patterns import TOOL_CALL_TAG_RE

logger = get_logger(__name__)


@dataclass
class AgentResult:
    """Result of agent.run()."""
    commands_run: list[str] = field(default_factory=list)
    commands_denied: list[str] = field(default_factory=list)
    final_response: str = ""
    turns: int = 0


def human_approve(cmd: str) -> bool:
    """Ask user for approval. Stub — monkeypatchable in tests."""
    return False


class Agent:
    """
    Main agent class handling tool calling, execution, and safety checks.
    """

    def __init__(
        self,
        config: Config | None = None,
        approval_callback: Callable[[str], bool] | None = None,
        session: Any | None = None,
        memory: Any | None = None,
        audit_path: Path | None = None,
        mcp_servers: dict[str, str] | None = None,
        approve: bool = False,
        llm_client: Any | None = None,
    ):
        self.config = config or get_config()
        self.approval_callback = approval_callback
        if llm_client is None:
            from jarvis.providers.llm import LLMClient
            llm_client = LLMClient(self.config, session=session)
        self.llm = llm_client
        self.memory = memory
        self.approve = approve
        self.audit_path = audit_path
        self.mcp_servers = mcp_servers or {}
        self.logger = get_logger(__name__)
        
        # Initialize components
        # NOTE: sem CircuitBreaker próprio aqui — proteção contra backend
        # instável vive no LLMClient (breaker + classificação de erro). Um
        # segundo breaker no Agent contaria falhas em duplicata.
        self.loop_detector = LoopDetector()
        self.context_budget = ContextBudget()
        self.validator = ToolValidator()

        # State
        self._loop_warnings = 0  # consecutive loop-detector warnings before forced stop
        self.state_dir = Path(self.config.state_dir) if self.config.state_dir else Path.cwd() / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path = audit_path or (self.state_dir / "audit.jsonl")

    def _log_audit(self, command: str, exit_code: int | None, result: str, allowed: bool, approved: bool = False) -> None:
        """Append an entry to the audit trail JSONL file."""
        entry = {
            "timestamp": time.time(),
            "cmd": command,
            "command": command,
            "exit_code": exit_code,
            "result_truncated": result[:TOOL_OUTPUT_MAX_CHARS],
            "allowed": allowed,
            "approved": approved,
        }
        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except IOError as e:
            self.logger.error(f"Failed to write audit log: {e}")

    def run(self, prompt: str) -> AgentResult:
        """Run agent with a single prompt. Returns AgentResult."""
        result = AgentResult()
        self.logger.emit("agent_start", detail={"prompt": prompt[:100]})
        system_content = "You are JARVIS, an AI coding assistant."

        # Persona MCU (default do repl + voz; antes o agente ignorava personas)
        try:
            from jarvis.core.persona import PersonaRegistry
            _persona = PersonaRegistry().get("jarvis")
            if _persona and _persona.system_prompt_additions:
                system_content += f"\n\nPERSONA ATIVA: {_persona.name} ({_persona.role})\n{_persona.system_prompt_additions}"
        except Exception:
            pass

        # Inject user profile
        try:
            from jarvis.core.user_profile import UserProfile, build_context_block
            profile = UserProfile()
            profile.load()
            profile_block = build_context_block(profile)
            if profile_block:
                system_content += f"\n\nUSER PREFERENCES:\n{profile_block}"
        except Exception:
            pass
        
        # Inject environment context
        try:
            import platform
            import os
            env_block = f"""ENVIRONMENT:
- OS: {platform.system()} {platform.release()}
- Python: {platform.python_version()}
- CWD: {os.getcwd()}
- User: {os.environ.get('USER', 'unknown')}"""
            system_content += f"\n\n{env_block}"
        except Exception:
            pass
        
        # Inject lessons from memory
        if self.memory:
            try:
                lessons = self.memory.lessons("", top_k=3)
                if lessons:
                    system_content += f"\n\nAVOID (past errors):{lessons}"
            except Exception:
                pass
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

        # Anti-loop: fresh detector state per prompt
        self.loop_detector.reset()
        self._loop_warnings = 0

        # Context guard (FASE 13): budget fresco por prompt, semeado com o
        # n_ctx autodetectado do budget compartilhado (evita re-query /props
        # e estado vazado entre prompts). Para ao estourar em vez de queimar
        # turnos que o modelo não consegue mais usar.
        turn_budget = ContextBudget(max_tokens=self.context_budget.max_tokens)
        try:
            turn_budget.add_message(messages[0])
            turn_budget.add_message(messages[1])
        except Exception:
            pass

        for turn in range(MAX_TURNS):
            result.turns += 1
            response = self._get_llm_response(messages)
            messages.append(response)
            try:
                turn_budget.add_message(response)
                turn_budget.record_llm_call()
            except Exception:
                pass

            # Context guard: overflow → responde com o que há e para.
            if turn_budget.is_overflow:
                note = "Context budget overflow — stopping to preserve answer quality."
                messages.append({"role": "system", "content": note})
                if not result.final_response:
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant" and msg.get("content"):
                            result.final_response = msg["content"] + f"\n\n[{note}]"
                            break
                    else:
                        result.final_response = f"({note})"
                break
            
            # Extract tool calls
            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")
            if not tool_calls:
                # Check for fallback tool call in content
                fallback = extract_fallback_tool_call(content)
                if fallback:
                    tool_calls = [{"function": fallback}]
                else:
                    result.final_response = content
                    break

            # Anti-loop: detect repeated/cyclic tool calls and inject a
            # recovery message. If the model ignores the warning twice in a
            # row, stop the loop instead of burning turns on the same call.
            strategy = self.loop_detector.check(tool_calls, content)
            if strategy.action in (RecoveryAction.ABORT, RecoveryAction.FORCE_ANSWER):
                messages.append({"role": "system", "content": strategy.message})
                break
            if strategy.action != RecoveryAction.NONE:
                messages.append({"role": "system", "content": strategy.message})
                self._loop_warnings += 1
                if self._loop_warnings >= 2:
                    break
            else:
                self._loop_warnings = 0
            
            # Execute tools
            for tc in tool_calls:
                func = tc.get("function", tc)
                if not isinstance(func, dict):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call-{turn}"),
                        "content": "ERROR: Malformed tool call structure",
                    })
                    continue
                name = func.get("name", "")
                try:
                    raw_args = func.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        args = json.loads(raw_args)
                    else:
                        args = raw_args
                except (json.JSONDecodeError, TypeError):
                    args = {}
                if not isinstance(args, dict):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call-{turn}"),
                        "content": "ERROR: Invalid tool arguments",
                    })
                    continue

                exit_code: int | None = None
                if name == "execute_shell":
                    cmd = args.get("cmd", "")
                    # Check if command is allowed
                    if command_allowed(cmd):
                        # Check chaining
                        if has_chaining_operators(cmd):
                            result.commands_denied.append(cmd)
                            tool_result = f"ERROR: Chaining operators not allowed: {cmd}"
                        else:
                            # Execute
                            proc = run_shell(cmd)
                            result.commands_run.append(cmd)
                            exit_code = proc.returncode
                            tool_result = proc.stdout + proc.stderr
                            self._log_audit(cmd, proc.returncode, tool_result, True)
                            # Auto-learn: record lesson on command failure
                            if proc.returncode != 0 and self.memory:
                                try:
                                    self.memory.remember_lesson(
                                        task=f"shell: {cmd[:80]}",
                                        error_pattern=tool_result[:200],
                                        fix=f"Command '{cmd[:60]}' failed with exit code {proc.returncode}",
                                    )
                                except Exception:
                                    pass
                    else:
                        # Needs approval
                        if self.approve:
                            if human_approve(cmd):
                                proc = run_shell(cmd)
                                result.commands_run.append(cmd)
                                exit_code = proc.returncode
                                tool_result = proc.stdout + proc.stderr
                                self._log_audit(cmd, proc.returncode, tool_result, True)
                            else:
                                result.commands_denied.append(cmd)
                                tool_result = f"ERROR: Command denied by user: {cmd}"
                                self._log_audit(cmd, None, tool_result, False)
                        else:
                            result.commands_denied.append(cmd)
                            tool_result = f"ERROR: Command not allowed: {cmd}"
                            self._log_audit(cmd, None, tool_result, False)
                elif name == "read_file":
                    # Leitura read-only via implementação canônica (devtools).
                    # Sem aprovação: risco zero. Erros viram tool result.
                    from jarvis.core.devtools import read_file as _canonical_read
                    try:
                        offset = int(args.get("offset", 0) or 0)
                    except (TypeError, ValueError):
                        offset = 0
                    try:
                        limit = int(args.get("limit", 200) or 200)
                    except (TypeError, ValueError):
                        limit = 200
                    res = _canonical_read(str(args.get("path", "")), offset=offset, limit=limit)
                    if res.get("ok"):
                        tool_result = f"# {res.get('path', '')} ({res.get('total_lines', 0)} linhas)\n{res.get('content', '')}"
                    else:
                        tool_result = f"ERROR: {res.get('error', 'read failed')}"
                else:
                    tool_result = f"ERROR: Unknown tool: {name}"

                # Post-execution validation (FASE 16): structured failure
                # feedback — padrões de erro, exit codes e hints NixOS que o
                # modelo nem sempre extrai sozinho do output cru.
                if self.validator is not None:
                    try:
                        vr = self.validator.validate(name, args, tool_result, exit_code)
                        if vr.warnings:
                            tool_result += "\n[validation: " + "; ".join(vr.warnings[:3]) + "]"
                    except Exception:
                        pass
                try:
                    turn_budget.record_tool_call()
                except Exception:
                    pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call-{turn}"),
                    "content": tool_result[:TOOL_OUTPUT_MAX_CHARS],
                })
        
        # Get final response if not set
        if not result.final_response:
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    result.final_response = msg["content"]
                    break
        
        self.logger.emit("agent_done", detail={
            "turns": result.turns,
            "commands_run": len(result.commands_run),
            "final_length": len(result.final_response),
        })
        return result

    def _get_llm_response(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Get response from LLM via the canonical LLMClient abstraction.

        Previously this method did a raw `requests.post` to llama.cpp,
        bypassing `LLMClient`/backend (circuit breaker, telemetry, error
        classification, backend routing). Now it delegates to
        `LLMClient.chat_with_tools` and adapts `ChatResponse` to the
        OpenAI-style message dict the loop consumes.
        """
        # Profile-aware generation params (hardcoded 1024/0.0 ignored the
        # detected model profile and tool_choice strategy)
        profile = detect_profile(self.config.llm_model or "")
        # Tools expostas ao LLM. `read_file` é sempre oferecida (read-only,
        # risco zero, capacidade central — CASE 1: "leia o arquivo X" nunca
        # deve precisar de RAG). `execute_shell` + MCP exigem mcp_servers.
        tools: list[dict[str, Any]] = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file with line numbers. Use for exact known paths (no RAG needed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (absolute or relative to CWD)"},
                        "offset": {"type": "integer", "description": "Start line, 0-indexed (default 0)"},
                        "limit": {"type": "integer", "description": "Max lines (default 200)"},
                    },
                    "required": ["path"],
                },
            },
        }]
        if self.mcp_servers:
            tools.append({
                "type": "function",
                "function": {
                    "name": "execute_shell",
                    "description": "Execute a shell command.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cmd": {"type": "string", "description": "Command to execute"}
                        },
                        "required": ["cmd"]
                    }
                }
            })
            # Add MCP tools
            for server_name, server_cmd in self.mcp_servers.items():
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{server_name}_query",
                        "description": f"Query {server_name} MCP server",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "q": {"type": "string", "description": "Query"}
                            },
                            "required": ["q"]
                        }
                    }
                })
        resp = self.llm.chat_with_tools(
            messages,
            tools=tools,
            temperature=profile["temperature"],
            max_tokens=profile["max_tokens"],
        )
        return {
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": resp.tool_calls or [],
        }
        
        # Fallback: raise not implemented
        raise NotImplementedError("LLM provider not configured")