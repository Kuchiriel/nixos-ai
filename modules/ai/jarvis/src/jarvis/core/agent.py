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
        - temperature (float): Recommended temperature setting (always 0.0 for deterministic tool calling).
    """
    m = model_id.lower()
    
    # Extract total parameters from name
    total_b_match = re.search(r"(?<![a-z])(\d+(?:\.\d+)?)b(?!\w)", m)
    total_b = float(total_b_match.group(1)) if total_b_match else None
    
    if total_b is not None and total_b >= 30:
        return {"name": "large", "max_tokens": 768, "temperature": 0.0}
    elif total_b is not None and total_b >= 7:
        return {"name": "small", "max_tokens": 1024, "temperature": 0.0}
    elif total_b is not None and total_b < 7:
        return {"name": "tiny", "max_tokens": 512, "temperature": 0.0}
    else:
        return {"name": "default", "max_tokens": 1024, "temperature": 0.0}


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
    """
    if not text:
        return None
    
    # Look for <tool_call> format
    match = re.search(r'<tool_call>({.*?})</tool_call>', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Look for JSON in code blocks
    match = re.search(r'```(?:json)?\s*({\s*"name"\s*:\s*"[^"]+"[^}]*})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Look for bare JSON with name and arguments
    match = re.search(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:', text)
    if match:
        # Find the complete JSON object
        start = text.rfind('{', 0, match.start() + 1)
        if start >= 0:
            # Count braces to find matching closing brace
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:i+1])
                        except json.JSONDecodeError:
                            break
    
    return None

import requests

from jarvis.core.logging import get_logger
from jarvis.core.user_profile import UserProfile, inject_context
from jarvis.core.circuit_breaker import CircuitBreaker
from jarvis.core.loop_detector import LoopDetector, RecoveryAction
from jarvis.core.context_budget import ContextBudget
from jarvis.core.validator import ToolValidator

from jarvis.core.config import Config, get_config
from jarvis.providers.mcp import MCPClient, MCPError, parse_command, to_function_tools

# ---------------------------------------------------------------------------
# Constantes (espelho do pi.nix, parametrizadas via Config/env)
# ---------------------------------------------------------------------------

MAX_TURNS: int = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", "8"))
MAX_REPAIR_RETRIES: int = int(os.environ.get("JARVIS_AGENT_MAX_REPAIR_RETRIES", "2"))

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
from jarvis.core.vision import VISION_TOOL
from jarvis.core.devtools import DEV_TOOLS

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "vision",
            "description": "Analyze an image or screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {
                        "type": "string",
                        "description": "URL of the image to analyze."
                    }
                },
                "required": ["image_url"]
            }
        }
    }
]

logger = get_logger(__name__)


class AgentError(Exception):
    """Base exception for Agent errors."""
    pass


class ApprovalDeniedError(AgentError):
    """Raised when a command is denied due to lack of approval."""
    pass


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
    ):
        self.config = config or get_config()
        self.approval_callback = approval_callback
        self.session = session
        self.memory = memory
        self.approve = approve
        self.audit_path = audit_path
        self.mcp_servers = mcp_servers or {}
        self.logger = get_logger(__name__)
        
        # Initialize components
        self.loop_detector = LoopDetector()
        try:
            from jarvis.core.health_monitor import BackendHealthMonitor
            monitor = BackendHealthMonitor()
            self.circuit_breaker = CircuitBreaker(health_monitor=monitor)
        except Exception:
            self.circuit_breaker = None
        self.context_budget = ContextBudget()
        self.validator = ToolValidator()
        
        # State
        self.turn_count = 0
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

    def _check_allowlist(self, command: str) -> bool:
        """Check if command is in the allowlist."""
        try:
            parsed = shlex.split(command)
            cmd_name = parsed[0] if parsed else ""
            
            # Check exact match or prefix match
            for prefix in DEFAULT_ALLOWED_PREFIXES:
                if cmd_name == prefix or command.startswith(prefix + " ") or command.startswith(prefix):
                    return True
            return False
        except ValueError:
            return False

    def _execute_command(self, command: str) -> tuple[int, str]:
        """Execute a shell command and return (exit_code, output)."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=self.config.working_dir if self.config.working_dir else None
            )
            output = result.stdout + result.stderr
            # Truncate output if too long
            if len(output) > TOOL_OUTPUT_MAX_CHARS:
                output = output[:TOOL_OUTPUT_MAX_CHARS] + "\n... [truncated]"
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return -1, "Command timed out"
        except Exception as e:
            return -1, f"Execution error: {str(e)}"

    def _request_approval(self, command: str) -> bool:
        """Request human approval for a command."""
        if self.approval_callback:
            return self.approval_callback(command)
        
        # Fallback to stdin if no callback provided
        try:
            response = input(f"Approve command: {command}? [y/N]: ")
            return response.strip().lower() in ('y', 'yes')
        except EOFError:
            return False
        except Exception as e:
            self.logger.warning(f"Approval request failed: {e}")
            return False

    def execute_tool(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """
        Execute a tool with safety checks.
        
        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments for the tool
            
        Returns:
            Result string from tool execution
            
        Raises:
            ApprovalDeniedError: If command requires approval but is denied
            AgentError: For other execution errors
        """
        self.turn_count += 1
        
        if self.turn_count > MAX_TURNS:
            raise AgentError(f"Maximum turns ({MAX_TURNS}) exceeded")
        
        # Handle vision tool specially
        if tool_name == "vision":
            return VISION_TOOL.execute(**tool_args)
        
        # Handle dev tools
        if tool_name in DEV_TOOLS:
            return DEV_TOOLS[tool_name].execute(**tool_args)
        
        # For command tools, parse and execute
        if tool_name == "bash":
            command = tool_args.get("command", "")
            if not command:
                raise AgentError("No command provided")
            
            # Check allowlist
            is_allowed = self._check_allowlist(command)
            
            if not is_allowed:
                # Require approval
                if not self.config.approve_mode:
                    self._log_audit(command, None, "Denied (no approval mode)", False)
                    raise ApprovalDeniedError(f"Command denied: {command}")
                
                if not self._request_approval(command):
                    self._log_audit(command, None, "Denied (user rejected)", False)
                    raise ApprovalDeniedError(f"Command denied by user: {command}")
            
            # Execute command
            exit_code, output = self._execute_command(command)
            self._log_audit(command, exit_code, output, is_allowed)
            
            return output
        
        raise AgentError(f"Unknown tool: {tool_name}")

    def run_loop(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Main agent loop for processing messages and executing tools.
        
        Args:
            messages: List of conversation messages
            
        Returns:
            Updated list of messages with tool responses
        """
        self.turn_count = 0
        
        for _ in range(MAX_TURNS):
            try:
                # Get response from LLM
                response = self._get_llm_response(messages)
                
                # Check for tool calls
                tool_calls = self._extract_tool_calls(response)
                
                if not tool_calls:
                    # No more tool calls, return final response
                    messages.append(response)
                    break
                
                # Process each tool call
                for tool_call in tool_calls:
                    try:
                        result = self.execute_tool(
                            tool_call["function"]["name"],
                            json.loads(tool_call["function"]["arguments"])
                        )
                        
                        # Add tool response to messages
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result
                        })
                        
                    except ApprovalDeniedError as e:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": f"Approval denied: {str(e)}"
                        })
                    except AgentError as e:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": f"Error: {str(e)}"
                        })
                        
            except Exception as e:
                self.logger.error(f"Agent loop error: {e}")
                break
        
        return messages

    def run(self, prompt: str) -> AgentResult:
        """Run agent with a single prompt. Returns AgentResult."""
        result = AgentResult()
        system_content = "You are JARVIS, an AI coding assistant."
        
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
        
        for turn in range(MAX_TURNS):
            result.turns += 1
            response = self._get_llm_response(messages)
            messages.append(response)
            
            # Extract tool calls
            tool_calls = response.get("tool_calls", [])
            if not tool_calls:
                # Check for fallback tool call in content
                content = response.get("content", "")
                fallback = extract_fallback_tool_call(content)
                if fallback:
                    tool_calls = [{"function": fallback}]
                else:
                    result.final_response = content
                    break
            
            # Execute tools
            for tc in tool_calls:
                func = tc.get("function", tc)
                name = func.get("name", "")
                try:
                    args = json.loads(func.get("arguments", "{}"))
                except (json.JSONDecodeError, TypeError):
                    args = func.get("arguments", {})
                
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
                            tool_result = proc.stdout + proc.stderr
                            self._log_audit(cmd, proc.returncode, tool_result, True)
                    else:
                        # Needs approval
                        if self.approve:
                            if human_approve(cmd):
                                proc = run_shell(cmd)
                                result.commands_run.append(cmd)
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
                else:
                    tool_result = f"ERROR: Unknown tool: {name}"
                
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
        
        return result

    def _get_llm_response(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Get response from LLM via session or config."""
        # Inject lessons into system prompt if memory is available
        if self.memory and messages and messages[0].get("role") == "system":
            try:
                lessons = self.memory.lessons("", top_k=3)
                if lessons:
                    messages[0]["content"] += f"\n\nAVOID (past errors):{lessons}"
            except Exception:
                pass
        
        # Use session if available (for testing)
        if self.session:
            url = f"{self.config.llm_base_url.rstrip('/')}/v1/chat/completions"
            payload = {
                "model": self.config.llm_model,
                "messages": messages,
                "max_tokens": 1024,
                "temperature": 0.0,
            }
            # Add tools if MCP servers are configured
            if self.mcp_servers:
                tools = [{
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
                }]
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
                payload["tools"] = tools
            resp = self.session.post(url, json=payload, timeout=120)
            return resp.json()["choices"][0]["message"]
        
        # Fallback: raise not implemented
        raise NotImplementedError("LLM provider not configured")

    def _extract_tool_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract tool calls from LLM response."""
        return response.get("tool_calls", [])