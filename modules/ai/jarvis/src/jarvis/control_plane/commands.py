"""Command Registry — typed commands with validation, policy, and audit.

Every operation that changes system state goes through a Command.
CLI, WebUI, Telegram, and Voice all execute commands via this registry.

Architecture:
    Caller → CommandRegistry.execute(name, args)
        → validates args
        → checks policy (risk, confirmation)
        → runs handler
        → logs to audit trail
        → returns result

Risk levels:
    SAFE: read-only, no side effects
    LOW: reversible changes (toggle, start/stop service)
    MEDIUM: irreversible changes (delete, modify config)
    HIGH: destructive (reboot, factory reset, deploy)
"""

from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


# ─── Risk Levels ───────────────────────────────────────────────────────

class Risk(Enum):
    SAFE = "safe"         # Read-only, no side effects
    LOW = "low"           # Reversible changes
    MEDIUM = "medium"     # Irreversible changes
    HIGH = "high"         # Destructive actions


# ─── Command Definition ────────────────────────────────────────────────

@dataclass
class CommandDef:
    """Definition of a command."""
    name: str
    description: str
    risk: Risk
    handler: Callable[..., Any]
    requires_confirmation: bool = False
    args_schema: dict[str, str] | None = None  # arg_name → description
    category: str = "general"
    enabled: bool = True


@dataclass
class CommandResult:
    """Result of a command execution."""
    command: str
    success: bool
    result: Any = None
    error: str = ""
    duration_ms: float = 0
    ts: float = 0.0
    source: str = ""  # cli, webui, telegram, voice

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "ts": self.ts,
            "source": self.source,
        }


# ─── Command Registry ─────────────────────────────────────────────────

class CommandRegistry:
    """Central registry for all system commands.

    Usage:
        registry = CommandRegistry()

        @registry.command("service.restart", Risk.LOW, category="services")
        def restart_service(name: str) -> dict:
            ...

        result = registry.execute("service.restart", {"name": "qdrant"}, source="webui")
    """

    def __init__(self, audit_dir: Path | None = None) -> None:
        self._commands: dict[str, CommandDef] = {}
        self._audit_dir = audit_dir or Path.home() / ".local/state/jarvis"
        self._audit_file = self._audit_dir / "command-audit.jsonl"

    def register(
        self,
        name: str,
        description: str,
        risk: Risk,
        handler: Callable[..., Any],
        *,
        requires_confirmation: bool = False,
        args_schema: dict[str, str] | None = None,
        category: str = "general",
    ) -> None:
        """Register a command."""
        self._commands[name] = CommandDef(
            name=name,
            description=description,
            risk=risk,
            handler=handler,
            requires_confirmation=requires_confirmation,
            args_schema=args_schema,
            category=category,
        )

    def command(
        self,
        name: str,
        risk: Risk,
        *,
        description: str = "",
        requires_confirmation: bool = False,
        args_schema: dict[str, str] | None = None,
        category: str = "general",
    ) -> Callable:
        """Decorator to register a command.

        Usage:
            @registry.command("agent.start", Risk.LOW, description="Start agent")
            def start_agent():
                ...
        """
        def decorator(func: Callable) -> Callable:
            self.register(
                name=name,
                description=description or func.__doc__ or "",
                risk=risk,
                handler=func,
                requires_confirmation=requires_confirmation,
                args_schema=args_schema,
                category=category,
            )
            return func
        return decorator

    def execute(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        source: str = "cli",
        confirmed: bool = False,
    ) -> CommandResult:
        """Execute a command.

        Args:
            name: Command name (e.g., "service.restart")
            args: Command arguments
            source: Who's executing (cli, webui, telegram, voice)
            confirmed: Whether user confirmed a dangerous command

        Returns:
            CommandResult with success/failure and output
        """
        cmd = self._commands.get(name)
        if cmd is None:
            return CommandResult(
                command=name,
                success=False,
                error=f"Unknown command: {name}",
                ts=time.time(),
                source=source,
            )

        if not cmd.enabled:
            return CommandResult(
                command=name,
                success=False,
                error=f"Command disabled: {name}",
                ts=time.time(),
                source=source,
            )

        if cmd.requires_confirmation and not confirmed:
            return CommandResult(
                command=name,
                success=False,
                error=f"Requires confirmation (risk={cmd.risk.value}). "
                      f"Re-execute with confirmed=True.",
                ts=time.time(),
                source=source,
            )

        args = args or {}
        start = time.time()
        try:
            result = cmd.handler(**args)
            duration = (time.time() - start) * 1000
            cmd_result = CommandResult(
                command=name,
                success=True,
                result=result,
                duration_ms=duration,
                ts=time.time(),
                source=source,
            )
        except Exception as exc:
            duration = (time.time() - start) * 1000
            cmd_result = CommandResult(
                command=name,
                success=False,
                error=str(exc),
                duration_ms=duration,
                ts=time.time(),
                source=source,
            )

        self._audit(cmd_result)
        return cmd_result

    def get_command(self, name: str) -> CommandDef | None:
        """Get command definition."""
        return self._commands.get(name)

    def list_commands(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all registered commands."""
        result = []
        for cmd in self._commands.values():
            if category and cmd.category != category:
                continue
            result.append({
                "name": cmd.name,
                "description": cmd.description,
                "risk": cmd.risk.value,
                "category": cmd.category,
                "requires_confirmation": cmd.requires_confirmation,
                "enabled": cmd.enabled,
                "args": cmd.args_schema,
            })
        return result

    def list_categories(self) -> dict[str, int]:
        """List categories and command counts."""
        cats: dict[str, int] = {}
        for cmd in self._commands.values():
            cats[cmd.category] = cats.get(cmd.category, 0) + 1
        return cats

    def _audit(self, result: CommandResult) -> None:
        """Log command execution to audit trail."""
        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": result.ts,
                "command": result.command,
                "success": result.success,
                "source": result.source,
                "duration_ms": round(result.duration_ms, 1),
                "error": result.error[:200] if result.error else None,
            }
            with self._audit_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # Best-effort audit


# ─── Singleton ─────────────────────────────────────────────────────────

_registry: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    """Get or create the global command registry."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry
