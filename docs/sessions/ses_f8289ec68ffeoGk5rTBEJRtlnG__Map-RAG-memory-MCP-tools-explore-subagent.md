# Map RAG, memory, MCP tools (@explore subagent)

- **sessão:** `ses_f8289ec68ffeoGk5rTBEJRtlnG`
- **quando:** 2026-09-07 20:01 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 8)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Explore the JARVIS codebase at /home/nixos/projects/nixos-ai/modules/ai/jarvis/src. Be very thorough. Focus on RAG, memory, MCP, and tool duplication.

Read these files:
- jarvis/core/rag.py (517 lines)
- jarvis/core/memory.py
- jarvis/core/legacy_index.py (338 lines)
- jarvis/providers/vector_store.py (175 lines)
- jarvis/providers/reranker.py
- jarvis/providers/mcp.py
- jarvis/mcp_server.py
- jarvis/core/vault.py
- jarvis/core/semantic_search... (if exists, glob)
- jarvis/core/tokens.py
- jarvis/core/context_budget.py (673 lines)
- src/nightwatch/context_budget.py

Report precisely:
1. RAG: what classes/functions exist for search? List every distinct search function across the whole src tree (semantic_search, rag_search, hybrid search, search_code, retrieve_context, etc.) with file:line. Do they overlap/duplicate? What collections does Qdrant use? Is there project isolation (per-project collections or filters)?
2. Memory: what does core/memory.py provide? What's the class list? How does remember/recall/lessons work? Where is episodic memory stored? Does memory overlap with vault.py and with the memories Qdrant collection?
3. MCP: what MCP tools are exposed in mcp_server.py (list all tool names)? Which duplicate native capabilities (rag/memory/voice/filesystem)? What is providers/mcp.py (client)? 
4. Context budget: compare the two context_budget.py implementations (core vs nightwatch) - classes, thresholds, methods. Are they copies?
5. tokens.py: what does it do? Does it overlap with context_budget?
6. List every file that does `rag` import and call in src and tests.

Return structured report with file:line references. Do NOT modify anything.

---

## · ?

I'll explore the JARVIS codebase thoroughly. Let me start by mapping the directory structure and locating the key files.

---

## · ?

Now let me read the key files in parallel batches.

---

## · ?

Now let me read the remaining core files.

---

## · ?

Now the MCP files and both context budget implementations.

---

## · ?

Now the two context budget implementations.

---

## · ?

Now let me search for all search-related functions, Qdrant collection usage, and rag imports across the tree.

---

## · ?

Let me examine the other search implementations found: devtools.semantic_search, audiobook.search_book, memory_bridge.recall_relevant_lessons.

---

