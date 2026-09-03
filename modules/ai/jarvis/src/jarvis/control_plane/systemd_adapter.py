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

# Seed descriptions for known Jarvis services
# The actual service list is discovered dynamically from systemctl
SERVICE_DESCRIPTIONS: dict[str, str] = {
    "llama-cpp-server": "LLM inference server (Qwen)",
    "llama-cpp-embeddings": "Embeddings server",
    "llama-cpp-rerank": "Reranker server",
    "qdrant": "Vector database",
    "llama-fan-control": "GPU fan control",
    "jarvis-telegram": "Telegram bot",
    "jarvis-wakeword": "Wake word detection",
    "jarvis-idle-worker": "Idle worker timer",
    "waybar": "Status bar",
    "mpvpaper": "Animated wallpaper",
    "swaync": "Notification daemon",
    "hypridle": "Idle manager",
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

    Discovers services dynamically from systemctl, with seed descriptions
    for known Jarvis services. The NixOS/systemd config is the source of truth.

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
        self._discovered_services: dict[str, dict[str, Any]] | None = None

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

    def _discover_services(self) -> dict[str, dict[str, Any]]:
        """Discover services dynamically from systemctl.

        Combines:
        - Dynamic discovery from systemctl list-units
        - Seed descriptions from SERVICE_DESCRIPTIONS
        """
        if self._discovered_services is not None:
            return self._discovered_services

        services: dict[str, dict[str, Any]] = {}

        # Discover system services
        for scope, flag in [("system", []), ("user", ["--user"])]:
            try:
                cmd = ["systemctl"] + flag + [
                    "list-units", "--type=service",
                    "--all", "--no-legend", "--no-pager",
                    "--plain",
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0:
                    continue
                for line in result.stdout.strip().splitlines():
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    unit = parts[0]
                    # Remove .service suffix
                    name = unit.replace(".service", "")
                    # Filter: only jarvis-related or well-known services
                    is_jarvis = any(kw in name for kw in (
                        "jarvis", "llama", "qdrant", "waybar",
                        "mpvpaper", "swaync", "hypr",
                    ))
                    if not is_jarvis:
                        continue
                    # Format: unit load active sub description
                    # parts[0]=unit, parts[1]=load, parts[2]=active, parts[3]=sub, parts[4:]=desc
                    active_state = parts[2] if len(parts) > 2 else "unknown"
                    sub_state = parts[3] if len(parts) > 3 else "unknown"
                    description = " ".join(parts[4:]) if len(parts) > 4 else ""
                    # Use seed description if available
                    desc = SERVICE_DESCRIPTIONS.get(name, description)
                    services[name] = {
                        "scope": scope,
                        "description": desc,
                        "active_state": active_state,
                        "sub_state": sub_state,
                    }
            except (subprocess.TimeoutExpired, OSError):
                continue

        self._discovered_services = services
        return services

    def _validate_service(self, name: str) -> str | None:
        """Validate service name exists. Returns error or None."""
        services = self._discover_services()
        if name not in services:
            known = ", ".join(sorted(services.keys()))
            return f"Unknown service: {name}. Discovered: {known}"
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
        """Get service status via systemctl."""
        services = self._discover_services()
        svc = services.get(name)
        if svc is None:
            return {"error": f"Service not found: {name}"}

        scope = svc["scope"]

        # Check active state (is-active returns exit 3 for inactive — that's OK)
        _, out_active = self._run_systemctl("is-active", name, scope, timeout=5)
        active_state = out_active.strip() or "unknown"

        # Check enabled state (is-enabled returns exit 1 for disabled — that's OK)
        _, out_enabled = self._run_systemctl("is-enabled", name, scope, timeout=5)
        enabled_state = out_enabled.strip() or "unknown"

        return {
            "name": name,
            "active": active_state == "active",
            "enabled": enabled_state == "enabled",
            "status": active_state,
            "scope": scope,
            "description": svc.get("description", ""),
        }

    def list_services(self) -> list[dict[str, Any]]:
        """List all discovered Jarvis services with their status."""
        services = self._discover_services()
        result = []
        for name in services:
            result.append(self.get_status(name))
        return result

    def get_all_status(self) -> dict[str, ServiceStatus]:
        """Get status of all discovered services."""
        services = self._discover_services()
        result = {}
        for name in services:
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

    def invalidate_cache(self) -> None:
        """Force re-discovery on next call."""
        self._discovered_services = None


# ─── Singleton ─────────────────────────────────────────────────────────

_adapter: SystemdAdapter | None = None


def get_systemd_adapter() -> SystemdAdapter:
    """Get or create the global systemd adapter."""
    global _adapter
    if _adapter is None:
        _adapter = SystemdAdapter()
    return _adapter
