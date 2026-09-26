"""JARVIS Agent Runtime Kernel (ADR-005).

Um único loop cognitivo (`AgentRuntime.run`), consumido por adapters finos
(CLI/REPL, MCP, Nightwatch-supervisor, voz, WebUI, Telegram, benchmarks).

Fase 1: shell do kernel + ToolRegistry (leitura das fontes existentes, zero
mudança de comportamento) + linter estrutural anti-drift.
"""
