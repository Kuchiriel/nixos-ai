# Forense agent.py runtime (@explore subagent)

- **sessão:** `ses_f21079cb0ffe95jJqp9Zytn2Yu`
- **quando:** 2026-09-26 18:26 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 7)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No repo /home/nixos/projects/nixos-ai, faça análise forense de modules/ai/jarvis/src/jarvis/core/agent.py (~3173 linhas). NÃO edite nada, só pesquise e reporte. Retorne: (1) qual função/método é o loop principal que chama o LLM (nome + linha), (2) como tools são declaradas (schema) e despachadas, (3) como contexto/memória/RAG/persona entram no prompt, (4) qual verificador de completion roda e quais estados (VERIFIED/UNVERIFIED/STUCK/FAILED), (5) retry/recovery/timeout existentes, (6) qual modelo é selecionado e como, (7) o que conta como sucesso. Liste nomes de funções + números de linha. Seja conciso e factual.

---

## · ?

Análise forense do agent.py em curso — mapeando loop, tools e verificador.

---

## · ?

Mapeamento inicial parcial — aprofundando varredura do loop principal.

---

## · ?

Primeiro mapeamento pronto — agora extraindo detalhes de tools, prompt e modelo.

---

## · ?

Núcleo do agente mapeado — verificando complemento, retries e seleção de modelo.

---

## · ?

Quase completo — lendo trechos finais de despacho e sucesso.

---

## · ?

Em `/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/agent.py` (3173 linhas). Só leitura:

### 1. Loop principal LLM
* `Agent.run(prompt)->AgentResult` :1057. `for turn in range(max_turns)` :1285, `result.turns+=1` :1286.
* Chamada LLM :1326 `response=self._get_llm_response(messages, reasoning_effort, review_focus)`.
* `Agent._get_llm_response` :2889 delega a `LLMClient.chat_with_tools(send_messages,tools,temperature,max_tokens,...role="orchestrator")` :3127-3138, adapta `ChatResponse->{role,content,tool_calls,finish_reason}` :3159-3171.
* Opcional pré-loop: `Agent._draft_plan` :2461 (turno 0, `self.plan` :1198).

### 2. Tools: schema + dispatch
Declaração em `_get_llm_response` :2910-3104, formato OpenAI `{type:function,function:{name,description,parameters}}`:
`read_file` :2910, `list_directory` :2925, `write_file` :2938, `str_replace` :2952, `build_json_dataset` :2968, `sanitize_secrets` :2985, `book_search` :3003, `book_resume` :3017, `synthesize_command` :3031, `execute_shell` :3086-3104 só `if self.mcp_servers` :3085.

Filtros:
* progressive-disclosure :3046-3067 (`_book_tools_offered` :1061, `_data_task_prompt` :400, `_secret_task_prompt` :408, `_synth_offered` :197+3061).
* `tool_class/surface_for` :3072-3082. `strict_tools` :3112-3122 + `_strict_extra` :2618 + `_strict_signatures` :2638 + `_strict_to_response` :2657 (cap 3, `strict-{idx}` :2674).

Dispatch em `run` :1497-2276:
* parse `tool_calls=response.get("tool_calls")` :1403 + fallback texto `extract_fallback_tool_calls` :306,1408 (+`extract_fallback_tool_call` :243,`_normalize_tool_call` :124,`_extract_json_object` :158).
* batch paralelo só-read :1499-1521 via `_parallel_read_batch` :2858.
* serial :1523-1547 (`json.loads(arguments)` :1533-1540) → `elif name==` : `execute_shell` :1553, `read_file` :1703 via `_exec_read_file` :2693, `list_directory` :1730 via `_exec_list` :2755, `synthesize_command` :~1754 via `llm.chat_with_tools(tools=None)` :1774, `build_json_dataset/sanitize_secrets` :1795/1819 via `devtools`, `book_*` :1845 via `_exec_book` :2833, `write_file/str_replace` :1848 via `_exec_write` :2813 em :2125/2179, `execute_shell/jarvis_execute` :2207. Desconhecida=`Unknown tool`. Resultado vira `{"role":"tool","tool_call_id":...}` :2272.

### 3. Prompt: contexto/memória/RAG/persona
`system_content` montado em `run` :1072-1181:
* base `You are JARVIS` :1072 + `TOOL_USE_DISCIPLINE` :1073 (def :370).
* `skills.descriptions_block()` :1077-1081, `TASK MODE SECRET-SANITIZATION` :1084-1094.
* persona `PersonaRegistry().get(persona_id)` :1103-1128 — explícita (`persona_id!=jarvis`) sempre injeta `PERSONA ATIVA:+system_prompt_additions` :1128; implícita só se prompt tem `forensic/áudio/auditoria/specialist/persona` :1113-1126. `ModelPolicy.framing_for(llm_model)` :1176-1181 (`MODEL FRAMING`, persona não entra).
* `UserProfile.load()+build_context_block` :1130-1137 (`USER PREFERENCES`), `ENVIRONMENT OS/Python/CWD/User` :1141-1150.
* memória: `if self.memory: memory.lessons(prompt,top_k=3)` :1157-1161 (`AVOID(past errors)`).
* `messages=[system,user(prompt)]` :1185-1188 + plano `Siga EXATAMENTE...` :1198-1208. Sem RAG injetado; RAG é via tools (`book_search`, `semantic_search/grep` via `execute_shell`, `_exec_read_file`).
* intra-loop: `STEER` :1290-1306, `STATE(no_tool_call,verify)` nudge :1458-1471, `PROGRESS-CHECK turn 5/11` :2393-2413, hints `_partial_coverage_note` :471, `_unexecuted_script_note` :591, `_unread_refs_note` :657, `_placeholder_script_note` :738, `_secret_worked_example` :417.

### 4. Verificador completion
`from jarvis.core.completion import check_completion` em `_finalize` :981, loop sem-call :1418, tail :~2448. Def em `completion.py: check_completion` :599, `missing_deliverables` :554, `classify_error` :942, `CompletionVerdict.status` :34.
* `AgentResult.verdict="unknown"` :847 (+`verified=False` :846). Estados: `VERIFIED|UNVERIFIED|STUCK|FAILED` :847 + `STOPPED` :1300 (steer).
* `Agent._finalize(result,messages,forced)` :973: `forced in(STUCK,FAILED)`→forced+`verified=False` :986-988; `v.status==VERIFIED`→`VERIFIED/verified=True` :989-991 senão `UNVERIFIED/False` :992-994; copia `evidence/missing` :995-997.

### 5. Retry/recovery/timeout
* `MAX_TURNS=8` :393 (override runtime :1236), `MAX_TIME_S=600` :397 (override :1240, estouro→`STUCK time budget` :1312-1317 + `break`).
* `TOOL_OUTPUT_MAX_CHARS=8000` :830, truncado `head60%+tail` :2259-2262. `_HIST_TOOL_BUDGET=12000` :203, `_truncate_history_for_send` :208+3126. `ContextBudget/turn_budget` :947,1226 + `is_overflow→stop` :1390-1400.
* `LoopDetector` :946, `reset()` :1216, `check()` :1477 → `ABORT/FORCE_ANSWER=>_stuck_or_cascade` :1478-1484; `warning!=NONE=>_loop_warnings+=1>=2=>STUCK` :1485-1493.
* `error_seen` mesmo erro 3x→`STUCK` :2426-2430 + `classify_error` :2276-2286. `_repair_malformed_tool_args` :1005 + `_mal_streak>=3=>STUCK` :1370-1379. `finish_reason==length` streak :1345-1362, `>=3` escala p/ plano em prosa. `verify_turns` máx 2 :1252,1436-1447.
* Exceção LLM→`STUCK: LLM call failed` :1328-1336. `_parallel_read_batch max 3 workers/timeout 60s` :2861,2883. Review sintaxe one-shot máx 3 :1258,1318-1323. `memory.remember_lesson` em `exit_code!=0` :1660-1662.
* Cascata API 1x/run: `_try_api_cascade` :2509 (flag `_api_fallback_used` :1220,1522, camada `_api_layer_for` :873 via `cascade_for+RemoteBackend` :2530-2540), `_stuck_or_cascade` :2556 (3 caminhos STUCK).

### 6. Modelo
Default: `config.llm_model` (`__init__` :907, `Agent.__init__` :891). Params por `detect_profile(llm_model)` :2902 (def :36 + `_registry_tier_profile` :87 + `_strict_default` :107 + `_ctx_derived_max_tokens` :68) → `temperature/max_tokens=profile[...]` :3130-3131.
* Roteamento só `if model_requirements` :1193 → `_ensure_routed_model` :2577 via `select_model(req)` :2589 + `base_url_for` :2593 + `ensure_model` :2594 + recria `LLMClient+ContextBudget` :2603-2613. Falha propaga, sem fallback silencioso.
* Planner opcional `_draft_plan:planner_model` :2478-2490. Fallback remoto só via cascata acima.

### 7. Sucesso
Só `check_completion(messages).status==VERIFIED` com evidência em `_finalize` :989. Texto sem tool-call nunca é DONE: checa :1420-1423; oco (`evidence` só `sem erro final`) :1424-1426 + promessa futura (`I will/vou/...`) :1431-1434 não finaliza, consome `verify_turns`; `verify>=2` sem substantivo→`UNVERIFIED+missing` :1436-1447; `_v_ok`→`finalize+break` :1448-1451. `forced STUCK/FAILED` nunca `VERIFIED` :986. Turns esgotados vazio→`STUCK turnos esgotados` :2439-2447; senão `finalize(evidência)` :2448-2450. `final_response` = último `assistant.content` :2433-2437.

---

