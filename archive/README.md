# Archive — Removed Modules

These modules were archived on 2026-09-03 during codebase consolidation.

## Why Archived

The project had ~40% dead/duplicate code. These modules were either:
- Completely unused (0 external imports)
- Superseded by better implementations in nightwatch/
- Marked PAUSADO but never cleaned up

## Module Details

### orchestrator.py (core)
- **Was**: Task decomposition, persona assignment, workflow management
- **Replaced by**: nightwatch/harness.py + nightwatch/task_queue.py
- **Useful parts extracted**: Workflow definitions → kept in memory (not needed at runtime)

### workitem.py (core)
- **Was**: Kanban/Scrum work item management with WIP limits
- **Replaced by**: nightwatch/task_queue.py
- **Useful parts**: None — task_queue is strictly better

### subagent.py (core)
- **Was**: Isolated agent instances with context, tools, handoff
- **Replaced by**: nightwatch/harness.py (single agent with full pipeline)
- **Useful parts**: None — _execute() just returned a string

### context.py (core)
- **Was**: Context assembly pipeline (HANDOFF + RAG + Memory + Lessons)
- **Replaced by**: nightwatch/context_budget.py
- **Useful parts**: Layered context concept (broken implementation)

### agent_loop.py (core)
- **Was**: Multi-iteration LLM loop with tool calling
- **Replaced by**: nightwatch/harness.py (_request_structured_patch + execute_task)
- **Useful parts**: ToolExecutor with snapshot/rollback, TOOL_DEFINITIONS
- **Note**: This was actually better than harness in some ways, but the harness integration is more complete

### ast_guard.py (core)
- **Was**: AST validation with hash cache, safe str_replace
- **Replaced by**: nightwatch/safe_editor.py + nightwatch/validator.py
- **Useful parts**: safe_str_replace with AST guard

### learning.py (core)
- **Was**: Pattern detection from history, agent memory updates
- **Status**: Never imported by anything
- **Useful parts**: detect_recurring_patterns, log_event

### vision_analyzer.py (core)
- **Was**: OCR via tesseract, image metadata, screenshot analysis
- **Status**: Never imported by anything
- **Useful parts**: OCR pipeline, tool definition for agent

## What Was NOT Archived

These modules were considered useful and kept:
- health_monitor.py — continuous backend monitoring (better than doctor.py)
- audiobook_ui.py — rofi/waybar integration (niche but functional)
- All nightwatch/ modules — the real pipeline
- All control_plane/ modules — the real UI layer
- All providers/ modules — LLM abstraction

## Recovery

If you need code from an archived module:
1. Check the file for useful functions
2. Copy specific functions to the appropriate active module
3. Do NOT restore the entire file — it was archived for a reason
