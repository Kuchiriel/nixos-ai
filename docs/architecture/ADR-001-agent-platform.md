# ADR-001: JARVIS Agent Platform Architecture

## Status: Accepted

## Context

JARVIS currently has 62+ Python modules with no communication between them. The user needs a monorepo-capable agent platform that can:
- Discover and work across multiple projects
- Use different personas/roles
- Manage work items persistently
- Maintain layered memory
- Execute autonomously for hours
- Recover from failures

## Research Summary

### Key Sources
1. **Nx Monorepo Advantage** (2026): "Three Walls" - Read, Write, Memory
2. **OpenDev Paper** (arxiv 2603.05344): Four-layer architecture, adaptive context compaction, lazy tool discovery
3. **Sourcegraph Context Engineering** (2026): Four pillars - Instructions, Retrieval, Memory, Tools
4. **Durable Execution** (AgentMarketCap 2026): 73% agent deployments fail without durability
5. **Augment Code Multi-Agent** (2026): Six coordination patterns for parallel agents

### Architectural Decisions

#### D1: Lightweight Core, Not Framework Wrapper
JARVIS will NOT wrap LangGraph, CrewAI, or Temporal. It will implement minimal primitives directly, using these frameworks as reference only.

**Rationale**: Local LLM constraints (32K context, 6GB VRAM) make framework overhead unacceptable. Simple JSON state + file-based persistence is sufficient.

#### D2: File-Based State, Not Database
All persistent state lives in `~/.local/state/jarvis/` as JSON/JSONL files.

**Rationale**: NixOS declarative model, Btrfs snapshots for recovery, no additional dependencies.

#### D3: Layered Context (OpenDev-inspired)
```
HANDOFF.md (index, ~100 lines)
    ↓
RAG search + Memory recall (just-in-time)
    ↓
read_files() for specific modules
```

**Rationale**: 32K context window cannot hold the full codebase. Just-in-time retrieval is mandatory.

#### D4: Coordinator/Specialist/Verifier Pattern
From Augment Code's research: separate planning, execution, and validation into explicit roles.

**Rationale**: Prevents the "LLM does everything" anti-pattern that causes code corruption.

#### D5: Workspace Discovery via Manifest Files
Each project declares itself via `jarvis.yaml` (or auto-detected from structure).

**Rationale**: Nx-style "affected projects" requires knowing project boundaries.

#### D6: Persona as Data, Not Code
Personas defined in YAML, loaded at runtime. No persona classes.

**Rationale**: User should be able to create personas without modifying Python code.

#### D7: Memory Layers
- Working memory: current task context (in LLM window)
- Episodic memory: what happened (JSONL log)
- Semantic memory: facts (Qdrant vector store)
- Project knowledge: AGENTS.md, manifest, dependency graph

**Rationale**: Different memory types serve different purposes. Mixing them causes confusion.

## Architecture

```
jarvis/
├── core/
│   ├── workspace.py      # Project discovery, manifest, dependency graph
│   ├── persona.py        # Persona registry (data-driven)
│   ├── agent.py          # Agent execution engine (existing, enhance)
│   ├── orchestrator.py   # Supervisor/subagent dispatch
│   ├── workitem.py       # Work item engine (Kanban/Scrum agnostic)
│   ├── memory.py         # Layered memory (existing, enhance)
│   ├── context.py        # Context assembly pipeline
│   └── model_policy.py   # Model routing per workflow
├── tools/                # Existing tools (filesystem, git, shell, etc.)
├── workflows/            # Workflow definitions (YAML)
├── personas/             # Persona definitions (YAML)
└── cli/                  # CLI entry points
```

## Data Flow

```
User Request
    ↓
Context Assembly (HANDOFF + RAG + Memory)
    ↓
Orchestrator (select persona, decompose task)
    ↓
Agent (execute with tool set)
    ↓
Validator (AST, tests, lint)
    ↓
Commit / Rollback
    ↓
Memory Update (episodic + project knowledge)
```

## Success Criteria

1. Agent can discover all projects in ~/projects/
2. Agent can select appropriate persona for a task
3. Work items persist across restarts
4. Context assembly uses RAG, not brute-force file reading
5. Code changes validated by AST before commit
6. Memory accumulates across sessions
