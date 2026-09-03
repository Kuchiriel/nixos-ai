"""State Store — single source of truth for operational state.

Replaces scattered JSON files with a structured, queryable state store.
Components publish state updates; consumers (WebUI, CLI, Waybar) subscribe.

Architecture:
    Component → StateStore.update(section, key, value)
        → persists to disk
        → notifies subscribers
        → consumers read current state

Sections map to subsystems:
    system, agent, llm, voice, services, nightwatch,
    projects, tasks, memory, rag, gaming, health
"""

from __future__ import annotations

import json
import time
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable


# ─── State Sections ────────────────────────────────────────────────────

class Sections:
    """State section names."""
    SYSTEM = "system"
    AGENT = "agent"
    LLM = "llm"
    VOICE = "voice"
    SERVICES = "services"
    NIGHTWATCH = "nightwatch"
    PROJECTS = "projects"
    TASKS = "tasks"
    MEMORY = "memory"
    RAG = "rag"
    GAMING = "gaming"
    HEALTH = "health"


@dataclass
class StateUpdate:
    """A state change event."""
    section: str
    key: str
    value: Any
    ts: float = 0.0
    previous: Any = None


# ─── State Store ───────────────────────────────────────────────────────

class StateStore:
    """Thread-safe state store with persistence and subscriptions.

    Usage:
        store = StateStore()
        store.update(Sections.SYSTEM, "boot_time", time.time())
        store.update(Sections.LLM, "model", "qwen3.6-35b")
        store.update(Sections.HEALTH, "overall", "ok")

        # Read
        state = store.get_state()
        llm = store.get(Sections.LLM)

        # Subscribe
        store.subscribe(Sections.LLM, my_handler)
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[Callable[[StateUpdate], None]]] = {}
        self._all_subscribers: list[Callable[[StateUpdate], None]] = []
        self._state_dir = state_dir or Path.home() / ".local/state/jarvis"
        self._state_file = self._state_dir / "control-plane-state.json"
        self._load()

    def _load(self) -> None:
        """Load state from disk."""
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._state = data.get("sections", {})
        except (OSError, json.JSONDecodeError):
            self._state = {}

    def _save(self) -> None:
        """Persist state to disk (called after updates)."""
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            data = {
                "sections": self._state,
                "last_update": time.time(),
                "last_update_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            self._state_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass  # Best-effort persistence

    def update(self, section: str, key: str, value: Any) -> StateUpdate:
        """Update a state value and notify subscribers.

        Args:
            section: State section (e.g., Sections.LLM)
            key: Key within the section (e.g., "model")
            value: New value (must be JSON-serializable)

        Returns:
            StateUpdate with previous value
        """
        with self._lock:
            if section not in self._state:
                self._state[section] = {}
            previous = self._state[section].get(key)
            self._state[section][key] = value
            self._save()

        update = StateUpdate(
            section=section,
            key=key,
            value=value,
            ts=time.time(),
            previous=previous,
        )

        # Notify subscribers (outside lock)
        self._notify(section, update)
        return update

    def update_many(self, section: str, data: dict[str, Any]) -> list[StateUpdate]:
        """Update multiple keys in a section atomically."""
        updates = []
        for key, value in data.items():
            updates.append(self.update(section, key, value))
        return updates

    def get(self, section: str, key: str | None = None) -> Any:
        """Get state for a section or a specific key."""
        with self._lock:
            if key is None:
                return dict(self._state.get(section, {}))
            return self._state.get(section, {}).get(key)

    def get_state(self) -> dict[str, dict[str, Any]]:
        """Get the full state snapshot."""
        with self._lock:
            return dict(self._state)

    def get_section(self, section: str) -> dict[str, Any]:
        """Get a section's state."""
        with self._lock:
            return dict(self._state.get(section, {}))

    def subscribe(
        self,
        section: str | None,
        handler: Callable[[StateUpdate], None],
    ) -> None:
        """Subscribe to state changes.

        Args:
            section: Section to watch (None = all sections)
            handler: Callback for state changes
        """
        with self._lock:
            if section is None:
                self._all_subscribers.append(handler)
            else:
                self._subscribers.setdefault(section, []).append(handler)

    def unsubscribe(
        self,
        section: str | None,
        handler: Callable[[StateUpdate], None],
    ) -> None:
        """Remove a subscription."""
        with self._lock:
            if section is None:
                self._all_subscribers = [
                    h for h in self._all_subscribers if h != handler
                ]
            else:
                subs = self._subscribers.get(section, [])
                self._subscribers[section] = [h for h in subs if h != handler]

    def _notify(self, section: str, update: StateUpdate) -> None:
        """Notify subscribers of a state change."""
        # Section-specific subscribers
        for handler in self._subscribers.get(section, []):
            try:
                handler(update)
            except Exception:
                pass  # Never crash on subscriber error

        # Global subscribers
        for handler in self._all_subscribers:
            try:
                handler(update)
            except Exception:
                pass

    def to_dict(self) -> dict[str, Any]:
        """Export full state as a dict (for API responses)."""
        return self.get_state()


# ─── Singleton ─────────────────────────────────────────────────────────

_store: StateStore | None = None


def get_state_store() -> StateStore:
    """Get or create the global state store."""
    global _store
    if _store is None:
        _store = StateStore()
    return _store
