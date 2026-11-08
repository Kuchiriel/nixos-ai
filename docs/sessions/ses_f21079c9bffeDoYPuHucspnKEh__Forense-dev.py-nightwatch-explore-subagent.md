# Forense dev.py + nightwatch (@explore subagent)

- **sessão:** `ses_f21079c9bffeDoYPuHucspnKEh`
- **quando:** 2026-09-26 18:26 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 7)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No repo /home/nixos/projects/nixos-ai, faça análise forense de DOIS arquivos (NÃO edite, só reporte): (1) modules/ai/jarvis/src/jarvis/cli/dev.py (~3078 linhas): loop principal do agente, _call_llm, _detect_profile, catálogo de tools, parser de tool calls, persona/mode handling, sessão, auto-commit, output validation — nomes + linhas. (2) modules/ai/jarvis/src/nightwatch/harness.py (~1908 linhas): ciclo autônomo, retry, checkpoint, patch, validation, review, branch isolation, task state — nomes + linhas. Depois compare: o que existe nos 3 loops (agent.py loop vs dev.py loop vs nightwatch loop) que é SEMANTICAMENTE DIFERENTE (não só nome diferente). Retorne tabela concisa.

---

## · ?

Análise forense dos 3 loops em curso — mapeando dev.py e harness para a tabela comparativa.

---

## · ?

Arquivos localizados — agora extraindo inventário de funções e linhas.

---

## · ?

Inventário completo — agora lendo os trechos-chave de cada loop.

---

## · ?

Quase completo — buscando detalhes finais de modos, checkpoints e isolamento.

---

## · ?

Dados principais reunidos — só confirmando as linhas dos parsers regex antes do relatório final.

---

## · ?

Forense read-only (nada editado) em `/home/nixos/projects/nixos-ai`:

# (1) `modules/ai/jarvis/src/jarvis/cli/dev.py` — 3078 linhas

**Loop principal:**
| Nome | Linhas |
|---|---|
| `_run_agent_loop(messages,tools,profile,approve,debug,max_turns=30,reasoning_level)` | 1997-2247 (`for turn in range(max_turns)` L2024) |
| `dev_repl(...)` — REPL externo `while True` + dispatch `/cmd` | 2295-~2805 (`while True` L2388) |
| `dev_once(...)` — one-shot não-interativo | 2946-3078 |
| `_run_autopilot(...)` | 2856-2916 |
| `_architect_plan(...)` | 2807-2855 |
| `_find_project_root()` | 2254-2294 |

**`_call_llm`:**
| Nome | Linhas |
|---|---|
| `_call_llm(messages,tools,profile,debug)` — delega a `LLMClient.chat_with_tools()`, readapta p/ shape cru `choices[0].message` | 1002-1079 |
| `_record_llm_telemetry()` / `_session_telemetry()` / `_print_stats()` | 399-456 |
| `_estimate_tokens()` (via `tokens.py`, nunca heurística inline) | 373-387 |

**`_detect_profile`:**
| Nome | Linhas |
|---|---|
| `_detect_profile()` — `GET /models` + `ModelRegistry`/`_registry_tier_profile` vence param-count; fallback regex `(\d+\.?\d?)b` p/ large/small/tiny/default; `native_tools=False` se tiny; `context_size` via `_query_server_context_size()` (`/props`) | 266-345 |
| `_query_server_context_size()` | 246-265 |
| `_maybe_disable_thinking()` (`/no_think`) | 348-353 |
| `MIN_PROFILE_CONTEXT` (import `provider_registry`) | L37,310,338,2012 |

**Catálogo de tools:**
| Nome | Linhas |
|---|---|
| `_get_tools(persona)` — ~21 dicts `type:function` (`read_file,str_replace,execute_shell,semantic_search,...,nix_*,browser,capture_screen,remember/recall/lessons,vault_*,rag_*,web_search,read_chatgpt`) + filtro `filter_tools(names,persona)` | 1496-~1833 (filtro L1822-1826) |
| `_tools_catalog(tools)` — deriva prosa do schema ativo por grupo (shell/arquivos/memoria/busca/nix/web/visao/outras) | 1462-1493 |

**Parser de tool calls:**
| Nome | Linhas |
|---|---|
| Regexes: `_SEARCH_REPLACE_RE` L1835, `_SHELL_BLOCK_RE` L1845, `_READ_MARKER_RE` L1847, `_JSON_TAG_RE`(=TOOL_CALL_TAG_RE)+`_JSON_CODEBLOCK_RE` L1851, `_FUNCTION_TAG_RE` L1861, `_PARAMETER_TAG_RE` L1864 | 1835-1868 |
| `_parse_text_actions(content)` — prioridade: `<function=>` Hermes/Llama-3 SÓ, senão SEARCH/REPLACE+`>>> READ`+shell-block, senão JSON solto | 1883-1948 |
| `_dedupe_actions()` | 1869-1880 |
| `_to_tool_calls(actions)` — `uuid` único (`call_<hex8>`, fix colisão `call_fallback_{i}`) | 1951-1969 |
| `_looks_like_promise()` (F1 abismo, PT-BR+EN, teto 2 nudges) | 1972-1984 |

**Persona/mode handling:**
| Nome | Linhas |
|---|---|
| `SYSTEM_PROMPT_TEMPLATE` (`{repo_map,memory_context,agent_context,persona_block,tool_discipline,tools_catalog}`) | 953-~1000 |
| `_select_persona(hint)` / `_persona_block(persona)` (default `jarvis` MCU) | 1437-1458 |
| `dev_repl`: `mode="native" if native_tools else "text"` L2318; `WorkspaceDiscovery→select_for_task` L2320-2337; `JARVIS_PERSONA` env L2341-2351; fallback `_select_persona("")` L2353; `tools=_get_tools(persona)` só se native L2354-2355 | 2316-2370 |
| Runtime: `/persona` L2686, `/persona <desc>` L2702-2713; `/tools[+nome/-nome/all]` L2539-2590; `/model[ id]` L2446-2485; `/reasoning low/medium/high` L2591-2598; `reasoning_level` no loop L2004,2060,2067; `/jarvismodes` via `_load_jarvismodes` L759 + `_parse_jarvismodes_simple` L791 | — |
| `approve/yolo`: `yolo→approve=True` L2307; `_approve_all_active()` (env `JARVIS_APPROVE_ALL` ou `~/.local/state/jarvis/approve-all`) L356-370; gate `execute_shell`+`browser click/fill/press` via `Confirm.ask` em `_execute_tool_call` | 1191,1336-1375 |

**Sessão:**
| Nome | Linhas |
|---|---|
| `_session_state_path()` (`~/.local/state/jarvis/dev-session-<proj>.json`) | 544-550 |
| `_persist_session()` (msgs+`token_estimate`+`git`+`session_id`+`tool_calls`; `.enc` se `vault_cipher`) | 652-684 |
| `_resume_session()` / `_get_session_info()` / `_wants_continue()` (fala curta "continue") | 710-732 / 734-758 / 687-707 |
| `_compact_session(max_tokens=6000)` / `_trim_messages(max=20, fronteira `user`) / auto-compact 70%→50% de `context_size` no loop L2025-2030 | 457-489 / 1087-1106 |
| `_get_git_state()` / `_snapshot_file()` L172 / `_restore_edit()` L194 / `EDIT_HISTORY` (cap 20) L168,1403-1405,2493-2496; `_discover_agent_files` L553 / `_load_agent_context` L593 / `_pinned_section` L185 / `_build_repo_map` L858 / `_build_memory_context` L524 / `_auto_index_rag` L490 | — |

**Auto-commit:**
| Nome | Linhas |
|---|---|
| `_auto_commit(tool,args,success)` — só `str_replace/write_file`, só arquivo editado (`git add -- <path>`, nunca `-A`; ignora `/tmp/` e `JARVIS_NO_AUTO_COMMIT=1`), `git commit --no-verify -- <path>`; chamado no loop L2228-2229 `if not is_error and diff` | 1114-1169 |

**Output validation:**
| Nome | Linhas |
|---|---|
| `_validated_output(name,args,output)` — `ToolValidator().validate()` anexa `[validation: warnings[:6]]`, best-effort; chamado L2208 | 1175-1188 |
| `_execute_tool_call(name,args,approve)` — vision/nix/memory/vault/rag/web/lessons/chatgpt/browser inline + resto via `handle_dev_tool(devtools.py)`; normaliza `content/output/results/entries/path`→str + `diff`; erro real sem `error` usa `output[:800]` (elo H2) | 1191-1434 |
| Vereditos no loop (não só validar string): `LoopDetector.check` L2043; promise-nudge (eco da tool anunciada) L2091-2123; claim-checker (regex `\.(txt\|md\|py\|...)` vs `_writes_ok`) L2128-2151; `completion.check_completion(messages)` 1x bounded, só reabre p/ artefato (`instrucao lida/nao existe/nao compila`), trailing-error ignorado L2152-2188; `max_turns` honesto: `stuck` (0 sucessos) vs turnos esgotados L2239-2247 | 1997-2247 |

# (2) `modules/ai/jarvis/src/nightwatch/harness.py` — 1908 linhas

**Ciclo autônomo:**
| Nome | Linhas |
|---|---|
| `Harness.__init__` — `TaskQueue+SafeEditor+Checkpoint.load+Mission+ProjectRegistry+LoopDetector+eventbus`, `ContextBudget` (auto `/props`), `prune_completed(20)/prune_stale(3600s)/recover_stuck/prune_orphan_branches/sync_to_episodic` | 1022-1088 |
| `Harness.run()` — `fcntl RUNNING.lock` (1 loop), pause-gate, `get_recovery_context`, `discover_tasks()` multi-projeto, `while executed<max_tasks` + `max_minutes`, `get_next_task→execute_task`, `project_switch_interval`, agregação `HarnessResult` + sumário Telegram | 1687-1863 |
| `Harness.execute_task(task)` — pipeline: stale-check→pause→checkpoint→protected→IN_PROGRESS→branch→budget→`retry{patch→apply→validate→review}`→commit-na-branch→merge→evidence→complete | 1327-1683 |
| `discover_tasks(project?)` / `_discover_scripted_tasks()` / `_discover_llm_tasks(call_llm)` / `_extract_json_array` | 1206-1326 / 265-292 / 339-469 / 293-338 |
| `run_nightwatch(max_tasks,max_minutes,...,strict_projects)` | 1870-1908 |
| `HarnessConfig` L119-154 / `HarnessResult.total/success_rate` L155-177 / `_default_call_llm(prompt,max_tokens)` L179-242 (via `LLMClient`) / `_default_send_telegram` L243-264 | — |

**Retry:**
| Nome | Linhas |
|---|---|
| `for attempt in range(max(max_retries,1))` intra-task: `abort+recreate branch`, `IN_PROGRESS`, `notify Retry`, `previous_errors: list[str]` realimentado no prompt (`DO NOT REPEAT`, últimas 3, `[:300]`) | 1419-1434,762-767 |
| Exceção outer: `classify_failure→FailureType` (L54-118) + `LoopDetector.record_attempt`→`block` + só `TRANSIENT/TOOL_FAILURE` com backoff `min(2^r*5,60)s` e recursão `execute_task` | 1641-1682 |

**Checkpoint:**
| Nome | Linhas |
|---|---|
| `create_checkpoint_for_task(task.id,desc,project)` L1363; `cp.record_operation("patch|write:*|validate|commit|error|compaction",...)` L1444,1482,1492,1495,1518,1594,1642,1410; `Checkpoint.load` L1033; `get_recovery_context` L1737; `generate_recovery_summary` injetado no patch-prompt L741 | — |

**Patch:**
| Nome | Linhas |
|---|---|
| `_request_json_patch(task,file_contents)` — Caminho 1 determinístico: grammar `json_schema{patches[{path,old_text,new_text}]}` via `LLMClient.chat_with_tools(extra=schema)` | 617-694 |
| `_request_structured_patch(task,target_files,call_llm,previous_errors)` — lê alvos (`_read_file_for_llm` L470 + `_extract_relevant_section` L508 + `_resolve_file_path` L573), injeta `recovery_ctx`+`LESSONS FROM PAST FAILURES (recall top_k=3)`+`error_section`, escolhe `WHOLE` (<6000 chars, ≤3 files) vs hunks `≤15 linhas`, tenta JSON-grammar primeiro, fallback `call_llm(prompt,4096)` + `parse_llm_patch` + dump `last_patch_failure.txt` | 697-861 |
| `_request_file_creation(...)` (NO_CHANGES+missing→CREATE dedicado) L862-913; apply: `patcher.apply_patch` L1478 + `editor.apply_edit(resolved,validate=True)→EditResult` L1487-1495 | — |

**Validation / Review:**
| Nome | Linhas |
|---|---|
| `validate_change(applied_files,run_tests,run_imports)→ValidationReport` (sintaxe+imports+testes) | 1511-1532 (import L97) |
| `review_change(task,acceptance_criteria,test_output,call_llm)→ReviewResult`; `skip_review = auto_review and risk==low and passed and sem output de tests` (economiza 1 LLM call) | 1534-1570 (import L98) |

**Branch isolation:**
| Nome | Linhas |
|---|---|
| `safety.create_task_branch(task.id,project)` L1400 (falha→`_fail_task`+return); `safety.merge_task_branch(branch)→commit_sha` L1593; `safety.abort_task_branch(branch)` em TODA falha (patch/write/validate/review/exhaust/commit/evidence/exception) L1427,1451,1463,1502,1525,1561,1576,1588,1600,1656 | — |
| `project_isolation.use_project_root(resolve_project_root(task.project))` L1394; `safety.is_path_protected` L1371 / `is_project_protected` L1378 (+discovery filter L1196,1224); `_git_commit(msg)` L927 / `_git_diff_stat` L914 / `_git_revert` L967 / `_verify_completion_evidence(commit_sha,files)` L952,1597-1607; `prune_orphan_branches` L1078 | — |

**Task state:**
| Nome | Linhas |
|---|---|
| `Task/TaskStatus/TaskQueue/LoopDetector/MissionState` (import L50); estados: `READY` (L286,447,458), `IN_PROGRESS` L1384,1433, `VALIDATING` L1469, `REVIEW` L1545, `BLOCKED` (protected/loop, L1372,1379,1663,1790), `ABANDONED`/skip (stale/pause/dry/no-changes, L1347,1357,1389,1464,1792) | — |
| `_fail_task(task,error)` (`task.fail`+`queue.update_task`+`_record_failure_rule`) L1092-1109; `_record_failure_rule` (ratchet p/ `AGENTS.md`) L1111-~1170; `classify_failure` L64-118; `queue.prune_completed/prune_stale/recover_stuck_tasks` L1066-1074,1719; `loop_detector.reset(task.id)` no sucesso L1609; `_log_progress` L1004; `notify/_emit/_handle_bus_*` L1170-1190 | — |

Referência 3º loop: `modules/ai/jarvis/src/jarvis/core/agent.py` — 3173 linhas, `Agent.run(prompt)→AgentResult` L1057, `for turn in range(max_turns)` L1285, `_get_llm_response` L2889, `_finalize` L973, `_stuck_or_cascade` L2556, `_try_api_cascade` L2509.

# Comparação — o que é SEMANTICAMENTE DIFERENTE (não alias)

| Dimensão | `agent.py:Agent.run` | `dev.py:_run_agent_loop+dev_repl` | `nightwatch:Harness.execute_task+run` |
|---|---|---|---|
| Unidade de loop | 1 `prompt` → N turnos tool; `MAX_TURNS=8` env, `MAX_TIME_S=600` + `ContextBudget` overflow-stop | 1 sessão REPL → N tasks; inner `max_turns=30`, auto-compact 70%→50% `context_size`, outer `while True` interativo | N tasks→1 patch-tentativa cada; inner `max_retries` (patch→apply→validate→review), outer `while executed<max_tasks` + `max_minutes` + `project_switch_interval` + `RUNNING.lock` |
| Chamada LLM | `_get_llm_response`: router+`reasoning_effort/review_focus`, `_repair_malformed_tool_args`, `finish_reason==length` streak→plano em prosa | `_call_llm`: `LLMClient.chat_with_tools` direto, sem repair/steer; thinking `<thinking>` só display | Duas vias: `_request_json_patch` grammar `json_schema` determinística PRIMEIRO, fallback texto `call_llm(prompt,4096)` + `parse_llm_patch`; prompt inclui `recovery_ctx+lessons+previous_errors` |
| Parser tool-call | `extract_fallback_tool_calls` (plural, xLAM arrays) + `STATE(no_tool_call,verify=n/2)` nudge tipado 1 ação/0 prosa, `verify_turns≤2` | `_parse_text_actions` multi-ação (Hermes `<function>` vence tudo, senão SEARCH/REPLACE+`>>>READ`+shell+JSON) + promise-nudge ecoando tool anunciada + claim-checker vs `_writes_ok` | Não há parser genérico: `parse_llm_patch` só entende `=== FILE/CREATE/WHOLE` ou JSON `{patches}`; sem fallback shell arbitrário |
| Execução tools | Serial+batch paralelo só `read_file` puro; `execute_shell` com `command_allowed`, audit `_log_audit`, `obs_cache` dedup, `json_echo_ban`, `steer/stop` mid-run | Serial; `execute_shell/browser-mutante` com `Confirm.ask` (ou `approve/yolo/approve-all`); `EDIT_HISTORY`+`/undo`; sem audit log, sem obs_cache, sem steer | Sem tools genéricas: só `SafeEditor.apply_edit(validate=True)` atômico; shell/testes só dentro de `validate_change`, nunca livre |
| Validação fim | `completion.check_completion` → `VERIFIED/UNVERIFIED` + `verify_turns` + `_finalize(verdict)`; `STUCK/STOPPED` honestos | `check_completion` 1x bounded só p/ artefato (arquivo existe/compila/instrução executada); trailing-error ignorado; retorno bool + `stuck` vs `max_turns` | `validate_change` (sintaxe/imports/testes) + `review_change` independente (skip se low-risk) + `_verify_completion_evidence(commit)` — tudo bloqueante p/ commit |
| Commit | Não commita | `_auto_commit` por-arquivo pós-`diff` (`str_replace/write_file`), conveniência, sem merge | ` _git_commit` na task-branch + `merge_task_branch` p/ main; sem merge = falha; `evidence` pós-merge pode abortar |
| Isolamento | Jail via `command_allowed`+`ToolValidator.secret_task`; escreve direto na worktree | `write-jail+protected-files` mas escreve direto na worktree/branch atual | `create/abort/merge_task_branch` por task + `use_project_root` + `is_path/project_protected` + `abort` em todo erro — main intocada até merge |
| Estado/checkpoint | Efêmero: `turn_budget`, `_obs_cache`, `_bar_repeat` por run; sem persistência | `dev-session-<proj>.json` (+`.enc`) com msgs+git+tokens; `resume/continue_session`, `/clear/compact/map` manuais | `Checkpoint{record_operation}` por task + `TaskQueue` persistida (attempts/status/last_error) + `get_recovery_context` + `prune/recover_stuck` + `Mission` + `platform_bridge.log_task_execution` |
| Anti-loop/retry | `LoopDetector` + `_loop_warnings≥2`→`_stuck_or_cascade→_try_api_cascade` (1x, só no teto) + `_mal_streak≥3` STUCK + `trunc_streak` | `LoopDetector` (aborta honesto) + nudges limitados (promise 2x, claim 1x, verdict 1x); retry = continuar turno com `system` nudge | `previous_errors` no prompt (aprende, não só avisa) + recria branch por attempt + `LoopDetector(task.id)` cross-run→`BLOCKED` + `rules ratchet` (`AGENTS.md`) + backoff exponencial só `TRANSIENT/TOOL_FAILURE` |
| Persona/modo | Gate: explícita sempre, implícita só se prompt domain-specific (`forensic/audio/...`); + `ModelPolicy.framing` + `skills descriptions` + `user_profile` + `env` | Sempre ativa (`jarvis` default, `JARVIS_PERSONA`/workspace/`/persona`); `_tools_catalog` derivado da persona filtra schema anunciado; `native/text` por `native_tools`; `reasoning low/med/high` display | Sem persona: `Task.persona/model_tier` só etiqueta p/ `log_task_execution`; comportamento vem de `risk` (skip review) não de framing |
| Interatividade | Nenhuma (API programática; `human_approve` callback) | Total: REPL, `/help/status/map/debug/model/tools/persona/undo`, `prompt_toolkit` session | Nenhuma: `pause`-file gate (`skip`, sem consumir attempt), Telegram `notify` + eventbus `task_*/run_*`, `dry_run`, `is_paused` antes de discovery e task |

---

