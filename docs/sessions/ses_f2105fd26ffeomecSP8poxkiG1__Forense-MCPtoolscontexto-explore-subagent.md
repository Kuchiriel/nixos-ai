# Forense MCP/tools/contexto (@explore subagent)

- **sessão:** `ses_f2105fd26ffeomecSP8poxkiG1`
- **quando:** 2026-09-26 18:28 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No repo /home/nixos/projects/nixos-ai, análise forense read-only (NÃO edite) destes arquivos: modules/ai/jarvis/src/jarvis/mcp_server.py (~1034 linhas), modules/ai/jarvis/src/jarvis/core/devtools.py (~2095), modules/ai/jarvis/src/jarvis/core/completion.py (~955), modules/ai/jarvis/src/jarvis/core/context_budget.py (~744), modules/ai/jarvis/src/jarvis/core/router.py, modules/ai/jarvis/src/jarvis/core/persona.py, modules/ai/jarvis/src/jarvis/core/persona_executor.py, modules/ai/jarvis/src/jarvis/core/memory.py, modules/ai/jarvis/src/jarvis/core/rag.py, modules/ai/jarvis/src/jarvis/core/vault.py, modules/ai/jarvis/src/jarvis/providers/. Para cada um retorne: exports principais (classes/funções + linhas), quem chama quem (callers reais via grep), e o que DUPLICA outro componente (ex: outro schema de tools, outro context budget, outro model detection). Feche com lista ranqueada das 10 duplicações mais graves com evidência (arquivo:linha dos dois lados).

---

## · ?

Mapeando exports, callers e sobreposições — varredura forense em curso.

---

## · ?

Inventário de módulos concluído — agora extraindo classes e funções de cada alvo.

---

## · ?

A busca ampla retornou ruído — vou refinar para extrair os símbolos exatos.

---

## · ?

Símbolos centrais extraídos — agora rastreando quem chama quem no repo.

---

## · ?

# Forense read-only — `nixos-ai` JARVIS (11 alvos)

Base: `/home/nixos/projects/nixos-ai` — `wc -l` confirmado: `mcp_server.py:1034`, `devtools.py:2095`, `completion.py:955`, `context_budget.py:744`, `router.py:478`, `persona.py:632`, `persona_executor.py:289`, `memory.py:353`, `rag.py:766`, `vault.py:204`.

## 1. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/mcp_server.py`

Exports (top-level `def`, `rg -n ^def`):
- `handle_request:379`, `_vault_sync_to_obsidian:431`, `_vault_sync_to_hackmd:463`, `_vault_read_from_obsidian:500`, `_vault_status:527`, `_mcp_mutation_policy:551`, `_mcp_audit:559`, `_guarded_mutation:572`, `call_tool:586`, `_handle_nix_search:750`, `_handle_remember:848`, `_handle_recall:864`, `_handle_lessons:884`, `_handle_vault_list:898`, `_handle_vault_write:911`, `_handle_rag_search:936`, `_handle_rag_index:983`, `main:1011`
- Constante schema: `JARVIS_TOOLS:54` (~20 tools `jarvis_*` + `*HACKMD_TOOLS:336` + `*MAKE_TOOLS:337` + 4 vault-sync `340,348,356,367`).
- Imports agregadores: `devtools.handle_dev_tool+DEV_TOOLS:39`, `vision.VISION_TOOL:40`, `chatgpt_reader.CHATGPT_READER_TOOL:41`, `multi_ai_reader.MULTI_AI_READER_TOOL:42`, `hackmd.HACKMD_TOOLS:43`, `make_ops.MAKE_TOOLS:44`.

Callers reais (`rg call_tool|handle_request|JARVIS_TOOLS`):
- Único produtivo: `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/webui/api.py:206` (`mcp_tools` importa `JARVIS_TOOLS`), `:220,229` (`mcp_call` → `call_tool`). Interno `:412` (`handle_request→call_tool`), `:1022` (`main` loop stdio).
- Resto é teste: `tests/test_mcp_server.py:2,28,39`, `tests/test_mcp_vault_search.py:8,14`, `tests/test_make_ops.py:17,25,27`. `tests/test_harness_e2e.py:770` referencia `TOOL_SCHEMAS` inexistente (string em teste).
- `providers/mcp.py:108 MCPClient.call_tool` é homônimo **não-relacionado** (cliente MCP genérico, usado por `router.py:360` e `agent.py:346`).

Duplica:
- Schema de tools (ver §Duplicações #1): `JARVIS_TOOLS:54-378` re-descreve `read_file/write_file/str_replace/execute_shell` já definidos em `devtools.DEV_TOOLS:1348` com nomes/parâmetros divergentes (`old_string/new_string` vs `old/new` em `devtools.handle_dev_tool:1606`).
- `DEV_TOOLS` importado em `:39` mas **nunca usado** no arquivo (só `handle_dev_tool` é chamado em `:625,628,631`) — import morto / schema fantasma.
- `_handle_remember:848/_recall:864/_lessons:884` são wrappers finos sobre `EpisodicMemory.remember/recall/lessons` (`memory.py:100,202,268`). `_handle_rag_search:936/_index:983` wrappers sobre `HybridSearch:676/HybridIndexer:475` (`rag.py`). `_handle_vault_list:898/_write:911` wrappers sobre `MemoryVault.list_notes:96/read_note:113` (+ escrita direta, não `summarize:149`).
- Vault-sync próprio `_vault_sync_to_obsidian:431` (hardcode `~/vaults/projects/nixos-ai:436` + `~/vaults/projects:437`) duplica `vault.MemoryVault.vault_dir:68` + `spaces.Space.vault_dir` (`core/spaces.py:65`) + `vault_cipher.note_path` (`core/vault_cipher.py:57`).

## 2. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/devtools.py`

Exports:
- Path/guard: `_project_root:39`, `resolve_base:45`, `_immutable_input:86`, `_safe_path:104`, `_validate_python_syntax:233`, `_ast_guard:242`, `_normalize_line:311`, `_normalize_text:315`, `_fuzzy_find:319`, `_find_context:371`, `_make_diff:403`
- Tools: `read_file:414`, `str_replace:488`, `execute_shell:645`, `semantic_search:698`, `write_file:746`, `list_directory:844`, `code_search:918`, `run_tests:968`, `run_linter:1015`, `jarvis_command:1050`, `sanitize_secrets:1087`, `build_json_dataset:1140 (+_fk_candidate:1169,_num:1215)`, `load_skill:1305`, `human_click:1317`, `human_type:1327`, `human_key:1336`, `handle_dev_tool:1603` (+dispatch `1605-1624`, required-check `1633-1652`)
- `DEV_TOOLS:1348` (schemas OpenAI-function, `execute_shell` deliberadamente **fora**, comentário `:1436`), SafeEditor: `compute_checksum:1682`, `detect_language:1687`, `strip_markdown_fences:1702`, `validate_content:1719`, `safe_write_file:1831`, `validate_file:1928`, `run_validation_checks:2074`

Callers reais:
- `mcp_server.py:39,625,628,631` (read/write/str_replace via `handle_dev_tool`).
- `cli/dev.py:40,207` (`write_file`), `router.py:401` (`read_file`), `doc_sanitize.py:397` (`_safe_path` privado cruzado), `agent.py:748,2396` (`resolve_base`), `:1795,1819` (`build_json_dataset,sanitize_secrets`), `:1977` (bloco devtools), `:2699,2757` (`read_file,list_directory` canônicos), `completion.py:609` (`resolve_base` lazy).
- Testes: `test_devtools.py:10,396,411,437,478`, `test_devtools_gates.py:7,17,28`, `test_humanize.py:42`, `test_skills.py:101`.

Duplica:
- **Dois writers**: `write_file:746` vs `safe_write_file:1831` (ambos backup+validação; segundo portado do nightwatch, comentário `:1678`). `validate_content:1719/validate_file:1928/run_validation_checks:2074` vs `core/validator.py:32,149 ToolValidator` vs `completion._residual_secret*:191,208`.
- **Dois searchers RAG**: `semantic_search:698` (usa `LLMClient+QdrantStore:705-706`) vs `rag.HybridSearch.search:676` vs `router.handle_rag:379` vs `mcp._handle_rag_search:936`.
- `_safe_path:104` vs `paths.set_project_root/get_project_root` (`core/paths.py:65`) vs `resolve_base:45` vs `_project_root:39` — 3 raízes (`completion.py:609` re-resolve, `agent.py:748,2396` re-resolve).

## 3. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/completion.py`

Exports: `_norm:22`, `CompletionVerdict:34`, `_find_placeholder_value:62`, `_claimed_change:136`, `_claimed_content_change:159`, `_claimed_noop:168`, `_residual_secret_in_file:191`, `_residual_secret_paths:208`, `_successful_calls:230`, `_mutating_shell:258`, `_shell_cmds:263`, `_denied_but_observed:294`, `_claimed_artifacts:315`, `_claimed_contents:330`, `_read_paths:347`, `_written_paths:365`, `_shell_write_paths:389`, `_is_error_output:424`, `_unexecuted_read_instructions:443`, `_last_tool_error:469`, `_any_tool_success:480`, `_pending_recovery_notes:489 (+_args:500,_exec_after:511,_read_ok_after:522)`, `missing_deliverables:554`, `check_completion:599`, `classify_error:942`.

Callers reais: só `core/agent.py:981,1418,2029,2276,2395` (veredito pós-loop + `classify_error` + `missing_deliverables`) e `cli/dev.py:2161` (lazy). Todo resto é `tests/test_completion.py` (~30 imports). Nenhum caller em `mcp_server/router/persona_executor`.

Duplica:
- Pós-condição triplicada: `check_completion:599` (AST-parse, existe-arquivo, trailing-error, recovery-notes) vs `judge.judge_grounding` (`core/judge.py:41`) vs `validator.ToolValidator` (`core/validator.py:149`) vs checks inline em `agent.py:417,471,519,553,591,657,738` (`_secret_worked_example,_partial_coverage_note,_check_run_json_artifacts,_missing_binary_hint,_unexecuted_script_note,_unread_refs_note,_placeholder_script_note` — mesma família `_unexecuted_*`, `_claimed_*`).
- `classify_error:942` vs `agent._missing_binary_hint:553` vs heurísticas de erro em `heal.py/watchdog.py`.

## 4. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/context_budget.py`

Exports: `CHARS_PER_TOKEN:29 (=4)`, `TOOL_OUTPUT_PRIORITY/TRUNCATE_LIMITS:32,50`, `STATE_DIR/CONTEXT_LOG:58`, `query_server_context_size:60`, `TelemetryCall:104`, `SessionTelemetry:122 (+record:133,total_*:159-167,n_calls:171,last:175,avg_tps:179,avg_ttft:184,window_pct:189,window_bar:194,render:201,payload_summary:218)`, `ContextSnapshot:241`, `_anchor_lines:262`, `ContextBudget:273 (+__post_init__:308,available:317,used:321,remaining:325,usage_percent:329,needs_warning:335,is_overflow:339,estimate_tokens:342,_calibration_ratio:352,record_actual:367,record_actual_for_text:378,sync_from_slots:392,add_message:403,get_budget_warning:430,truncate_tool_outputs:443,compress_history:476,record_snapshot:544,should_compact:570,record_compaction:576,record_llm_call:598,record_tool_call:603,get_recommendation:607,get_stats:643,to_dict:694,from_dict:710,_log_snapshot:726,_log_event:740)`.

Callers reais: `core/agent.py:342` (único produtivo — `ContextBudget` no loop), `providers/llm.py:278` (`SessionTelemetry` lazy), `cli/dev.py:394` (telemetria REPL), `nightwatch/context_budget.py:8` (re-export compat), testes `test_p7_context_budget.py:16`, `test_llm_backend.py:446-515`, `test_loop_detector.py:8`.

Duplica (ver #2):
- `CHARS_PER_TOKEN:29` ≡ `tokens.CHARS_PER_TOKEN` (`core/tokens.py:27`); `estimate_tokens:342` + `_calibration_ratio:352-359` (delega p/ `tokens.calibration_ratio`) ≡ `tokens.estimate:49/estimate_messages:63`; `cli/dev.py:_estimate_tokens:373` é **terceira** implementação (usada em `:460,463,663,2025,2028,2380,2419,2421`), `agent._truncate_history_for_send:208` + `_ctx_derived_max_tokens:68` quarta via de truncamento. Docstring `:1-7` admite consolidação mas `nightwatch/context_budget.py` continua como shim.
- Fonte de contexto: `provider_registry.CANONICAL_CONTEXT=32768:40` (fonte declarada) vs `query_server_context_size:60` (HTTP `/slots` vivo) vs `llm_llama_cpp._context_window:136` vs `llm.n_ctx:768` vs `ContextSnapshot.tokens_budget` — 5 leituras de `n_ctx` sem hierarquia única em runtime.

## 5. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/router.py`

Exports: triggers `_DOCTOR:28,_NIXOS:43,_BOOKS:58,_RAG:66`, regexes `_RAG_EXT:77,_READ_VERB:81,_READ_PATH:82,_READ_QUESTION:83`, `_is_pure_read:84`, `_extract_read_path:100`, `Route:109`, `get_fast_paths:123 (+_audio:130,_voice:134,_math:144,_screenshot:193,_sys:204)`, `_match_any:234`, `route_request:241`, `handle_fastpath:320`, `handle_doctor:327`, `handle_nixos:334` (via `MCPClient:341`), `handle_rag:379` (via `HybridSearch:381`), `handle_read:395` (via `devtools.read_file:401`), `handle_agent:416`, `_extract_nix_term:452`, `_strip_stopwords:476`. Depende de `core/rules.FastPaths/DEFAULT_RULES`.

Callers reais: `cli/main.py:624`, `providers/telegram.py:542`, `core/voice.py:828`, `core/benchmark.py:62`, `core/regression.py:56` + testes `test_router.py:3,120,130`, `test_rules.py:4,131,268`, `test_read_route.py:17`, `test_model_routing.py:416`. `agent.py` **não** chama `route_request` (cascata paralela).

Duplica:
- Roteamento duplo: `route_request` (doctor/nixos/books/rag/read/agent) vs `provider_registry.route:197/route_for_persona:246` (tier/kind/context) vs `agent.detect_profile:36/_registry_tier_profile:87` vs `tool_surface.classify_task/surface_for` (`core/tool_surface.py:53,79`). Quatro classificadores por keyword sem dono único.
- `handle_doctor:327` vs `core/doctor.run_doctor:328/doctor_report:343` vs `health_monitor.BackendHealthMonitor:45` (ver #8). `handle_rag:379` vs `devtools.semantic_search:698` (ver #5).

## 6. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/persona.py`

Exports: `PersonaPolicy:18`, `Persona:31 (+to_dict:44)`, `BUILTIN_PERSONAS` (incl. `uncensored`), `_EXEC_TOOLS:475`, `_WRITE_TOOLS:476`, `CAPABILITY_TOOLS:481` (read/write/shell/git/test/nix_*/rag_search/memory/vault/web_search/read_url/vision/workitem), `filter_tools:503`, `PersonaRegistry:528 (+__init__:531,_load_from_dir:543,get:569,list_all:573,list_by_tag:577,select_for_task:581,save_registry:609,summary:622)`.

Callers reais: `mcp_server.py:603` (`PersonaRegistry()` p/ `jarvis_persona`), `persona_executor.py:30`, `agent.py:1106,1119`, `cli/dev.py:1440,1451,1824 (_filter_tools),2333,2344,2688,2705`, `cli/main.py:1524`, `control_plane/integration.py:312?` (via platform_bridge:56), `self_test.py:602`, testes `test_persona.py:8,190,201,208,219,265`, `test_jarvis_assistant.py:8`.

Duplica:
- Filtro triplo: `filter_tools:503` (capability+policy) vs `tool_surface.surface_for` (`core/tool_surface.py:79`, attractor-drop) vs `agent.py` filtragem inline + `cli/dev.py:1824`. `CAPABILITY_TOOLS:481` mapeia nomes `jarvis_*` que **não existem** em `DEV_TOOLS` (ex. `jarvis_nix_eval,nix_eval,remember,recall,rag_search`) — matriz dessincronizada dos schemas reais (`JARVIS_TOOLS` vs `DEV_TOOLS` vs `to_function_tools`).

## 7. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/persona_executor.py`

Exports: `ExecutionResult:34`, `PersonaExecutor:46 (+__init__:55,_get_harness:61,execute_with_persona:84,execute_pipeline:253,summary:282)`. Importa `PersonaRegistry:30`, lazy `config.get_config+paths.set_project_root:64-72`, `nightwatch.harness.Harness/HarnessConfig:77-83`, `nightwatch.task_queue.Task/TaskStatus` (dentro `:84+`).

Callers reais: **só** `cli/main.py:1547,1549,1558` (`PersonaExecutor(...).execute_with_persona`). Zero callers em `agent/mcp_server/router/webui/telegram/voice`. Auto-referência `:253,269`. Sem teste dedicado (só `test_persona.py` cobre registry, não executor).

Duplica: **terceiro executor** — `PersonaExecutor.execute_with_persona:84/execute_pipeline:253` vs `Agent.run` (`core/agent.py:1057`) vs `Harness.run` (`nightwatch/harness.py:1687`). Docstring `:9` diz `NO DEPENDENCY ON orchestrator.py` mas `_get_harness:61` reacopla ao `Harness` + `Task Queue`; `ToolExecutor` citado `:9` não é importado/usado.

## 8. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/memory.py`

Exports: `KIND_*:lesson/fact/decision/preference/error (32-38)`, `_ALL_KINDS`, `MemoryEvent:43 (+payload:54)`, `_stable_id:67`, `EpisodicMemory:78 (+__init__:81,collection:89,ensure:92,is_available:95,remember:100,remember_lesson:122,forget_task:172,remember_fact:197,recall:202,lessons:268,recent:316,count:337,clear:343)`. Usa `LLMClient:28`, `QdrantStore:29`, `rag.sparse_terms/sparse_vector:108,224`, `vector_store.stable_id:74`.

Callers reais: `mcp_server.py:855,871,890` (remember/recall/lessons), `vault.py:30` (vault lê memories), `cli/main.py:441,457,466,685`, `cli/dev.py:154,527,1235,1245,1319,2607`, `webui/api.py:705,732` (recall/remember HTTP), `providers/telegram.py:583`, `nightwatch/memory_bridge.py:186,250`, `benchmarks/kb_regression.py:44,88,112`, `heal.py:177`, testes `test_memory.py:7,184,206`, `test_fuzz_mutation.py:498-767`.

Duplica:
- `remember/recall` expostos em **4 superfícies** com nomes distintos: `EpisodicMemory` ⇄ `mcp.call_tool(jarvis_remember/jarvis_recall/jarvis_lessons)` ⇄ `webui/api.memory_recall:703/memory_remember:730` ⇄ `cli/main.py:441+` ⇄ `telegram.py:583`. Mesma coleção `memories`, sem validação única.
- `_stable_id:67` vs `vector_store.stable_id:61` (importado `:74` mas ambos existem; `memory` tem o seu + importa o outro). `ensure:92` vs `rag.ensure_collection:484` vs `knowledge_schema.ensure_collection:93` vs `QdrantStore.ensure_collection:114` (ver #6).

## 9. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/rag.py`

Exports: `_load_ragignore:37`, `_ragignore_rejects:56`, `_SimpleIgnoreMatcher:72 (+__init__:79,match_file:135)`, `extract_facts:245`, `get_symbol_block:266`, `build_rich_content:291`, `sparse_terms:319`, `sparse_vector:332`, `HybridHit:358`, `_target_extension:366`, `apply_legacy_boosts:371`, `_is_allowed:417`, `iter_indexable_files:428`, `HybridIndexer:475 (+__init__:478,ensure_collection:484,index_file:487,_mark_indexed:607,index_directory:620)`, `diversify_by_source:633`, `HybridSearch:668 (+__init__:671,search:676,_rerank_candidates:730)`. Usa `LLMClient:26`, `QdrantStore+dense_key+stable_id:27`, `Reranker:738` lazy.

Callers reais: `mcp_server.py:944,987`, `router.py:381`, `cli/main.py:154,171`, `cli/dev.py:512,1283,1300`, `memory.py:108,224` (sparse), `legacy_index.py:31,301`, `audiobook.py:940`, `control_plane/integration.py:288`, `eval_rag.py:196`, `regression.py:104`, `devtools.semantic_search:698` (concorrente, não caller), testes `test_rag.py:7`, `test_reranker.py:74,102`, `test_rag_manifest.py:20`, `test_rag_diversify.py:12`.

Duplica:
- Busca em 4 lugares: `HybridSearch.search:676` ⇄ `devtools.semantic_search:698` ⇄ `router.handle_rag:379` ⇄ `mcp._handle_rag_search:936`. Indexação em 3: `HybridIndexer.index_file:487/index_directory:620` ⇄ `mcp._handle_rag_index:983` ⇄ `cli/dev.py:512,1300`.
- `sparse_terms:319/sparse_vector:332` importados por `memory.py:108,224` + `legacy_index.py:31` + `audiobook.py:940` — util compartilhado sem dono (também `vector_store.dense_key:46` espelha lógica).
- `.ragignore` engine própria (`_SimpleIgnoreMatcher:72` + pathspec fallback) sem equivalente em `memory/vault` (inconsistência de filtragem).

## 10. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/vault.py`

Exports: só `MemoryVault:52 (+__init__:55,vault_dir:68,_ensure_vault:71,_git:77,_month_file:88,list_notes:96,read_note:113,_collect_events:129,_format_events:135,summarize:149)`. Usa `EpisodicMemory+KIND_FACT:30`, `LLMClient:31`. Prompt `_SUMMARY_PROMPT:33`.

Callers reais: `mcp_server.py:901,919` (list/write), `cli/main.py:475,486`, `cli/dev.py:1260,1271,2617`, `webui/api.py:763,782` (list/summarize HTTP), `providers/telegram.py:589`, teste `test_vault.py:11`. `summarize:149` chamado só via CLI/WebUI, **não** via MCP (`_handle_vault_write:911` escreve direto, sem condensação LLM).

Duplica:
- 3 camadas de “memória” sem fronteira executada: `rag` (conhecimento) vs `memory.EpisodicMemory` (experiência) vs `vault.MemoryVault` (síntese) — distinção só em docstrings (`memory.py:1-18`, `vault.py:1-22`, `rag.py:1-14`); em runtime `vault.summarize:149` regrava `kind=fact` no `memories` (loop memória→vault→memória).
- Git próprio `_git:77` vs `devtools.execute_shell(git…)` vs `spaces` dirs; path `vault_dir:68` vs `mcp_server:436,467,531-532` hardcodes `~/vaults/projects…` vs `spaces.Space.vault_dir:65` vs `vault_cipher.note_path:57`.
- Criptografia irmã: `vault_cipher._fernet:34/encrypt_text:118/decrypt_text:123/write_text:76/read_text:105` vs `rag_crypto._fernet:28/encrypt_payload:56/decrypt_payload:64` — dois Fernets, nenhum usado por `vault.py` (vault grava plaintext + git).

## 11. `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/providers/` (14 arqs, 2691 linhas)

Exports-chave:
- `interfaces.py:14,22,30` (`STT/TTS/WakewordProvider` ABCs — sem caller produtivo encontrado, só contrato).
- `llm_backend.py:21,29,43,58,66,76` (`ChatMessage:21,ChatResponse:43,EmbeddingResponse:58,BackendInfo:66,LLMBackend:76` com `chat:85,embed:113,health:126,info:138,supports_*:146-160`).
- `llm.py:43-66` erros (`LLMError,Connection,Timeout,Server,ContextOverflow,Stream,CircuitOpen`), `_:78,_CircuitState,Config:84,Breaker:89 (+before_call:110,record_*:123-131,release:146,state:158)`, `_classify_error_response:164`, `_review_prompt:174`, `LLMClient:202 (+__init__:216,is_available:295,get_slots_status:314,is_busy:320,get_backend_info:330,_resolve_model_id:340,_record_telemetry:357,session_telemetry:390,last_ttft:395,_served_model_id:408,_resolve_temperature:442,chat_full:471,chat:503,chat_with_tools:508,_chat_once:628,chat_stream:665,achat_stream:707,embed:741,base_url:761,n_ctx:768)`.
- `llm_llama_cpp.py:63 LlamaCppBackend` (`_build_session:38,_stable_model_name:105,_context_window:136,chat:154,_thinking_kwarg:256,_stream_payload:266,_extract_delta:292,chat_stream:309,achat_stream:339,embed:369,health:386,info:397,get_slots_status:428,is_busy:455,close:466`) — usa `embedding.embed_long:33`.
- `llm_prismml.py:60 PrismMLBackend` (`_build_session:35,chat:101,embed:161,health:178,info:189,get_slots_status:220,is_busy:247,close:258,find_prism_binary:263`) — usa `embedding.embed_long:30`, sem `chat_stream/thinking/slots-ctx`.
- `llm_factory.py:create_backend:23,list_backends:99`; `llm_remote.py:16 RemoteBackend(chat:45,embed:94,health:97,info:105)`; `mcp.py:31 MCPClient(start:57,close:82,list_tools:103,call_tool:108,_request:119,_notify:145,_read_loop:152)+_content_text:171,parse_command:183,to_function_tools:196,from_function_call:212`; `embedding.py:split_for_embedding:28,mean_pool:59,embed_long:74`; `vector_store.py:_embed_dim:27,dense_key:46,stable_id:61,QdrantStore:74 (+is_available:96,_request:99,ensure_collection:114,delete:127,info:130,_normalize_vector:136,upsert:142,_decrypt_results:162,get_points:173,delete_points:196,search:203,search_hybrid:224,count:267)`; `reranker.py:Reranker:29 (+is_available:36,rerank:39)`; `telegram.py:TelegramBot:38+TelegramChannel:96 (+handle_message:190,_handle_*:227-376,run:411)`; `http_service.py:http_health_check:20`.

Callers reais: `LLMClient` ← `agent.py:933,2485,2606`, `rag.py:26`, `memory.py:28`, `vault.py:31`, `devtools.py:705`, `cli/main.py:44,109`, `cli/dev.py:1019`, `webui/api.py:449`, `nightwatch/harness.py:198,665`; `QdrantStore` ← `rag.py:27`, `memory.py:29`, `devtools.py:706`, `mcp_server.py:946`, `cli/main.py:45`, `cli/dev.py:497`; `create_backend` ← `test_llm_backend.py:16` + `llm_factory.py:4` (auto-ref); `MCPClient` ← `router.py:341`, `agent.py:346`; `Reranker` ← `rag.py:738` lazy + `test_reranker.py:8`; `TelegramChannel` ← standalone `run:411`.

Duplica: ver ranking #3 (Llama vs Prism), #4 (CircuitBreaker), #7 (embed ×4), #8 (health), #6 (ensure/ зачем `_embed_dim`).

---

# 10 duplicações mais graves (ranqueadas, com evidência dos dois lados)

1. **Schema de tools em 4 dialetos** — `mcp_server.JARVIS_TOOLS:54` (`jarvis_read_file:path/offset/limit`, `jarvis_str_replace:old_string/new_string`) × `devtools.DEV_TOOLS:1348` (`read_file:path/offset/limit`, `str_replace:old/new/allow_multiple`) × `persona.CAPABILITY_TOOLS:481` (lista `remember/recall/nix_eval/read_chatgpt` que não existem em nenhum schema) × `mcp.to_function_tools:196` (`providers/mcp.py`, conversor MCP→OpenAI usado por `agent.py:346`). Risco: LLM vê nomes incompatíveis; `mcp_server.py:625-631` traduz manualmente, `filter_tools:503` filtra por nomes fantasmas.
2. **Orçamento de contexto / contagem de tokens em 4 vias** — `context_budget.ContextBudget.estimate_tokens:342 + _calibration_ratio:352` × `tokens.estimate:49/estimate_messages:63 + calibration_ratio:34` (delegação parcial `:359`) × `cli/dev._estimate_tokens:373` (usado em 7 pontos `:460,663,2025,2380,2419`) × `agent._truncate_history_for_send:208 + _ctx_derived_max_tokens:68`. Risco: thresholds divergem; compactação dispara em um contador e não no outro.
3. **Backend LLM clonado** — `llm_llama_cpp.LlamaCppBackend:63` (`chat:154,embed:369,health:386,info:397,get_slots_status:428,is_busy:455`) × `llm_prismml.PrismMLBackend:60` (`chat:101,embed:161,health:178,info:189,get_slots_status:220,is_busy:247`); `diff` = 364 linhas, mesma `LLMBackend` (`llm_backend.py:76`), ambos chamam `embedding.embed_long` (`llm_llama_cpp.py:33`, `llm_prismml.py:30`). Prism sem `chat_stream:_thinking_kwarg:256/chat_stream:309`. Risco: fix em slots/busy precisa de 2 patches.
4. **CircuitBreaker duplo** — `core/circuit_breaker.CircuitBreaker:165` (+`CircuitState:34,DataClass:40,ContentSafetyFilter:102`) × `providers/llm.CircuitBreaker:89` (+`_CircuitState:78,Config:84`). Nenhum importa o outro (`rg` sem cross-import). Risco: política de fallback local/remoto e segurança de conteúdo avaliadas por dois autômatos distintos.
5. **RAG search/index em 4 fachadas** — `rag.HybridSearch.search:676/HybridIndexer.index_file:487` × `devtools.semantic_search:698` (próprio `LLMClient+QdrantStore:705-706`) × `router.handle_rag:379` × `mcp_server._handle_rag_search:936/_handle_rag_index:983`. Risco: boosts RRF (`apply_legacy_boosts:371`), `diversify_by_source:633` e rerank (`_rerank_candidates:730`) só no caminho `rag.py`; demais atalhos entregam ranking inferior.
6. **Ensure de coleção ×4 + `_embed_dim` ×2** — `vector_store.QdrantStore.ensure_collection:114` × `rag.HybridIndexer.ensure_collection:484` × `memory.EpisodicMemory.ensure:92` × `knowledge_schema.ensure_collection:93` (+`vector_config:75`); `vector_store._embed_dim:27` × `knowledge_schema._embed_dim:40`. Risco: drift de dimensão/nome de coleção (`memories` vs `code_index/books`) quebra `test_context_drift`.
7. **Embed em 5 implementações** — `providers/embedding.embed_long:74/split_for_embedding:28/mean_pool:59` × `llm.LLMClient.embed:741` × `llm_llama_cpp.embed:369` × `llm_prismml.embed:161` × `llm_remote.embed:94` (+`vector_store.dense_key:46/stable_id:61` para sparse). Risco: chunking inconsistente (long-text só via `embed_long` nos backends llama/prism, não no `LLMClient` nem `Remote`).
8. **Saúde/doctor em 5 níveis** — `router.handle_doctor:327` × `doctor.run_doctor:328/doctor_report:343/check_llm:43/check_embeddings:61/check_qdrant:71` × `health_monitor.BackendHealthMonitor:45` × `llm.is_available:295/health:386,178` + `http_service.http_health_check:20` + `llm.get_slots_status:314/is_busy:320` vs `llama.get_slots_status:428/is_busy:455`. Risco: “sistema ok” varia por entrypoint (router vs doctor vs slots).
9. **Filtro de tools por persona ×2 + matriz fantasma** — `persona.filter_tools:503` (capability+`_EXEC_TOOLS:475/_WRITE_TOOLS:476`) × `tool_surface.surface_for:79/classify_task:53` (attractor-drop `read_file`) × filtragem inline `agent.py:1106+cli/dev.py:1824`. `CAPABILITY_TOOLS:481` cita `nix_eval,remember,rag_search` inexistentes como tools. Risco: persona `can_write=False` bloqueada num caminho e liberada no outro.
10. **Executores de tarefa ×3 + cripto ×2 (empate técnico, mesma severidade)** — `persona_executor.PersonaExecutor.execute_with_persona:84/execute_pipeline:253` × `agent.Agent.run:1057` × `harness.Harness.run:1687` (só `cli/main.py:1547` chama o primeiro — executor órfão que reacopla `Harness:61-83` após declarar independência); `vault_cipher._fernet:34/encrypt_text:118` × `rag_crypto._fernet:28/encrypt_payload:56` (nenhum usado por `vault.py:52-204`, que persiste plaintext+git via `_git:77`). Risco: caminho de execução/segredo depende de qual `main/CLI` o operador invoca.

*Método: só `rg`/`sed`/`wc`, nenhum arquivo editado. Caminhos absolutos acima; linhas são `rg -n` exatas no snapshot atual.*

---

