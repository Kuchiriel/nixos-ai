# RUNTIME FORENSICS — estado real em 586ec31 (26/09/2026)

> Mapa do código COMO ELE É, não como os docs dizem. Linhas = `rg -n` exatas no snapshot.
> Base: `modules/ai/jarvis/src/jarvis/`. ~13k linhas só no runtime/harness.

## 1. Os três loops cognitivos (semânticas DIFERENTES, não só nomes)

| Dimensão | `core/agent.py:Agent.run:1057` (3173 ln) | `cli/dev.py:_run_agent_loop:1997` (3078 ln) | `nightwatch/harness.py:Harness.run:1687` (1908 ln) |
|---|---|---|---|
| Unidade | 1 prompt → N turnos; `MAX_TURNS=8:393`, `MAX_TIME_S=600:397` | 1 sessão REPL → N tasks; inner 30 turnos, auto-compact 70%→50% (`:2025-2030`) | N tasks → 1 patch-tentativa cada; `max_retries` + `max_minutes` + `RUNNING.lock` |
| Chamada LLM | `_get_llm_response:2889` → `LLMClient.chat_with_tools` + repair de args + steer + cascata remota 1x (`_try_api_cascade:2509`) | `_call_llm:1002` → `chat_with_tools` direto, sem repair/steer | `_request_json_patch:617` (grammar JSON determinística PRIMEIRO) → fallback texto + `parse_llm_patch`; prompt com `recovery_ctx+lessons+previous_errors` |
| Parser tool-call | `extract_fallback_tool_calls:306` (xLAM arrays) + nudge `STATE(no_tool_call)` | `_parse_text_actions:1883` (Hermes `<function>` vence tudo, senão SEARCH/REPLACE+`>>>READ`+shell+JSON) + promise-nudge + claim-checker (`:2128`) | `parse_llm_patch` só entende `=== FILE/CREATE/WHOLE` ou JSON `{patches}` |
| Execução | serial + batch paralelo só `read_file`; `execute_shell` com `command_allowed` + audit + `obs_cache` | serial; `Confirm.ask` p/ shell/browser (ou `approve/yolo`); `EDIT_HISTORY`+`/undo`; sem audit | só `SafeEditor.apply_edit(validate=True)`; shell SÓ dentro de `validate_change` |
| Veredito final | `completion.check_completion:599` → VERIFIED/UNVERIFIED + `verify_turns≤2` + `_finalize:973`; STUCK/STOPPED honestos | `check_completion` 1x bounded só p/ artefato (`:2152-2188`); trailing-error ignorado | `validate_change:1511` (sintaxe/imports/testes) + `review_change:1534` independente + `_verify_completion_evidence:1597` pós-merge |
| Commit | não commita | `_auto_commit:1114` por-arquivo pós-diff | `_git_commit:927` na task-branch + `merge_task_branch:1593` (sem merge = falha) |
| Isolamento | jail via `command_allowed` | write-jail, escreve na worktree atual | branch por task + `abort` em TODO erro — main intocada até merge |
| Estado | efêmero (sem persistência) | `dev-session-<proj>.json:544` (+`.enc`); resume/continue | `Checkpoint` por task + `TaskQueue` persistida + `Mission` + `platform_bridge` log |
| Retry | `LoopDetector` + cascata API no teto + `_mal_streak≥3` STUCK | `LoopDetector` (aborta honesto) + nudges limitados | `previous_errors` no prompt (aprende) + recria branch + `LoopDetector(task.id)` cross-run→BLOCKED + ratchet em `AGENTS.md` + backoff só TRANSIENT |
| Persona | gate: explícita sempre, implícita só se prompt domain; + `ModelPolicy.framing` + skills + user_profile + env | sempre ativa (`jarvis` default); persona filtra schema anunciado; `native/text` por `native_tools` | sem persona (só etiqueta p/ log); comportamento vem de `risk` |
| Interatividade | nenhuma (`human_approve` callback) | total (REPL + 10 slash cmds) | nenhuma (pause-file gate, Telegram, dry_run) |

**Terceiro executor órfão**: `core/persona_executor.py:PersonaExecutor.execute_with_persona:84` —
só chamado por `cli/main.py:1547`, reacopla `Harness:61-83` após declarar independência (`:9`).

## 2. Tool schemas em 4 dialetos

- `mcp_server.JARVIS_TOOLS:54` (`jarvis_read_file:path/offset/limit`, `jarvis_str_replace:old_string/new_string`)
- `devtools.DEV_TOOLS:1348` (`read_file`, `str_replace:old/new/allow_multiple`; `execute_shell` FORA de propósito `:1436`)
- `persona.CAPABILITY_TOOLS:481` (cita `remember/recall/nix_eval/read_chatgpt` — NÃO existem em nenhum schema)
- `providers/mcp.to_function_tools:196` (conversor MCP→OpenAI usado por `agent.py:346`)
- `mcp_server.py:625-631` traduz manualmente; `DEV_TOOLS` importado em `mcp_server.py:39` mas NUNCA usado.
- Declaração LLM: `agent.py:2910-3104` (10 tools, progressive-disclosure `:3046-3067`) vs
  `dev.py:_get_tools:1496` (~21 dicts + `filter_tools:1822`).

## 3. Contexto/tokens em 4 vias

`context_budget.ContextBudget.estimate_tokens:342` (+`_calibration_ratio:352` → delega parcial p/
`tokens.py`) × `tokens.estimate:49` × `dev._estimate_tokens:373` (7 call sites) ×
`agent._truncate_history_for_send:208` + `_ctx_derived_max_tokens:68`. A docstring de
`context_budget.py:1-7` ADMITE a consolidação pendente; `nightwatch/context_budget.py:8` é shim.
`n_ctx` lido em 5 lugares sem hierarquia (`provider_registry:40` vs `/slots` vivo vs `llm_llama_cpp:136`…).

## 4. RAG/busca em 4 fachadas · ensure ×4 · embed ×5

- Busca: `rag.HybridSearch.search:676` (ÚNICA com RRF+boosts+diversify+rerank) ×
  `devtools.semantic_search:698` (LLMClient+Qdrant próprios) × `router.handle_rag:379` ×
  `mcp._handle_rag_search:936`.
- Ensure: `vector_store:114` × `rag:484` × `memory:92` × `knowledge_schema:93`.
- Embed: `embedding.embed_long:74` × `LLMClient.embed:741` × `llama_cpp:369` × `prismml:161` × `remote:94`.
- Backends LLM clonados: `llm_llama_cpp:63` × `llm_prismml:60` (diff 364 ln; Prism sem stream/thinking).

## 5. Roteamento ×4 · saúde ×5 · cripto ×2

- Roteamento: `router.route_request:241` × `provider_registry.route:197` × `agent.detect_profile:36` ×
  `tool_surface.classify_task:53`. `agent.py` NÃO chama `route_request` (cascata paralela).
- Saúde: `router.handle_doctor:327` × `doctor.*:328/343/43/61/71` × `health_monitor:45` ×
  `llm.is_available/get_slots_status` × `http_service:20`.
- Cripto: `vault_cipher:34/118` × `rag_crypto:28/56` — nenhum usado por `vault.py` (plaintext+git).
- Memória em 3 camadas sem fronteira executada: `rag` (conhecimento) vs `memory.EpisodicMemory`
  (experiência) vs `vault.MemoryVault` (síntese) — `vault.summarize:149` regrava `kind=fact`
  no `memories` (loop memória→vault→memória). Paths de vault em 4 lugares
  (`vault.py:68` vs `mcp_server:436,467` vs `spaces.py:65` vs `vault_cipher:57`).
- `persona.filter_tools:503` × `tool_surface.surface_for:79` × filtros inline (`agent:1106`, `dev:1824`).

## 6. Quem chama o quê (choke points reais hoje)

- LLM: `LLMClient` ← agent, rag, memory, vault, devtools, main, dev, webui, harness (ÚNICO ponto são — preservar).
- Tools exec: `devtools.handle_dev_tool:1603` ← mcp_server:625, dev.py (preservar como primitiva).
- Completion: `check_completion` ← SÓ agent.py + dev.py lazy (mcp/nightwatch/router NUNCA chamam).
- `route_request` ← main:624, telegram:542, voice:828, benchmark:62 (agent.py NÃO usa).
- `JARVIS_TOOLS` ← SÓ `webui/api.py:206` + stdio `main:1011`.
- RAG chega ao agente SÓ via tools (`book_search`, shell grep) — `Agent.run` NÃO injeta retrieval
  (red-team confirma); lessons entram (`memory.lessons:1157`), persona/mode entram sempre em dev.

## 7. Decisão canônica (evidência, não preferência)

**`agent.py:Agent.run` vence como base do kernel**: único com vereditos honestos
(VERIFIED/UNVERIFIED/STUCK/STOPPED), repair de args, cascata, budget-overflow-stop,
`verify_turns` limitado e `finalize` com evidência. `dev.py` contribui: sessão/compaction,
claim-checker, promise-nudge, catálogo amplo, approval UX. Nightwatch contribui: supervisor
(branch/checkpoint/review/ratchet) — mas como CAMADA sobre o runtime, nunca como loop.
Detalhe e migração em `docs/audit/RECONSTRUCTION-PLAN.md`; contrato em
`docs/architecture/ADR-005-agent-runtime-kernel.md`.
