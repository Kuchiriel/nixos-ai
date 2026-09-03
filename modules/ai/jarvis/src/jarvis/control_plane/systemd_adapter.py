"""Systemd Adapter — safe wrapper for systemctl commands.

Prevents the WebUI from executing arbitrary shell commands.
All systemd operations go through this adapter with validation.

Architecture:
    Command → Policy check → SystemdAdapter → systemctl
                                          → audit trail
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Any

from jarvis.control_plane.commands import CommandRegistry, Risk, get_command_registry


# ─── Service Registry ──────────────────────────────────────────────────

# Known Jarvis services — source of truth from NixOS config
# Format: name → {scope, description, managed_by}

KNOWN_SERVICES: dict[str, dict[str, Any]] = {
    # System services (require sudo)
    "llama-cpp-server": {
        "scope": "system",
        "description": "LLM inference server (Qwen)",
        "managed_by": "nixos",
    },
    "llama-cpp-embeddings": {
        "scope": "system",
        "description": "Embeddings server",
        "managed_by": "nixos",
    },
    "llama-cpp-rerank": {
        "scope": "system",
        "description": "Reranker server",
        "managed_by": "nixos",
    },
    "qdrant": {
        "scope": "system",
        "description": "Vector database",
        "managed_by": "nixos",
    },
    "llama-fan-control": {
        "scope": "system",
        "description": "GPU fan control",
        "managed_by": "nixos",
    },
    # User services
    "jarvis-telegram": {
        "scope": "user",
        "description": "Telegram bot",
        "managed_by": "nixos",
    },
    "jarvis-wakeword": {
        "scope": "user",
        "description": "Wake word detection",
        "managed_by": "nixos",
    },
    "jarvis-idle-worker": {
        "scope": "user",
        "description": "Idle worker timer",
        "managed_by": "nixos",
    },
    "waybar": {
        "scope": "user",
        "description": "Status bar",
        "managed_by": "nixos",
    },
}


@dataclass
class ServiceStatus:
    """Status of a systemd service."""
    name: str
    active: bool
    enabled: bool
    status: str  # active, inactive, failed, activating, etc.
    scope: str  # system or user
    description: str
    error: str = ""


# ─── Systemd Adapter ──────────────────────────────────────────────────

class SystemdAdapter:
    """Safe wrapper for systemctl operations.

    Usage:
        adapter = SystemdAdapter()
        status = adapter.get_status("llama-cpp-server")
        adapter.start("llama-cpp-server")
        adapter.stop("llama-cpp-server")
        adapter.restart("qdrant")
    """

    def __init__(self) -> None:
        self._registry = get_command_registry()
        self._register_commands()

    def _register_commands(self) -> None:
        """Register systemd commands with the command registry."""
        self._registry.register(
            name="service.start",
            description="Start a systemd service",
            risk=Risk.LOW,
            handler=self.start,
            args_schema={"name": "Service name"},
            category="services",
        )
        self._registry.register(
            name="service.stop",
            description="Stop a systemd service",
            risk=Risk.LOW,
            handler=self.stop,
            args_schema={"name": "Service name"},
            category="services",
        )
        self._registry.register(
            name="service.restart",
            description="Restart a systemd service",
            risk=Risk.LOW,
            handler=self.restart,
            args_schema={"name": "Service name"},
            category="services",
        )
        self._registry.register(
            name="service.status",
            description="Get service status",
            risk=Risk.SAFE,
            handler=self.get_status,
            args_schema={"name": "Service name"},
            category="services",
        )
        self._registry.register(
            name="service.list",
            description="List all known Jarvis services",
            risk=Risk.SAFE,
            handler=self.list_services,
            category="services",
        )

    def _validate_service(self, name: str) -> str | None:
        """Validate service name exists in registry. Returns error or None."""
        if name not in KNOWN_SERVICES:
            return f"Unknown service: {name}. Known: {', '.join(KNOWN_SERVICES)}"
        return None

    def _run_systemctl(
        self,
        action: str,
        service: str,
        scope: str,
        timeout: int = 30,
    ) -> tuple[bool, str]:
        """Run a systemctl command safely."""
        cmd = ["systemctl"]
        if scope == "user":
            cmd.append("--user")
        cmd.extend([action, service])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, f"Timeout after {timeout}s"
        except (OSError, FileNotFoundError) as exc:
            return False, str(exc)

    def start(self, name: str) -> dict[str, Any]:
        """Start a service."""
        error = self._validate_service(name)
        if error:
            return {"success": False, "error": error}

        svc = KNOWN_SERVICES[name]
        ok, output = self._run_systemctl("start", name, svc["scope"], timeout=60)
        return {
            "success": ok,
            "service": name,
            "action": "start",
            "output": output[:200],
        }

    def stop(self, name: str) -> dict[str, Any]:
        """Stop a service."""
        error = self._validate_service(name)
        if error:
            return {"success": False, "error": error}

        svc = KNOWN_SERVICES[name]
        ok, output = self._run_systemctl("stop", name, svc["scope"], timeout=30)
        return {
            "success": ok,
            "service": name,
            "action": "stop",
            "output": output[:200],
        }

    def restart(self, name: str) -> dict[str, Any]:
        """Restart a service."""
        error = self._validate_service(name)
        if error:
            return {"success": False, "error": error}

        svc = KNOWN_SERVICES[name]
        ok, output = self._run_systemctl("restart", name, svc["scope"], timeout=60)
        return {
            "success": ok,
            "service": name,
            "action": "restart",
            "output": output[:200],
        }

    def get_status(self, name: str) -> dict[str, Any]:
        """Get service status."""
        error = self._validate_service(name)
        if error:
            return {"error": error}

        svc = KNOWN_SERVICES[name]
        scope = svc["scope"]

        # Check active state
        ok_active, out_active = self._run_systemctl("is-active", name, scope, timeout=5)
        active_state = out_active.strip() if ok_active else "unknown"

        # Check enabled state
        ok_enabled, out_enabled = self._run_systemctl("is-enabled", name, scope, timeout=5)
        enabled_state = out_enabled.strip() if ok_enabled else "unknown"

        return {
            "name": name,
            "active": active_state == "active",
            "enabled": enabled_state == "enabled",
            "status": active_state,
            "scope": scope,
            "description": svc["description"],
        }

    def list_services(self) -> list[dict[str, Any]]:
        """List all known Jarvis services with their status."""
        result = []
        for name, svc in KNOWN_SERVICES.items():
            status = self.get_status(name)
            result.append(status)
        return result

    def get_all_status(self) -> dict[str, ServiceStatus]:
        """Get status of all known services."""
        result = {}
        for name in KNOWN_SERVICES:
            data = self.get_status(name)
            result[name] = ServiceStatus(
                name=name,
                active=data.get("active", False),
                enabled=data.get("enabled", False),
                status=data.get("status", "unknown"),
                scope=data.get("scope", "system"),
                description=data.get("description", ""),
            )
        return result


# ─── Singleton ─────────────────────────────────────────────────────────

_adapter: SystemdAdapter | None = None


def get_systemd_adapter() -> SystemdAdapter:
    """Get or create the global systemd adapter."""
    global _adapter
    if _adapter is None:
        _adapter = SystemdAdapter()
    return _adapter
