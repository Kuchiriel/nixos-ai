# HANDOFF.md — Project Index

> Updated: 2026-09-03

## Quick Start

```bash
# Tests
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q

# Build
nix build .#jarvis --no-link && nix flake check

# WebUI
jarvis-webui  # port 8090
```

## Architecture

```
PersonaExecutor
  → TaskQueue (persistent)
    → Harness (pipeline engine)
      → LLM (via _default_call_llm)
        → Patcher + SafeEditor
          → Validator (syntax + tests)
            → Evaluator (review)
              → Checkpoint + Safety
                → Git commit
```

## Module Map

### Core (jarvis/core/)
- config.py — Configuration (31 imports)
- eventbus.py — Event bus (17 imports)
- memory.py — Episodic memory (17 imports)
- rag.py — Hybrid search (15 imports)
- voice.py — TTS/STT (9 imports)
- feedback.py — Notifications (9 imports)
- workspace.py — Project discovery (8 imports)
- persona.py — Persona registry (7 imports)
- gaming.py — Gaming mode (3 imports)
- health_monitor.py — Backend monitoring (3 imports)

### Nightwatch (nightwatch/)
- harness.py — Main execution engine
- task_queue.py — Persistent task queue
- patcher.py — LLM patch application
- safe_editor.py — Atomic writes
- validator.py — Syntax + test validation
- evaluator.py — Independent review
- checkpoint.py — State persistence
- safety.py — Branch isolation

### Control Plane (control_plane/)
- plane.py — Unified orchestration
- events.py — 58 event types
- state.py — Thread-safe state store
- commands.py — Typed command registry
- notifications.py — Multi-channel routing
- systemd_adapter.py — Safe systemctl

### WebUI (webui/)
- api.py — FastAPI backend (12 endpoints)
- server.py — Uvicorn launcher
- frontend/ — SvelteKit (12 routes, SSE)

## Services

| Service | Port | Status |
|---------|------|--------|
| llama-server | 8080 | Check health |
| embeddings | 8081 | Check health |
| rerank | 8082 | Check health |
| qdrant | 6333 | Check collections |
| WebUI | 8090 | Check /api/health |

## Tests

- 302/303 pass (1 pre-existing failure in test_integration.py)
- Core: eventbus, feedback, queue, harness_e2e, gaming
- Nightwatch: validator, safe_editor, safety, checkpoint
- Control Plane: events, state, commands, notifications
