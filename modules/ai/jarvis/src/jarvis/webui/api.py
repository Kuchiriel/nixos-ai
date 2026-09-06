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
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://localhost:8090",
        "http://127.0.0.1:8090",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
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


# ─── MCP Bridge (mission-control: mesmas tools do MCP server) ────────────

# Tools que mutam estado exigem approve=true (mesma filosofia do confirmed).
MCP_WRITE_TOOLS = frozenset({
    "jarvis_execute",
    "jarvis_write_file",
    "jarvis_str_replace",
    "jarvis_vault_write",
    "jarvis_vault_sync_obsidian",
    "jarvis_vault_sync_hackmd",
    "jarvis_rag_index",
    "jarvis_remember",
})


class McpCallRequest(BaseModel):
    arguments: dict[str, Any] = {}
    approve: bool = False


@app.get("/api/mcp/tools")
def mcp_tools() -> list[dict[str, Any]]:
    """List MCP tools (name, description, write-gated). Mesmas do MCP server."""
    from jarvis.mcp_server import JARVIS_TOOLS
    return [
        {
            "name": t.get("name", "?"),
            "description": t.get("description", ""),
            "write": t.get("name") in MCP_WRITE_TOOLS,
        }
        for t in JARVIS_TOOLS
    ]


@app.post("/api/mcp/call/{name}")
def mcp_call(name: str, req: McpCallRequest) -> dict[str, Any]:
    """Call an MCP tool. Write tools exigem approve=true. Audita via SSE."""
    from jarvis.mcp_server import JARVIS_TOOLS, call_tool
    known = {t.get("name") for t in JARVIS_TOOLS}
    if name not in known:
        raise HTTPException(status_code=404, detail=f"Unknown MCP tool: {name}")
    if name in MCP_WRITE_TOOLS and not req.approve:
        raise HTTPException(
            status_code=403,
            detail=f"Tool '{name}' mutates state — reenvie com approve=true",
        )
    result = call_tool(name, req.arguments or {})
    _push_to_sse({
        "type": "mcp_call",
        "tool": name,
        "approved": req.approve,
        "error": result.startswith("ERROR:"),
        "ts": time.time(),
    })
    return {"tool": name, "result": result, "isError": result.startswith("ERROR:")}


# ─── Config & Router ───────────────────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    llm_disable_thinking: bool | None = None
    llm_timeout: int | None = None
    tavily_api_key: str | None = None


@app.get("/api/config")
def get_system_config() -> dict[str, Any]:
    """Get full system configuration, cascade router status, and secret presence."""
    from jarvis.core.config import get_config
    import os
    from pathlib import Path

    cfg = get_config()
    tavily_secret = Path("/etc/jarvis-secrets/tavily.env")
    has_tavily = tavily_secret.exists() or bool(os.environ.get("TAVILY_API_KEY"))

    return {
        "llm": {
            "backend": cfg.llm_backend,
            "base_url": cfg.llm_base_url,
            "model": cfg.llm_model,
            "timeout": cfg.llm_timeout,
            "disable_thinking": cfg.llm_disable_thinking,
            "tool_calling": cfg.llm_tool_calling,
        },
        "services": {
            "embed_url": cfg.embed_base_url,
            "rerank_url": cfg.rerank_base_url,
            "qdrant_url": cfg.qdrant_url,
        },
        "cascade_router": {
            "routes": [
                {"name": "fastpath", "desc": "Respostas instantâneas e determinísticas sem LLM"},
                {"name": "doctor", "desc": "Diagnóstico de saúde do sistema e serviços"},
                {"name": "nixos", "desc": "Consultas declarativas do sistema NixOS / Nixpkgs"},
                {"name": "rag", "desc": "Busca semântica no Qdrant (dense + sparse + rerank)"},
                {"name": "agent", "desc": "Execução autônoma com personas e chamadas de ferramenta"},
            ],
            "status": "active",
        },
        "secrets": {
            "tavily_configured": has_tavily,
            "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
        },
    }


@app.post("/api/config")
def update_system_config(req: ConfigUpdateRequest) -> dict[str, Any]:
    """Update runtime configuration settings."""
    import os
    if req.llm_disable_thinking is not None:
        os.environ["JARVIS_LLM_DISABLE_THINKING"] = "1" if req.llm_disable_thinking else "0"
    if req.llm_timeout is not None:
        os.environ["JARVIS_LLM_TIMEOUT"] = str(req.llm_timeout)
    if req.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = req.tavily_api_key

    from jarvis.core.config import get_config
    if hasattr(get_config, "cache_clear"):
        get_config.cache_clear()
    return {"status": "updated"}


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


@app.post("/api/services/{name}/{action}")
def service_action(name: str, action: str) -> dict[str, Any]:
    """start/stop/restart a service via allowlisted SystemdAdapter + SSE audit."""
    if action not in ("start", "stop", "restart"):
        raise HTTPException(400, f"Invalid action: {action}")
    plane = _get_plane()
    if plane._systemd is None:
        from jarvis.control_plane.systemd_adapter import get_systemd_adapter
        plane._systemd = get_systemd_adapter()
    fn = {"start": plane._systemd.start,
          "stop": plane._systemd.stop,
          "restart": plane._systemd.restart}[action]
    result = fn(name)
    _push_to_sse({"type": "service_action", "service": name,
                  "action": action, "success": result.get("success", False),
                  "ts": time.time()})
    return result


class ChatRequest(BaseModel):
    message: str
    max_tokens: int = 512
    temperature: float = 0.0


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    """Chat direto com o LLM local (Bonsai). Sem streaming (rápido a 71 t/s)."""
    if not req.message.strip():
        raise HTTPException(400, "Empty message")
    from jarvis.providers.llm import LLMClient
    client = LLMClient()
    text = client.chat(
        [{"role": "user", "content": req.message}],
        temperature=req.temperature,
        max_tokens=min(req.max_tokens, 4096),
    )
    _push_to_sse({"type": "chat", "ts": time.time()})
    return {"reply": text}


@app.get("/api/remote")
def remote_status() -> dict[str, Any]:
    """Cascade remota: quais provedores têm key configurada (nomes, NUNCA valores).

    Keys vivem em /etc/litellm.env (chmod 600, fora do repo).
    """
    from pathlib import Path
    env_file = Path("/etc/litellm.env")
    present: dict[str, bool] = {"groq": False, "gemini": False, "openrouter": False}
    exists = env_file.exists()
    if exists:
        try:
            content = env_file.read_text(encoding="utf-8")
            present["groq"] = "GROQ_API_KEY=" in content and "sua_chave" not in content
            present["gemini"] = "GEMINI_API_KEY=" in content and "sua_chave" not in content
            present["openrouter"] = "OPENROUTER_API_KEY=" in content and "sua_chave" not in content
        except OSError:
            exists = False
    return {"env_file": exists, "providers": present,
            "cascade": ["local"] + [k for k, v in present.items() if v]}


class KeysUpdateRequest(BaseModel):
    provider: str
    key: str


PROVIDER_KEY_MAP = {
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "together": ["TOGETHERAI_API_KEY", "TOGETHER_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "hf": ["HUGGINGFACE_API_KEY", "HF_TOKEN"],
}


@app.get("/api/keys")
def keys_status() -> dict[str, Any]:
    """List which API-key providers have keys configured (names only, never values)."""
    from pathlib import Path
    env_file = Path("/etc/litellm.env")
    present: dict[str, bool] = {k: False for k in PROVIDER_KEY_MAP}
    if env_file.exists():
        try:
            content = env_file.read_text(encoding="utf-8")
            for provider, key_names in PROVIDER_KEY_MAP.items():
                if isinstance(key_names, str):
                    key_names = [key_names]
                for kn in key_names:
                    if f"{kn}=" in content and "sua_chave" not in content:
                        present[provider] = True
                        break
        except OSError:
            pass
    configured = [k for k, v in present.items() if v]
    return {"providers": present, "configured": configured,
            "cascade": ["local"] + configured}


@app.post("/api/keys")
def set_key(req: KeysUpdateRequest) -> dict[str, Any]:
    """Set or update an API key for a provider. Writes to /etc/litellm.env."""
    import os
    env_file = Path("/etc/litellm.env")
    key_names = PROVIDER_KEY_MAP.get(req.provider)
    if not key_names:
        raise HTTPException(400, f"Unknown provider: {req.provider}")
    if isinstance(key_names, str):
        key_names = [key_names]
    key_name = key_names[0]

    try:
        if env_file.exists():
            content = env_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            new_lines = [l for l in lines if not l.startswith(f"{key_name}=")]
            new_lines.append(f'export {key_name}="{req.key}"')
            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        else:
            env_file.write_text(f'export {key_name}="{req.key}"\n', encoding="utf-8")
        os.chmod(env_file, 0o644)
    except OSError as e:
        raise HTTPException(500, f"Failed to write key: {e}")

    _push_to_sse({"type": "key_set", "provider": req.provider, "ts": time.time()})
    return {"status": "updated", "provider": req.provider}


@app.delete("/api/keys/{provider}")
def remove_key(provider: str) -> dict[str, Any]:
    """Remove an API key for a provider from /etc/litellm.env."""
    import os
    key_names = PROVIDER_KEY_MAP.get(provider)
    if not key_names:
        raise HTTPException(400, f"Unknown provider: {provider}")
    if isinstance(key_names, str):
        key_names = [key_names]

    try:
        env_file = Path("/etc/litellm.env")
        if env_file.exists():
            content = env_file.read_text(encoding="utf-8")
            lines = content.splitlines()
            new_lines = [l for l in lines if not any(l.startswith(f"{kn}=") for kn in key_names)]
            env_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            os.chmod(env_file, 0o644)
    except OSError as e:
        raise HTTPException(500, f"Failed to remove key: {e}")

    _push_to_sse({"type": "key_removed", "provider": provider, "ts": time.time()})
    return {"status": "removed", "provider": provider}


@app.get("/api/events/history")
def event_history(limit: int = 100) -> list[dict[str, Any]]:
    """Get recent event history."""
    plane = _get_plane()
    return plane.get_event_history(limit)


# ─── LLM ──────────────────────────────────────────────────────────────

@app.get("/api/llm")
def llm_info() -> dict[str, Any]:
    """Get LLM backend info including real active model name."""
    from jarvis.core.config import get_config
    from pathlib import Path
    import requests

    cfg = get_config()
    info: dict[str, Any] = {
        "backend": cfg.llm_backend,
        "model": cfg.llm_model,
        "base_url": cfg.llm_base_url,
        "timeout": cfg.llm_timeout,
        "tool_calling": cfg.llm_tool_calling,
        "disable_thinking": cfg.llm_disable_thinking,
    }
    try:
        resp = requests.get(f"{cfg.llm_base_url}/models", timeout=3)
        if resp.status_code == 200:
            info["healthy"] = True
            info["status"] = "online"
            data = resp.json().get("data", [])
            if data and "id" in data[0]:
                raw_name = data[0]["id"]
                stem = Path(raw_name).stem.replace(".gguf", "")
                parts = stem.split("-", 1)
                clean_name = parts[-1] if (len(parts) > 1 and len(parts[0]) == 32) else stem
                info["model"] = clean_name
                info["raw_model_path"] = raw_name
        else:
            info["healthy"] = False
            info["status"] = "error"
    except Exception:
        info["healthy"] = False
        info["status"] = "offline"
    return info


# ─── Voice ─────────────────────────────────────────────────────────────

@app.get("/api/voice")
def voice_info() -> dict[str, Any]:
    """Get voice/TTS state."""
    plane = _get_plane()
    voice_state = plane.state.get_section("voice")
    status_text = voice_state.get("status_text", "")
    current_status = voice_state.get("status", "idle")
    
    # Auto-heal stale error if code_index is now active
    if current_status == "error" and "code_index" in status_text:
        current_status = "idle"
        status_text = "Ready (RAG active)"

    return {
        "status": current_status,
        "text": status_text,
        "last_tts_len": voice_state.get("last_tts_len", 0),
        "last_tts_time": voice_state.get("last_tts_time"),
    }


# ─── Memory / RAG ─────────────────────────────────────────────────────

@app.get("/api/memory")
def memory_info() -> dict[str, Any]:
    """Get memory/RAG status."""
    from jarvis.core.config import get_config
    cfg = get_config()
    info: dict[str, Any] = {
        "qdrant_url": cfg.qdrant_url,
        "collections": {
            "code": cfg.qdrant_collection_code,
            "memories": cfg.qdrant_collection_memories,
            "books": cfg.qdrant_collection_books,
        },
    }
    # Check Qdrant health
    try:
        import requests
        resp = requests.get(f"{cfg.qdrant_url}/collections", timeout=3)
        if resp.status_code == 200:
            collections = [c["name"] for c in resp.json()["result"]["collections"]]
            info["healthy"] = True
            info["existing_collections"] = collections
        else:
            info["healthy"] = False
    except Exception:
        info["healthy"] = False
        info["existing_collections"] = []
    return info


# ─── Agent ─────────────────────────────────────────────────────────────

@app.get("/api/agent")
def agent_info() -> dict[str, Any]:
    """Get agent state."""
    plane = _get_plane()
    agent_state = plane.state.get_section("agent")
    return {
        "active_task": agent_state.get("active_task", ""),
        "active_persona": agent_state.get("active_persona", ""),
        "active_project": agent_state.get("active_project", ""),
    }


# ─── Nightwatch ────────────────────────────────────────────────────────

@app.get("/api/nightwatch")
def nightwatch_info() -> dict[str, Any]:
    """Get nightwatch state."""
    from pathlib import Path
    import json
    state_dir = Path.home() / ".local/state/jarvis/nightwatch"
    info: dict[str, Any] = {"active": False, "last_run": None}
    progress_file = state_dir / "progress.json"
    if progress_file.exists():
        try:
            data = json.loads(progress_file.read_text())
            info["last_run"] = data
            info["active"] = True
        except (json.JSONDecodeError, OSError):
            pass
    return info


# ─── Projects ──────────────────────────────────────────────────────────

@app.get("/api/projects")
def projects_list() -> list[dict[str, Any]]:
    """List projects — fast shallow scan, no deep analysis."""
    now = time.time()
    if hasattr(projects_list, '_cache') and now - projects_list._cache_ts < 60:
        return projects_list._cache

    from pathlib import Path
    import os
    root = Path(os.path.expanduser("~/projects"))
    result = []
    if root.exists():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            # Quick project detection
            has_git = (entry / ".git").exists()
            has_py = any(entry.glob("*.py")) or (entry / "pyproject.toml").exists()
            has_nix = (entry / "flake.nix").exists() or (entry / "default.nix").exists()
            has_node = (entry / "package.json").exists()
            proj_type = "unknown"
            if has_py: proj_type = "python"
            if has_nix: proj_type = "nix" if proj_type == "unknown" else f"{proj_type}+nix"
            if has_node: proj_type = "node" if proj_type == "unknown" else f"{proj_type}+node"
            result.append({
                "name": entry.name,
                "path": str(entry),
                "type": proj_type,
                "has_git": has_git,
            })
    projects_list._cache = result
    projects_list._cache_ts = now
    return result


# ─── Tasks ──────────────────────────────────────────────────────────────

@app.get("/api/tasks")
def tasks_list(limit: int = 50) -> dict[str, Any]:
    """List tasks from the persistent task queue."""
    from pathlib import Path
    import json as _json
    state_dir = Path.home() / ".local/state/jarvis/nightwatch"
    queue_file = state_dir / "task_queue.json"
    mission_file = state_dir / "mission_state.json"

    tasks = []
    if queue_file.exists():
        try:
            raw = _json.loads(queue_file.read_text(encoding="utf-8"))
            # Sort by updated_at descending (most recent first)
            raw.sort(key=lambda t: t.get("updated_at", 0), reverse=True)
            tasks = raw[:limit]
        except (_json.JSONDecodeError, OSError):
            pass

    mission = {}
    if mission_file.exists():
        try:
            mission = _json.loads(mission_file.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError):
            pass

    return {
        "tasks": tasks,
        "mission": mission,
        "total": len(tasks),
    }


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str) -> dict[str, Any]:
    """Get a specific task by ID."""
    from pathlib import Path
    import json as _json
    queue_file = Path.home() / ".local/state/jarvis/nightwatch" / "task_queue.json"
    if not queue_file.exists():
        raise HTTPException(404, "No tasks found")
    try:
        raw = _json.loads(queue_file.read_text(encoding="utf-8"))
        for t in raw:
            if t.get("id") == task_id:
                return t
    except (_json.JSONDecodeError, OSError):
        pass
    raise HTTPException(404, f"Task {task_id} not found")


def _find_task_file(task_id: str) -> tuple[str, dict[str, Any]] | None:
    """Locate a task across per-project queue files. Returns (project, dict)."""
    import json as _json
    from nightwatch.task_queue import STATE_DIR
    for qf in sorted(STATE_DIR.glob("task_queue*.json")):
        try:
            raw = _json.loads(qf.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        for t in raw:
            if t.get("id") == task_id:
                proj = t.get("project", "nixos-ai")
                return proj, t
    return None


@app.post("/api/tasks/{task_id}/retry")
def task_retry(task_id: str) -> dict[str, Any]:
    """Re-queue a FAILED/BLOCKED task (attempts reset)."""
    from nightwatch.task_queue import TaskQueue, TaskStatus
    found = _find_task_file(task_id)
    if not found:
        raise HTTPException(404, f"Task {task_id} not found")
    project, _ = found
    q = TaskQueue(project=project)
    task = q.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    if task.status not in (TaskStatus.FAILED.value, TaskStatus.BLOCKED.value):
        raise HTTPException(409, f"Only FAILED/BLOCKED can retry (status={task.status})")
    q.update_task(task_id, status=TaskStatus.READY.value, attempts=0,
                  last_error="retried via webui")
    _push_to_sse({"type": "task_retry", "task_id": task_id, "ts": time.time()})
    return {"task_id": task_id, "status": TaskStatus.READY.value}


@app.post("/api/tasks/{task_id}/cancel")
def task_cancel(task_id: str) -> dict[str, Any]:
    """Abandon a non-terminal task."""
    from nightwatch.task_queue import TaskQueue, TaskStatus
    found = _find_task_file(task_id)
    if not found:
        raise HTTPException(404, f"Task {task_id} not found")
    project, _ = found
    q = TaskQueue(project=project)
    task = q.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found")
    if task.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value,
                       TaskStatus.ABANDONED.value):
        raise HTTPException(409, f"Terminal task cannot cancel (status={task.status})")
    task.abandon("cancelled via webui")
    q._save()
    _push_to_sse({"type": "task_cancel", "task_id": task_id, "ts": time.time()})
    return {"task_id": task_id, "status": TaskStatus.ABANDONED.value}


@app.post("/api/tasks/clear_failed")
def clear_failed_tasks() -> dict[str, Any]:
    """Clear failed tasks from the persistent task queue."""
    from pathlib import Path
    import json as _json
    queue_file = Path.home() / ".local/state/jarvis/nightwatch" / "task_queue.json"
    if not queue_file.exists():
        return {"cleared": 0, "remaining": 0}
    
    try:
        raw = _json.loads(queue_file.read_text(encoding="utf-8"))
        remaining = [t for t in raw if t.get("status") != "FAILED"]
        cleared_count = len(raw) - len(remaining)
        queue_file.write_text(_json.dumps(remaining, indent=2), encoding="utf-8")
        return {"cleared": cleared_count, "remaining": len(remaining)}
    except Exception as e:
        raise HTTPException(500, f"Failed to clear tasks: {e}")


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

    # Subscribe to state store (idempotent — handler ref replaces previous)
    plane.state.subscribe(None, _sse_handler)

    # Track unique subscriber name for this connection
    import uuid
    sub_name = f"sse-bridge-{uuid.uuid4().hex[:8]}"

    # Subscribe to EventBus events with unique name (cleaned up on disconnect)
    from jarvis.core.eventbus import get_bus
    get_bus().subscribe("", _sse_event_handler, name=sub_name)

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
            # Cleanup: remove from SSE queues and unsubscribe from EventBus
            with _event_lock:
                if q in _event_queues:
                    _event_queues.remove(q)
            get_bus().unsubscribe(sub_name)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
