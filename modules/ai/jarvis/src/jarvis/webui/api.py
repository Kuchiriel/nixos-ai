"""FastAPI backend for Jarvis WebUI — Control Plane HTTP API.

Exposes:
    - GET /api/status — full system status
    - GET /api/state — state store snapshot
    - GET /api/events — SSE stream of events
    - GET /api/commands — list registered commands
    - POST /api/commands/{name} — execute a command
    - GET /api/services — list systemd services
    - POST /api/notify — send notification
    - GET /api/health — health check

SSE Transport:
    GET /api/events/stream — Server-Sent Events for real-time updates
    Events include state changes and command results.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jarvis.control_plane.plane import get_control_plane
from jarvis.control_plane.integration import setup_integration

# ─── App ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Jarvis Control Plane",
    description="Real-time interface for the Jarvis AI system",
    version="0.1.0",
)

# CORS for SvelteKit dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_plane():
    """Get or initialize the Control Plane."""
    plane = get_control_plane()
    setup_integration()
    return plane


# ─── SSE Event Queue ───────────────────────────────────────────────────

_event_queues: list[queue.Queue] = []
_event_lock = threading.Lock()


def _sse_handler(update: Any) -> None:
    """State change handler that pushes to SSE queues."""
    event_data = {
        "type": "state_change",
        "section": update.section,
        "key": update.key,
        "value": update.value,
        "ts": update.ts,
    }
    _push_to_sse(event_data)


def _sse_event_handler(event: Any) -> None:
    """EventBus event handler that pushes to SSE queues."""
    event_data = {
        "type": "event",
        "topic": event.topic,
        "source": event.source,
        "data": event.data,
        "ts": event.ts,
    }
    _push_to_sse(event_data)


def _push_to_sse(data: dict[str, Any]) -> None:
    """Push data to all SSE queues."""
    with _event_lock:
        dead = []
        for q in _event_queues:
            try:
                q.put_nowait(data)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _event_queues.remove(q)


# ─── Routes ────────────────────────────────────────────────────────────

@app.get("/api/health")
def health() -> dict[str, Any]:
    """Health check."""
    return {"status": "ok", "ts": time.time()}


@app.get("/api/status")
def status() -> dict[str, Any]:
    """Full system status."""
    plane = _get_plane()
    return plane.get_full_status()


@app.get("/api/state")
def state() -> dict[str, Any]:
    """State store snapshot."""
    plane = _get_plane()
    return plane.state.get_state()


@app.get("/api/state/{section}")
def state_section(section: str) -> dict[str, Any]:
    """Get a specific state section."""
    plane = _get_plane()
    data = plane.state.get_section(section)
    if not data:
        raise HTTPException(404, f"Section '{section}' not found")
    return data


@app.get("/api/commands")
def commands() -> list[dict[str, Any]]:
    """List all registered commands."""
    plane = _get_plane()
    return plane.commands.list_commands()


@app.get("/api/commands/categories")
def command_categories() -> dict[str, int]:
    """List command categories."""
    plane = _get_plane()
    return plane.commands.list_categories()


class CommandRequest(BaseModel):
    args: dict[str, Any] = {}
    source: str = "webui"
    confirmed: bool = False


@app.post("/api/commands/{name}")
def execute_command(name: str, req: CommandRequest) -> dict[str, Any]:
    """Execute a command."""
    plane = _get_plane()
    result = plane.commands.execute(
        name, req.args,
        source=req.source, confirmed=req.confirmed,
    )
    return result.to_dict()


@app.get("/api/services")
def services() -> list[dict[str, Any]]:
    """List all known services with status."""
    plane = _get_plane()
    if plane._systemd is None:
        from jarvis.control_plane.systemd_adapter import get_systemd_adapter
        plane._systemd = get_systemd_adapter()
    return plane._systemd.list_services()


class NotifyRequest(BaseModel):
    title: str
    body: str = ""
    severity: str = "info"
    channels: list[str] = ["web", "desktop"]


@app.post("/api/notify")
def notify(req: NotifyRequest) -> dict[str, Any]:
    """Send a notification."""
    plane = _get_plane()
    from jarvis.control_plane.events import Severity
    severity_map = {
        "info": Severity.INFO,
        "success": Severity.SUCCESS,
        "warning": Severity.WARNING,
        "error": Severity.ERROR,
        "critical": Severity.CRITICAL,
    }
    notified = plane.notifications.notify(
        req.title, req.body,
        severity=severity_map.get(req.severity, Severity.INFO),
        channels=req.channels,
    )
    return {"notified": notified}


@app.get("/api/events/history")
def event_history(limit: int = 100) -> list[dict[str, Any]]:
    """Get recent event history."""
    plane = _get_plane()
    return plane.get_event_history(limit)


@app.get("/api/events/stats")
def event_stats() -> dict[str, Any]:
    """Event bus statistics."""
    plane = _get_plane()
    return plane.bus.stats


# ─── SSE Stream ────────────────────────────────────────────────────────

@app.get("/api/events/stream")
async def events_stream():
    """Server-Sent Events stream for real-time updates.

    Sends state changes as they happen. Client should reconnect on disconnect.
    """
    plane = _get_plane()

    # Subscribe to state changes
    q: queue.Queue = queue.Queue(maxsize=100)
    with _event_lock:
        _event_queues.append(q)

    # Subscribe to state store
    plane.state.subscribe(None, _sse_handler)

    # Subscribe to EventBus events
    from jarvis.core.eventbus import get_bus
    get_bus().subscribe("", _sse_event_handler, name="sse-bridge")

    async def generate():
        try:
            # Send initial state
            yield f"data: {json.dumps({'type': 'init', 'state': plane.state.get_state()})}\n\n"

            while True:
                try:
                    event = q.get_nowait()
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except queue.Empty:
                    # Send heartbeat every 30s
                    await asyncio.sleep(1)
                    yield f": heartbeat {int(time.time())}\n\n"
        finally:
            # Cleanup
            with _event_lock:
                if q in _event_queues:
                    _event_queues.remove(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
