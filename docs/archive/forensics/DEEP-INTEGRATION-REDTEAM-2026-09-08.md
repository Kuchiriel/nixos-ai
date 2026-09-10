# DEEP ADVERSARIAL INTEGRATION AUDIT — 2026-09-08

> Pergunta da sessão: "o sistema funciona como sistema, ou só cada componente isolado?"
> Método: 7 agentes de exploração read-only + verificação pessoal de cada achado
> antes de qualquer patch (evidência > síntese). Só P0/P1 + P2 óbvios mesma
> causa-raiz foram corrigidos (§57). Nenhuma decisão de produto tomada.

## 1. Baseline

- Branch `main`, tree limpo no início. Commits-base: `4c33392` (rebuild-5),
  `ae7bb70` (waybar pkill -x + hearing), `91a94e4` (TTS self-cut),
  `c98288a` (paths canônico), `532f135` (RVC `_run_driver`), `1723b4b`
  (LLMClient), `1482622` (read route), `1ffb095` (validator+budget).
- Herdado como VERIFICADO (isolado): sandbox 834 passed/0 failed; local
  998+/5 infra (nightwatch_real_e2e×3 + platform_e2e×2, precisam de
  Qdrant/llama.cpp vivos); RVC E2E 15.9s; STT PT-BR; wakeword VAD.
- Herdado como BLOCKED (não tocado): ADR-003 personas/jarvismodes, ADR-004
  privacy registry wiring, dev.py convergence (2529L), WebUI source-of-truth,
  chat vs ask, long-run >30min E2E.
- Detalhe: `docs/FORENSIC-SYSTEM-COHERENCE-2026-09-08.md` + BUFFY/HANDOFF
  usados como mapa, não como verdade — cada afirmação reauditada no código.

## 2. Boundary map

| Boundary | Contract | Owner | State crossing | Failure propagation | Tested? |
|---|---|---|---|---|---|
| REPL↔Agent | prompt→AgentResult | agent.py | env MAX_TURNS (era frozen) | TimeoutExpired matava run (CORRIGIDO) | novo teste |
| Agent↔LLM | LLMClient.chat/chat_full | providers/llm.py | ChatResponse(+reasoning) | breaker+telemetry (vision BYPASS corrigido) | novo teste |
| Agent↔Tools | run_shell/timeout 60s | security.py | exit_code/observation | timeout agora é observation | novo teste |
| Agent↔RAG | embed via backend 8081 | llm.py+_embed_breaker | breaker SEPARADO do chat | domínios desacoplados | novo teste |
| Agent↔Memory | lessons(prompt) | memory | — | ok | herdado |
| Agent↔MCP | JARVIS_TOOLS schemas | mcp_server.py | obsidian path hardcoded (CORRIGIDO) | erro observável | novo teste |
| Agent↔Persona | filter_tools | persona.py | policies IGNORADAS (CORRIGIDO) | shell p/ can_write=False | novo teste |
| Voice↔Waybar | /tmp/jarvis-status.json | feedback.py+daemon | hearing até confirmação | TTL 45s cobre hearing | herdado ae7bb70 |
| LLM↔Breaker | before/record/release | llm.py CircuitBreaker | HALF_OPEN travava (CORRIGIDO) | release() no abandono | novo teste |
| ControlPlane↔Bus | subscribe cp-* | integration.py/plane.py | setup duplicava (CORRIGIDO) | guard idempotente | probe manual |
| CLI↔Library | dev.py vs devtools | — | nix eval duplicado | BLOCKED (dev.py) | não |
| WebUI↔State | env mutation | api.py | global+efêmero (documentado) | cache_clear morto removido | novo teste |
| WebUI↔Secrets | /etc/litellm.env | api.py+keys.py | 644+`export ` (CORRIGIDO→600, sem prefixo) | parser tolera legado | novo teste |
| EventBus sync/async | publish vs astart | eventbus.py | coroutine descartada (CORRIGIDO) | DLQ observável | novo teste |

## 3. Bypass findings

- **BUG corrigido — vision.py:303**: `requests.post` manual ao llama.cpp
  (pulava breaker/retry/telemetry/fallback, model "local" hardcoded, msg de
  timeout dizia 120s com timeout=180). Agora via `LLMClient.chat_full()`;
  `ChatResponse.reasoning` adicionado (backends parseiam `reasoning_content`).
- **BUG confirmado, NÃO corrigido (BLOCKED dev.py)**: `cli/dev.py:1111`
  `nix eval/check/search` reimplementa `devtools/nixos` em vez de chamar.
- **LEGACY documentado**: `cli/main.py:298,314` top/journalctl duplicam
  doctor/heal; `launcher.sh` curl health duplica health_monitor.
- **VALID/NECESSARY**: reranker/telegram/hackmd/tavily POSTs (sem runner
  canônico p/ esses); voice subprocess (isolamento CTranslate2/torch, env
  custom); systemd/notify-send (fora do allowlist); audiobook Popen detached.
- **BUG confirmado, fora do escopo (WebUI local)**: `api.py` toca
  `plane._systemd` privado em 3 pontos — trocar por API pública do plane
  exige refator WebUI (P2, listado em riscos residuais).

## 4. State-machine findings

- **P1 corrigido — breaker HALF_OPEN pin**: `before_call()` incrementava
  `_half_open_calls_in_flight`; abandono de stream (GeneratorExit no yield)
  pulava `record_success/failure` → CircuitOpenError eterno, recovery
  impossível sem restart. Fix: `release()` + `except GeneratorExit`.
- **P1 corrigido — EventBus sync drop**: `_dispatch_sync` ignorava retorno
  do handler; subscriber async era descartado em silêncio (+RuntimeWarning).
  Fix: sem loop rodando executa com `wait_for(timeout)`; com loop, fecha a
  coroutine e conta falha (DLQ) — falha observável, nunca silent.
- **P1 corrigido — setup duplicava subscribers**: `subscribe()` faz append
  incondicional; 2º `setup()` = double-delivery. Fix: guard `_setup_done`
  (probe: 0→1, não 0→2). `get_control_plane()` já guardava; o guard cobre
  construção direta.
- **P2 corrigido — DLQ/telemetria sem cap**: `_dlq` (4 sites) e
  `SessionTelemetry.calls` unbounded → vazam em sessões longas/falha
  contínua. Fix: cap 1000/2000 + `dlq_dropped` no stats.
- Estados impossíveis procurados (SUCCESS→RUNNING, TTS×idle, STT×capture):
  nenhum encontrado no código atual — `done` é efêmero por design, TTL 45s
  cobre estados transientes presos.

## 5. Lifecycle findings

- **P1 corrigido — TimeoutExpired abortava `Agent.run()`**: `run_shell`
  (timeout 60s) sem try nos 2 sites → exceção subia, sem final_response,
  sem audit, sem observation. Fix: vira `ERROR: Command timed out after
  60s` + audit exit -1 + fluxo normal (validator→messages.append). Teste
  E2E-mockado prova que a observation chega ao turno 2.
  Achado no caminho: meu primeiro patch usou `continue`, que pulava o
  `messages.append` — pego pelo próprio teste (second pass funciona).
- `Agent` sem `close()` (LLMClient criado em run, pool vaza em recreate):
  SUSPECT documentado — mitigado porque run() cria e descarta por chamada;
  lifecycle explícito é P2 futuro.
- `persona_executor` Harness cacheado sem close + `set_project_root`
  global sem restore: documentado (toca ADR-003 BLOCKED).
- `MCPClient` importado mas nunca `start()/close()` em agent.py: lifecycle
  morto — documentado.

## 6. Restart/recovery findings

- Voice daemon: `followup/expect/suppress` in-memory, perdidos no
  `Restart=always` — aceito por design (janela de segundos), documentado.
- Crash antes/depois de tool: sem journal de intenção — tools são
  re-executáveis pelo modelo no próximo turno via observation; side effects
  externos (git, notify, TTS) sem compensação — documentado como risco P1
  residual (idempotency keys só onde dói: não adicionadas por §57).
- Restart de serviço systemd: estado persistente = arquivos
  (status.json, vault, state_dir); efêmero = breaker, health cache,
  telemetria, DLQ — correto por design.

## 7. Idempotency findings

- Leituras (read_file, rg, STT probe): seguras p/ retry.
- Escritas (speak/clone/notify/play, hash%1e9 colisão, `_gen_ack`
  move-newest race): NÃO idempotentes, sem dedup key — P1 residual
  documentado (retry de voz duplica áudio/notificação).
- `set_status` last-write-wins sem CAS: aceito (sinal de UI, TTL cobre).
- Duplo `setup()`: tornado idempotente (fix).

## 8. Retry findings

- urllib3 Retry total=3 em POST de chat (429/500/502/503/504): chat é
  semanticamente read-only no servidor (slots) — VALID, sem duplex de side
  effect. 400-overflow corretamente excluído.
- Classificação de erro por substring ("timeout"/"connection") é frágil;
  `_classify_error_response` (status-based) existe mas não é usado nesse
  caminho — P2 documentado.
- Voice STT subprocess: read-only, safe p/ retry. Steps com side effect
  (speak/notify): sem retry automático — correto (não duplicar).

## 9. Cancellation findings

- **Teatro confirmado**: `security.run_shell` bloqueante sem kill;
  `webui task_cancel` só marca `abandon()` + SSE (sem handle do proc);
  `providers/mcp` poll 60s sem flag; `_play` TTS fallback sequencial até
  ~150s sem cancel; daemon `KILL_TTS` é kill-only (sem pause/resume).
  Cancelamento chega ao estado, não ao processo — P1 residual documentado
  (exige redesign de execução, não patch pontual).

## 10. Resource ownership

| Recurso | Owner | Cleanup | Veredito |
|---|---|---|---|
| requests.Session (backend) | LLMClient.close/__exit__ | ok | OK |
| Agent-LLMClient por run | — (descartado, sem close) | vaza pool | SUSPECT |
| Harness persona | persona_executor._harness | nunca fecha | documentado (ADR-003) |
| EventBus tasks | _tasks + stop(cancel) | ok | OK |
| MCP stdio Popen | mcp_server timeout→terminate/kill | ok | OK |
| RVC subprocess | _run_driver env custom | ok | herdado 532f135 |
| DLQ/telemetry | caps novos | ok | CORRIGIDO |

- `asyncio.create_task` só no eventbus (owned + awaited) — sem leaks.

## 11. Async task leaks

Nenhum `create_task/ensure_future` fora do eventbus. `_deliver_async` com
`return_exceptions=True`: `CancelledError(BaseException)` num sub pode
envenenar o batch — SUSPECT documentado (raro; gather não propaga, mas o
cancelamento do lote pode interromper subs pendentes).

## 12. Event semantics

- Paralelos: at-least-once com retry + DLQ; ordenados: sequencial estrito.
- Duplicata por re-setup: eliminada (guard). Slow subscriber paralelo não
  bloqueia (gather); ordenado lento bloqueia por design.
- `state._notify` itera lista viva (unsub concorrente = skip/dupe):
  SUSPECT documentado.

## 13. Observability integrity

| Operation | Actual | Reported | Divergência |
|---|---|---|---|
| stream abandonado | desconhecido | nada (breaker travava) | CORRIGIDA (release+telemetry no finally) |
| tool timeout | exceção letal | nada | CORRIGIDA (observation+audit -1) |
| update_system_config | efêmero p/ clientes futuros | "updated" | HONESTO agora (comentário; sem persistência — P2) |
| vision timeout | 180s | msg dizia 120s | CORRIGIDA (via backend canônico) |
| fallback invisível | core breaker só em path morto | — | path morto (registry sem consumers) |
| async drop em sync | coroutine descartada | delivered++ | CORRIGIDA (executa ou DLQ) |
| cancel | só estado | "cancelled" | TEATRO documentado |

## 14. REPL integration

- Cenário A (read explícito): coberto por `test_read_route` (11 contratos).
- Cenário E (tool failure→observation): NOVO teste timeout.
- `dev.py` REPL aplica `filter_tools` (agora com policy); agent/MCP/WebUI
  NÃO filtram — três taxonomias (`CAPABILITY_TOOLS` ≠ `MCP_WRITE_TOOLS` ≠
  allowlist do agent): P1 residual (unificar exige decidir persona default
  por superfície — produto).

## 15. RAG/MCP/Memory integration

- MCP `_handle_rag_search`→QdrantStore: herdado ok.
- **Corrigido**: `_vault_read_from_obsidian` hardcoded `~/vaults/projects`
  + `[]` silencioso + query como regex. Agora `JARVIS_OBSIDIAN_VAULT`,
  `rg -F`, `[{"error"}]` observável. (MemoryVault é outro store — delegar
  mudaria semântica; não delegado de propósito.)
- RAG embed agora sob breaker PRÓPRIO (ver §16 do porquê separado).

## 16. Voice integration

- Cadeia viva validada na sessão anterior (wake→STT→agent→TTS→waybar).
- Timeouts: STT-60 interno vence primeiro; LLM-120; `_play` 30×N;
  RVC-300/1800 SEMPRE estoura o outer-120 com clone=True — P2 documentado
  (filho > pai; brain timeout não cobre clone).
- Daemon `hearing` até confirmação: correto (ae7bb70). `killTTS` heurístico
  (speaking<30s) corre com writers de voice.py — race documentada.
- Sem validação de input STT (sr/ch/duração) nem no `transcribe(path)`;
  `load_mono16k` tolera (resample) — VALID por robustez, não por contrato.
- Retry de speak duplica áudio — sem dedup (§7).

## 17. Project isolation

- `paths.py` contextvar: PASS (1 teste de isolamento herdado).
- **Violações confirmadas**: `cli/dev.py:1964 os.chdir` global;
  `webui api.py:286-290` env global por request HTTP; singletons
  (`get_bus`, `_classifier`, `_est_total`, health caches) sangram
  calibração entre sessões — P1 residual (isolar bus por sessão exige
  redesign; documentado, não patchado).

## 18. Configuration precedence

Autoridade declarada: env (config.py) + arquivos legados (keys.py).
- **Corrigido**: `MAX_TURNS` congelado no import → lido no runtime
  (TOOL_OUTPUT mantido: mudá-lo no meio do run quebraria truncamento
  consistente — decisão documentada).
- **Corrigido**: `cache_clear` morto removido; honestidade sobre efemeridade.
- Shadow systems restantes: `voice_clone._cfg` local, `JARVIS_BASE_DIR`
  vs paths.py, `JARVIS_SKIP_VERIFY` morto, `JARVIS_VOICE_DIR` vs
  `MODEL_DIR_DEFAULT` — P2/P3 listados, não migrados (RVC env history).
- Precedência paths/keys/voice_clone mapeada — sem winners acidentais
  além dos corrigidos.

## 19. Nix reproducibility

- Declarativo ok: models.nix fetchurl+sha256, STT small, sem curl/wget.
- **Violações confirmadas (P1 residual)**: RVC em `/tmp/opencode`
  (venv manual + checkout, GC-unsafe, "some no reboot");
  `JARVIS_VOICE_CLONE_MODEL/INDEX=~/models/*` manuais não rastreados;
  `modelsLink` via activation runner imperativo (conteúdo declarativo ok).
- Bare-metal Disko: runtime NÃO reproduz RVC/voice-clone hoje — gap
  documentado, sem ação (exige empacotamento Nix, fora do escopo).

## 20. Security boundaries

- **P0 corrigido**: `/etc/litellm.env` chmod 644 + formato `export `
  (quebrava keys.py E systemd EnvironmentFile). Agora 600 + `KEY="v"`;
  parser tolera legado; remove limpa ambos os formatos. Docstring que
  afirmava 600 voltou a ser verdadeira (§54).
- **P0 corrigido (policy)**: `filter_tools` agora honra
  can_write/can_execute — cto/coordinator/qa/security perdem
  execute_shell+write. can_commit/can_deploy NÃO enforcáveis nesta camada
  (tudo via shell) — residual documentado.
- Choke point real: `command_allowed`+allowlist+approval no agent;
  `DANGEROUS_COMMANDS` definido mas nunca checado (morto — funciona por
  default-deny; documentado, não removido por cautela).
- Falsa sensação: `provider_registry.route()` (SECRET→local) com ZERO
  consumers; `ContentSafetyFilter` só vive no path morto do registry;
  `confirmed/approve` é bool do cliente (forjável); `yolo` auto-aprova
  (escolha UX explícita — não tocado); Telegram sem check
  persona/project; `persona.delete_note` sem policy; `devtools args.split`
  permite flag injection (sem shell, mas flags); shell tools com
  `os.chdir` escapam via `../` (jail só em file tools).
- `self_test shell=True` → argv sem shell (higiene; callers eram fixos).

## 21. Test integrity

- Ordem: sem dependência detectada; riscos mapeados (`/tmp/jarvis_mcp_*`
  fixos no e2e — colisão em paralelo; resto usa tmp_path/monkeypatch).
- Paralelismo: inseguro hoje (paths fixos e2e, coleções Qdrant
  compartilhadas sem cleanup, env global em api/voice_clone) — NÃO
  habilitado; documentado quais são unsafe.
- Sandbox 834 vs local ~998+: explicado (conftest dropa 9 arquivos por
  nome + skipifs live; docstring de test_rag mente "sem serviços" com
  pytestmark=integration — P3 anotado).
- 5 falhas infra: causa documentada parcial; inferência mapeada
  (Qdrant/llama.cpp, systemd, áudio). Nenhum teste "consertado" com mock
  falso; nenhum teste desapareceu (test_mcp_vault_search.py NOVO roda no
  sandbox — fora do módulo e2e pulado).
- Reverso: arquivos tocados passam em ordem reversa (ver Evidência).

## 22. Code deleted

Nenhum módulo deletado nesta sessão (§59: registry morto é BLOCKED ADR-004
— deletar preemptaria decisão de produto). Removidos: `shell=True`
(self_test), `requests.post` manual (vision), `cache_clear` morto,
`export ` prefix, regex rg, `continue` que engolia observations.

## 23. Refactors performed

1. `CircuitBreaker.release()` + cobertura embed (breaker próprio) + testes.
2. `LLMClient.chat_full()` (extração de `chat()`) — caminho canônico p/
   callers que precisam de ChatResponse crua.
3. `ChatResponse.reasoning` + parse nos 2 backends.
4. Timeout de tool → observation (2 sites + auto-learn via exit_code).
5. Policy enforcement em `filter_tools` (+ conjuntos _EXEC/_WRITE).
6. Formato/perms de `/etc/litellm.env` + tolerância legado (writer+parser).
7. Busca obsidian configurável + erro observável.
8. DLQ limitada + stats, telemetria limitada, setup idempotente,
   sync-async honesto, MAX_TURNS runtime, _run_cli sem shell.

## 24. Remaining BLOCKED

ADR-003, ADR-004 (incl. deletar-ou-ligar registry+core breaker morto),
dev.py convergence (incl. nix-eval duplicado), WebUI source-of-truth,
chat vs ask, long-run E2E, default provider.

## 25. Remaining product decisions

Personas semântica, provider default (custo×latência×privacidade), WebUI
state authority, chat/ask merge-or-split, persistência de runtime config,
empacotamento RVC p/ bare-metal.

## 26. Residual risks

- P1: cancelamento teatral; retry de voz duplica side effects; RVC
  timeout filho>pai; singletons cruzam sessões; três taxonomias de tools;
  crash mid-side-effect sem compensação; registry de privacidade morto
  (falsa sensação); Telegram sem policy; `../` escape em shell tools.
- P2: substring-error-classify; `confirmed` forjável; state._notify race;
  mcp CancelledError batch; shadow envs; `DANGEROUS_COMMANDS` morto;
  STT sem validação de input; killTTS race; `/tmp` RVC GC-unsafe.
- P3: test_rag docstring mente; vision timeout 180→120 (canônico agora).

## 27. Evidence

- Suite final: 1020 passed, 5 failed (as 5 infra conhecidas:
  nightwatch_real_e2e x3 + platform_e2e x2, sem Qdrant/llama vivos),
  21 skipped, 1 xfailed, 4 xpassed. `nix flake check --no-build`:
  all checks passed. compileall: OK. Reverso: 132/132.
- Novos testes: 4 (breaker/embed) + 2 (agent timeout/max_turns) + 3
  (persona policy) + 3 (webui keys) + 2 (mcp vault) + 3 (eventbus) = 17.
- Arquivos tocados: 12 src + 7 tests + 1 novo teste + este relatório.
- Commits (sem push): 9f0edbf (breaker/vision), ffc0ede (agent),
  266cc37 (persona), e43ee8f (webui keys), 3a4c0d0 (mcp vault),
  0ce092c (eventbus/lifecycle), + este relatório.
- `git status --short`: limpo após commits.
