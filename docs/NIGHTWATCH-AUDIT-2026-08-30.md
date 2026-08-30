# Nightwatch Audit — 2026-08-30

## Overview

Audit of nightwatch components to identify:
1. What works well
2. What could be ported to other JARVIS systems
3. What needs improvement
4. What is duplicated

## Nightwatch Components

### 1. checkpoint.py ✅ WORKS WELL

**Purpose**: Recovery system for the Nightwatch harness.

**Features**:
- Survives process crashes, context condensing, LLM failures
- Stores task state, git state, validation results
- Multi-project state tracking
- Session tracking (LLM calls, tool calls)

**Could Port To**:
- **REPL (dev.py)** — Save session state for `--continue`
- **Telegram bot** — Resume conversations
- **Any long-running process** — Recovery after crash

**Current State**: Only used by nightwatch

### 2. context_budget.py ⚠️ DUPLICATED

**Purpose**: Track context usage and inform condensing policy.

**Two Implementations**:
1. `jarvis/core/context_budget.py` — Truncates tool outputs by priority
2. `nightwatch/context_budget.py` — Tracks context usage metrics

**Could Port To**:
- **REPL** — Better context management
- **Agent** — Shared context budget logic

**Recommendation**: Consolidate into single implementation

### 3. safe_editor.py ✅ CRITICAL — NEEDED EVERYWHERE

**Purpose**: Safe file editing for LLM agents.

**Features**:
- Atomic writes (temp file → validate → rename)
- AST validation for Python
- Nix validation
- Markdown fence stripping
- Structural integrity checks
- Backup on failure

**Could Port To**:
- **devtools.py** — Replace current write_file/str_replace
- **MCP server** — Safe file operations
- **REPL** — Safe editing mode

**Current State**: Only used by nightwatch

### 4. validator.py ✅ WORKS WELL

**Purpose**: Validation pipeline for changes.

**Features**:
- Syntax validation (Python, Nix, JSON, YAML)
- Import integrity checking
- Test execution
- Full-suite fallback when no relevant test found

**Could Port To**:
- **devtools.py** — Validate before write
- **MCP server** — Validate file operations
- **REPL** — Pre-commit validation

**Current State**: Only used by nightwatch

### 5. evaluator.py ✅ WORKS WELL

**Purpose**: Independent review of changes.

**Features**:
- Structural checks (import removal, function removal)
- Diff analysis
- Quality assessment
- Auto-review for simple changes

**Could Port To**:
- **REPL** — Post-edit review
- **MCP server** — Code review tool
- **Telegram** — Review changes remotely

**Current State**: Only used by nightwatch

### 6. learning.py ✅ WORKS WELL

**Purpose**: Detect recurring patterns across runs.

**Features**:
- Pattern detection (code-quality, test-coverage, security)
- Agent memory updates
- Append-only audit trail

**Could Port To**:
- **REPL** — Learn from user interactions
- **Agent** — Improve over time
- **Any system** — Pattern detection

**Current State**: Only used by nightwatch

### 7. vault_sync.py ✅ WORKS WELL

**Purpose**: Sync JARVIS vault with Obsidian and HackMD.

**Features**:
- Sync to Obsidian (with frontmatter)
- Sync to HackMD (create/update)
- Search Obsidian vault
- Status reporting

**Could Port To**:
- **REPL** — Sync commands
- **MCP server** — Vault tools
- **Telegram** — Remote vault access

**Current State**: Only used by nightwatch

### 8. multi_agent.py ⚠️ EXPERIMENTAL

**Purpose**: Multi-agent primitives with persona handoff.

**Features**:
- Persona definitions (planner, builder, reviewer)
- Event Bus integration
- Handoff mechanism

**Could Port To**:
- **REPL** — Switch personas
- **Nightwatch** — Multi-agent execution
- **Future** — Team simulation

**Current State**: Experimental, not fully integrated

### 9. project_isolation.py ✅ WORKS WELL

**Purpose**: Isolates state between multiple projects.

**Features**:
- Project discovery
- State isolation
- Git state tracking

**Could Port To**:
- **REPL** — Multi-project support
- **Agent** — Project-aware context
- **Monorepo** — Better organization

**Current State**: Only used by nightwatch

### 10. safety.py ✅ WORKS WELL

**Purpose**: Protected paths and safety checks.

**Features**:
- Path protection
- Git operations safety
- Command validation

**Could Port To**:
- **devtools.py** — Safety checks
- **MCP server** — Protected operations
- **REPL** — Safety warnings

**Current State**: Only used by nightwatch

## Duplication Found

### 1. context_budget.py (2 implementations)

**Problem**: Two different implementations with different goals.

**Solution**: Consolidate into single implementation that:
- Tracks context usage (nightwatch version)
- Truncates tool outputs by priority (core version)
- Provides metrics for adaptive policies

### 2. checkpoint.py vs memory.py

**Problem**: Checkpoint (nightwatch) and memory (core) serve similar purposes but differently.

**Solution**: Checkpoint is for session recovery, memory is for knowledge. Keep separate but integrate:
- Checkpoint saves state
- Memory saves knowledge
- Both persist across sessions

## Porting Recommendations

### Priority 1: SafeEditor → devtools.py

**Why**: Prevents file corruption across all systems.

**How**:
1. Import SafeEditor into devtools.py
2. Replace write_file/str_replace with SafeEditor
3. Add AST validation for Python
4. Add Nix validation

### Priority 2: Checkpoint → REPL

**Why**: Enables `--continue` for REPL sessions.

**How**:
1. Import Checkpoint into dev.py
2. Save session state on each turn
3. Restore state on `--continue`
4. Integrate with memory.py

### Priority 3: Validator → devtools.py

**Why**: Validate before write, not just in nightwatch.

**How**:
1. Import Validator into devtools.py
2. Run syntax checks before write
3. Run import checks for Python
4. Provide validation report

### Priority 4: Learning → Agent

**Why**: Agent should learn from interactions.

**How**:
1. Import Learning into agent.py
2. Detect patterns from conversations
3. Update AGENTS.md automatically
4. Improve over time

### Priority 5: VaultSync → MCP Server

**Why**: Enable vault operations from any client.

**How**:
1. Import VaultSync into mcp_server.py
2. Add vault-sync tool
3. Add vault-status tool
4. Enable from REPL/Telegram

## Integration Plan

### Phase 1: Core Integration (This Week)

1. Consolidate context_budget.py
2. Import SafeEditor into devtools.py
3. Import Checkpoint into dev.py
4. Test all integrations

### Phase 2: MCP Integration (Next Week)

1. Import Validator into mcp_server.py
2. Import Learning into agent.py
3. Import VaultSync into mcp_server.py
4. Add new MCP tools

### Phase 3: Documentation (Following Week)

1. Create Mermaid diagrams for all integrations
2. Update AGENTS.md with new capabilities
3. Sync to HackMD/Obsidian
4. Test end-to-end

## Conclusion

Nightwatch has many components that work well but are isolated. Porting them to other JARVIS systems will:

1. Prevent file corruption (SafeEditor)
2. Enable session recovery (Checkpoint)
3. Validate changes (Validator)
4. Learn from interactions (Learning)
5. Sync knowledge (VaultSync)

The key insight: **Nightwatch is not just an autonomous agent — it's a collection of reusable components that should power all JARVIS systems.**

---

*Generated by Buffy (Codebuff) using JARVIS MCP tools*
