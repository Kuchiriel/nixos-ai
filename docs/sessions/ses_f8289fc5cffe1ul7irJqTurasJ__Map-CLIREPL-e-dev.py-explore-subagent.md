# Map CLI/REPL e dev.py (@explore subagent)

- **sessão:** `ses_f8289fc5cffe1ul7irJqTurasJ`
- **quando:** 2026-09-07 20:01 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 11 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Explore the JARVIS codebase at /home/nixos/projects/nixos-ai/modules/ai/jarvis/src. Be very thorough. Focus on the production CLI/REPL entrypoints and the suspected duplication between cli/dev.py and core/agent.py.

Read these files:
- jarvis/cli/main.py (1407 lines)
- jarvis/cli/dev.py (2529 lines)
- jarvis/cli/launcher_main.py

Report precisely:
1. What is the actual production entrypoint (which main() is called by the `jarvis` command/console_scripts)? Check pyproject.toml in /home/nixos/projects/nixos-ai/modules/ai/jarvis for entry points.
2. In main.py: how does the REPL loop work? List every function that handles a query (route handler). Which one calls Agent or router? List all hardcoded values found (ports, paths, model names, timeouts, thresholds).
3. In dev.py: what is this file? Is it a REPL? Does it have its own agent loop? Does it duplicate Agent.run(), tool execution, RAG search, memory, MCP? List the main classes and public functions in dev.py with line numbers. Specifically check: does dev.py have its own LLM call code, its own tool registry, its own RAG, its own memory/recall, its own eventbus? Where does dev.py's loop live and does main.py or anything import dev.py?
4. Check who imports dev.py across the whole repo (grep in src/ and tests/).
5. In launcher_main.py: what does it do?

Return a structured report with file:line references for each finding. Do NOT modify anything.

---

## · ?

I'll explore the JARVIS codebase thoroughly. Let me start by examining the structure and reading the key files in parallel.

---

## · ?

The pyproject.toml is clear: `jarvis = "jarvis.cli.main:main"` is the production entrypoint. Now let me read the main files and get structural overviews.

---

## · ?

Now let me read main.py in full detail. I'll read it in sections.

---

## · ?

main.py is fully covered. Now let me read dev.py thoroughly.

---

