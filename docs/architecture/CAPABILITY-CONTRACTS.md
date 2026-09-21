# CAPABILITY CONTRACTS (Ciclo 3 — PHases 8-9; owners = repo real)

| Capability | Owner | Input | Output | Auth state | Verification | Failures | Observability | Regression |
|---|---|---|---|---|---|---|---|---|
| RAG retrieve | `core/rag.py::HybridSearch` + `vector_store.QdrantStore` + embed :8081 | query | hits+provenance | Qdrant `code_index`/`books` | fonte existe+metadata bate | unavailable/empty/stale/malformed | eval_rag P/R/NDCG | `test_rag*`, R1-C2 |
| Memory persist/recall | `core/memory.py::EpisodicMemory` (`memories`) | evento/query | id/hits | Qdrant `memories` | persistência+retrieval (+comportamento) | write-fail vs empty (distinguir) | count(), lessons_unavailable | `test_memory*` |
| Lessons transfer | `memory.remember_lesson` + lint (`lesson_lint`) + inject `agent.py:1128` | falha | regra value-free | `memories` kind=lesson + meta | retrieval + melhora futura | valores episódicos (lint) | AVOID-inject, supersede | `test_lesson_lint*`, R2 |
| Self-knowledge | filesystem/Git/Qdrant/config (hieraquia PHASE 6) | pergunta de estado | claim+evidência | LIVE>FS>Git>gen>índice>docs>mem>modelo | inspeção autoritativa | palpite plausível (Ga) | grounding class | Ga/Gb tasks |
| MCP expose | `mcp_server.JARVIS_TOOLS` + handlers | chamada | observação | runtime | tool→args→obs→mundo | approval-gap (boundary doc) | isError, metricas | `test_mcp*` |
| Disclosure | `core/tool_surface` + `Agent.tool_class` | task+classe | schema reduzido | código | seleção correta 1ª tool | attractor (read_file) | entropy_metrics | `test_tool_surface*` |
| Completion | `core/completion.py` + world_check | trajetória | VERIFIED/... | mundo | estado real | stale (flag), vácuo | evidence/missing | `test_completion*` |

Políticas prompt-only (honesto, NÃO enforcement): MANDATORY recall/lessons
(descrições MCP), framings, nudges STATE/COVERAGE. Enforcement real:
allowlist/gates, approval jail, STUCK forcings, quarantine, verdicts,
world_check. Runtime novo só onde evidência ≥ n=3 com replicação:
tool_class filter (E6), lesson lint (R2), outage emit (J), stale flag.
