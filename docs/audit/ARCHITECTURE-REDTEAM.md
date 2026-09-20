# ARCHITECTURE RED TEAM — mapa atual (20/09, repo = verdade)

> Reconstrução executada 20/09 por 3 passes paralelos sobre o código.
> Complementa `docs/benchmarks/knowledge-system-benchmark-spec.md` (18/09,
> especificação) com o estado implementado + riscos verificados no código.
> Campanha: KNOWLEDGE → BEHAVIOR causalidade (experimentos A–J).

Base: `modules/ai/jarvis/src/jarvis/`. Registry: `models.nix:routing` →
`/etc/jarvis/model-registry.json`. Tiers: bonsai (speed, default), fast,
reasoning. Serviços: :8080 router, :8081 embeddings, :8082 rerank, :6333
Qdrant (`code_index`, `memories`, `books`).

## 1. Knowledge flow (implementado? testado? falha silenciosa?)

| Etapa | Arquivo | In→Out | Falha silenciosa? |
|---|---|---|---|
| Aquisição/validação | `core/doc_sources.py` | spec→spec validada | Não (retorna errs explícitos), sem teste dedicado |
| Sanitize (gate) | `core/doc_sanitize.py` | raw→SanitizedDoc ok/quarantine | **SIM parcial**: quarantine=None indistinguível de skip; só manifest JSONL |
| Index código | `core/rag.py::HybridIndexer` | arquivo→chunks 1200ch→embed→`code_index` | **SIM**: `return None` p/ quarantine/OSError/embed-fail/mtime-skip; `continue` por chunk |
| Index livros | `core/audiobook.py::index_book/sweep_books` | PDF/md→`books` | **SIM**: skips com `except OSError: pass`; só batch JSONL |
| Schema/bootstrap | `core/knowledge_schema.py` | →3 collections dense+sparse | Não (RuntimeError explícito) |
| Retrieval código | `core/rag.py::HybridSearch` + rerank top-5 + diversify | query→hits | **SIM**: embed-None→`[]`; rerank com fallback explícito `except→candidates` |
| Memória | `core/memory.py::EpisodicMemory` | evento→embed→`memories`; recall/lessons | **SIM**: tudo degrada p/ None/[]/"" |
| Lessons→prompt | `core/agent.py:1128` auto-inject `AVOID` | prompt→system augment | **SIM by design**: `try/except: pass`, sem métrica hit/miss |
| Vault | `core/vault.py::MemoryVault` | memories 7d→LLM→md+git+fact | `_git()` falha silenciosa (bool ignorado) |

**Fato arquitetural central:** `Agent.run` NÃO chama RAG. Conhecimento chega
ao agente via (a) lessons auto-injetadas, (b) aumento de prompt na camada
router/dev, (c) `execute_shell jarvis …`/MCP. RAG "funciona" ≠ RAG usado.

## 2. Agent loop (`core/agent.py`, ~3020 linhas)

Turno: wall-clock → LLM (`LLMClient.chat_with_tools`, profile por tier,
`max_tokens=ctx//12`, strict JSON p/ speed/fast) → repair malformed →
dispatch (reads paralelos ≤3; resto serial; `execute_shell` só com
mcp_servers) → artifact-check → validator → error 2x-nudge/3x-STUCK →
`_finalize` (completion.py: VERIFIED exige evidência).
ENFORCED (nega/para): allowlist, chaining/pipe gates, placeholder bars,
clobber bars, echo-ban pós-2º-repeat, approval jail, STUCK forcings,
budget-overflow. ADVISORY (texto): TOOL_USE_DISCIPLINE, framings,
STATE()/COVERAGE nudges, validator warnings (`valid=True` sempre).
Falha dominante: variância do modelo pequeno (read-first, 0/9 world-exact).

## 3. Dois loops (estado diverge)

Core `Agent.run`: run evidenciado (verdict, audit JSONL, STUCK honesto).
`cli/dev.py`: REPL/sessão interativa — sucesso = texto, SEM completion gate,
SEM AgentResult, 21 tools próprias, auto-commit. Compartilham só disciplina,
LoopDetector, validator, LLMClient, EpisodicMemory. Risco: rc=0 em texto
não-verificado; dois `detect_profile` podem discordar.

## 4. MCP (33 declared + 4 shadow, sem gating em tools/list)

Três esquemas distintos: MCP flat (33), DEV_TOOLS (10+1), Agent schema
(9 + execute_shell condicional). `book_*` só no Agent; memory/vault/rag só
via MCP/CLI. "MANDATORY recall/lessons" = prosa; enforced real: lessons
auto-inject + TOOL_USE_DISCIPLINE. **Approval gap**: Agent exige
approve+human_approve (shell sensível, writes); MCP `call_tool` não —
`jarvis_write_file/str_replace` vão direto ao devtool. `make_run`
confirm=true é o único gate MCP. Shadow: proactive_check, system_health,
classify ×2 (callable, invisíveis). Host roda root → JSONL auto-desligado
(`JARVIS_JSONL=1` p/ forense).

## 5. Observabilidade

`core/logging.py` JSONL (apagável por env/uid), `SessionTelemetry`
(sys/tools/msgs por chamada, cap 2000), audit JSONL de shell, eventbus com
DLQ, `eval_rag --seed` (11 queries, P/R/NDCG), `benchmark.py` (latência por
rota), `eval_harness.compare` (A/B com world_check — anti-false-green).
Nada conta quarantine-rate, embed-fail-rate, recall-hit-rate no path real.

## 6. Dívidas / achados (viram §55: reproduzir→dono→teste→fix)

1. Read-path inteiro degrada p/ "" / "No results found" e o agente continua
   (retrieval failure indistinguível de "não há conhecimento" — §27).
2. Approval gap MCP vs Agent (§51: classificar boundary, não afrouxar).
3. Dois "vaults" homônimos (MemoryVault Qdrant-fact vs Obsidian rg).
4. Três esquemas de tools sobrepostos; 4 shadow tools.
5. `test_mcp_tools_e2e` 21 testes = integration (skip no sandbox — cobertura
   MCP real só no host).
6. `scripts/ingest_books.py` citado em docstring mas inexistente (caminho
   vivo = audiobook.py via `_handle_rag_index`).
7. Root JSON scan do completion só top-level; suffix-match pode over-creditar.

## 7. Status por claim (§67)

VERIFIED (código+lido): strict-tier default, killpg tree-kill, lessons
auto-inject, completion gates, world_check veta texto, quarantine gate.
PARTIALLY: rerank (fallback silencioso), vault git, MCP approval.
UNVERIFIED→experimentos A–J: causalidade RAG/memória/lesson, substrate
selection, MCP confusion em Bonsai, context ablation, provenance, temporal.
