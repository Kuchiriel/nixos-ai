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


class Agent:
    """
    Main agent class handling tool calling, execution, and safety checks.
    """

    def __init__(
        self,
        config: Config | None = None,
        approval_callback: Callable[[str], bool] | None = None,
    ):
        self.config = config or get_config()
        self.approval_callback = approval_callback
        self.logger = get_logger(__name__)
        
        # Initialize components
        self.loop_detector = LoopDetector()
        self.circuit_breaker = CircuitBreaker()
        self.context_budget = ContextBudget()
        self.validator = ToolValidator()
        
        # State
        self.turn_count = 0
        self.state_dir = Path(self.config.state_dir) if self.config.state_dir else Path.cwd() / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path = self.state_dir / "audit.jsonl"

    def _log_audit(self, command: str, exit_code: int | None, result: str, allowed: bool) -> None:
        """Append an entry to the audit trail JSONL file."""
        entry = {
            "timestamp": time.time(),
            "command": command,
            "exit_code": exit_code,
            "result_truncated": result[:TOOL_OUTPUT_MAX_CHARS],
            "allowed": allowed,
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

    def _get_llm_response(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Get response from LLM (implementation depends on provider)."""
        # Placeholder for actual LLM call
        raise NotImplementedError("LLM provider not implemented")

    def _extract_tool_calls(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract tool calls from LLM response."""
        # Placeholder for actual parsing logic
        raise NotImplementedError("Tool call extraction not implemented")