# HANDOFF.md — Project Index

> Updated: 2026-09-03

## Quick Start

```bash
# Tests
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q

# Build
nix build .#jarvis --no-link && nix flake check

# WebUI
jarvis-webui  # port 8090
```

## Architecture

```
PersonaExecutor
  → TaskQueue (persistent)
    → Harness (pipeline engine)
      → LLM (via _default_call_llm)
        → Patcher + SafeEditor
          → Validator (syntax + tests)
            → Evaluator (review)
              → Checkpoint + Safety
                → Git commit
```

## Module Map

### Core (jarvis/core/)
- config.py — Configuration (31 imports)
- eventbus.py — Event bus (17 imports)
- memory.py — Episodic memory (17 imports)
- rag.py — Hybrid search (15 imports)
- voice.py — TTS/STT (9 imports)
- feedback.py — Notifications (9 imports)
- workspace.py — Project discovery (8 imports)
- persona.py — Persona registry (7 imports)
- gaming.py — Gaming mode (3 imports)
- health_monitor.py — Backend monitoring (3 imports)

### Nightwatch (nightwatch/)
- harness.py — Main execution engine
- task_queue.py — Persistent task queue
- patcher.py — LLM patch application
- safe_editor.py — Atomic writes
- validator.py — Syntax + test validation
- evaluator.py — Independent review
- checkpoint.py — State persistence
- safety.py — Branch isolation

### Control Plane (control_plane/)
- plane.py — Unified orchestration
- events.py — 58 event types
- state.py — Thread-safe state store
- commands.py — Typed command registry
- notifications.py — Multi-channel routing
- systemd_adapter.py — Safe systemctl

### WebUI (webui/)
- api.py — FastAPI backend (12 endpoints)
- server.py — Uvicorn launcher
- frontend/ — SvelteKit (12 routes, SSE)

## Services

| Service | Port | Status |
|---------|------|--------|
| llama-server | 8080 | Check health |
| embeddings | 8081 | Check health |
| rerank | 8082 | Check health |
| qdrant | 6333 | Check collections |
| WebUI | 8090 | Check /api/health |

## Tests

- 859 passed, 0 failed, 26 skipped, 5 xpassed
- Core: eventbus, feedback, queue, harness_e2e, gaming
- Nightwatch: validator, safe_editor, safety, checkpoint
- Control Plane: events, state, commands, notifications

## 2026-09-07 — opencode auth + fast path enriquecido

### opencode (config/home.nix)

Problema real: "só alguns modelos funcionam; header/token error na maioria".
Duas causas raiz (ambas corrigidas em home.nix):

1. `headers.Authorization = "Bearer \${VAR}"` — o opencode NÃO expande `${VAR}`;
   a sintaxe é `{env:VAR}`. Virou `options.apiKey = "{env:VAR}"` em
   openrouter/groq/cerebras/together/huggingface (sem header Authorization;
   o SDK monta o header a partir do apiKey). Verificado: `opencode debug config`
   mostra o apiKey expandido com a chave real.
2. Shell do usuário é **zsh** mas as chaves só eram carregadas em
   `programs.bash.initExtra` → zsh abria opencode sem env vars. Adicionado o
   mesmo sourcing (keys-wrapper.sh + opencode-auth-sync.sh) ao
   `programs.zsh.initContent`.

Versão: `pkgs.kilo` = opencode do nixpkgs-unstable pinado no flake.lock
(1.18.16, lock de 2026-08-13). `nix run nixpkgs#opencode` é o canal estável
(1.15.10, MAIS VELHO). autoupdate não funciona em Nix. Atualizado:
`nix flake lock --update-input nixpkgs-unstable` → 2026-09-07 (deve trazer
~1.18.29 no próximo rebuild). Modelos mortos atualizados: groq →
`qwen/qwen3.6-27b`, cerebras → `qwen-3.8-27b`.

Testes manuais pós-fix (via OPENCODE_CONFIG com apiKey): groq responde,
cerebras = "Payment required" (conta sem billing — não é config), openrouter =
rota OK (modelos :free às vezes sem endpoint — capacidade). Chaves validadas
por curl direto (HTTP 200).

### Fast path (rules.py + router.py) — portado do legado Manjaro/AI_SYSTEM

- Engine: `! array nome = a b c` + `@nome` (dentro de `[]`/`()` também),
  `[*]` (wildcard opcional), `#` (número), `<star1>..<starN>`, ordenação por
  especificidade (literal > número/alternativa > opcional > wildcard),
  normalização de entrada (tira "jarvis/hey/ei/por favor/pode/você pode/fala"
  do INÍCIO, nunca do final), wildcard `*` agora lazy (não engole o 2º número
  em matemática).
- Handlers novos: `math` (ast-safe, sem eval; "quanto é 8 + 2" → 10, aceita
  vírgula decimal e multi-operando) e `screenshot` (grim).
- DEFAULT_RULES: audiobook com controle completo (pausa/continua/next/prev/
  status no tópico, sem expulsar do tópico), voz com variações PT/EN, sistema
  (cpu/memória/disco/temperatura/hora/data/kernel/uptime/processos),
  saudações, screenshot.
- SEGURANÇA: matching ANCORADO — trigger curto só casa frase EXATA;
  filler no fim nunca é removido; regras com `*` que roubariam pergunta real
  foram removidas (`que livros *`). Testes negativos garantem que perguntas
  reais ("explique como funciona uma cpu", "quanto é a capital da frança")
  NUNCA casam fast path → vão pro LLM.
- Testes: `tests/test_rules.py` (26 → 33 testes). Rodados: test_rules,
  test_router, test_voice, test_benchmark, test_regression, test_intents —
  verdes no env disponível; falhas de `requests`/`hypothesis` são só do env
  ad-hoc (bare pytest), não regressões (a suíte Nix roda com deps completas).

### Pendências abertas

- Validar opencode pós-rebuild (versão esperada ~1.18.29 + modelos reais).
- Cerebras: conta sem billing (pagamento necessário para usar).
- RiveScript legado tem mais regras aproveitáveis (git, typing, vision) —
  portar quando houver handler correspondente no jarvis atual.

---

## 2026-09 — Deep Architectural Audit (forensics pass)

Audit doc: `docs/audit/DEEP-ARCHITECTURAL-AUDIT-2026-09.md`

### Fixes (verified, tests green)

1. **P0 — LoopDetector ligado ao `Agent.run()`** (`core/agent.py`): antes era instanciado e
   nunca usado (component theater). Agora: reset por prompt, `check()` por turno de tool call,
   warnings de recovery injetados no histórico, 2 warnings consecutivos → stop, e
   ABORT/FORCE_ANSWER → stop imediato. Execução real: 4º call idêntico → cycle detector
   interrompe (antes: 8 turnos queimados).
2. **P0 — `LoopDetector._check_stagnation()` crashava com `content=None`**
   (`core/loop_detector.py`): llama.cpp retorna `content: null` em turno de tool call — o
   crash era garantido no primeiro uso real. Fix: `content = content or ""`.
3. **P1 — payload profile-aware** (`_get_llm_response`): `max_tokens`/`temperature` agora vêm
   de `detect_profile(model)` (antes fixos 1024/0.0).
4. **P2 — comentário falso** em `devtools.py` (dizia que execute_shell vive em agent TOOLS e
   roteia para `_execute_tool()` — premissas falsas).

### Tests
- `tests/test_agent.py`: **30 passed** (2 novos: loop detector para repetição idêntica;
  sem falso positivo em fluxo com progresso).
- `tests/test_loop_detector.py`: **15 passed**.
- Falhas pré-existentes fora do escopo: `test_memory` (httpx ausente no pytest ad-hoc),
  `test_rules::test_fastpath_sys_executes_and_blocks` (locale pt-BR: `"up" not in "1 dia 6:44"`).

### Reproduzir
```bash
cd modules/ai/jarvis
PYTHONPATH=src:<store de requests+urllib3+certifi+charset-normalizer+idna> \
  /nix/store/b9xszc8ibgm6c4cm461661qiiqi78zwz-python3.13-pytest-9.0.3/bin/pytest tests/test_agent.py -q
```

### Bloqueadores p/ próxima sessão
- Migrar `_get_llm_response()` para `LLMClient` (fecha acoplamento llama.cpp no REPL; ~20
  testes mockam `session.post` — adaptar contrato).
- Remover caminho morto `run_loop`/`execute_tool`/`TOOLS` (zero chamadores verificados).
- Consolidar `jarvis/core/context_budget.py` + `nightwatch/context_budget.py`.

---

## 2026-09-07 — Deep Forensic Audit (session 2)

### Fixes (verified, tests green)

1. **P0 — Agent.run() crashes on malformed tool calls** (`core/agent.py`):
   - `func` not a dict (e.g. `"function": "not a dict"`) → `AttributeError` crash. Fixed: `isinstance(func, dict)` guard → error tool result + continue.
   - `arguments` as invalid JSON string (e.g. `"{invalid json"`, `"   "`) → `args` became string → `args.get("cmd")` crash. Fixed: detect string vs dict before `json.loads`; except → `{}`.
   - `arguments` as non-dict after parsing → `isinstance(args, dict)` guard → error tool result + continue.
   - Evidence: `tests/test_solar_probe.py` 8 failures → 0. Suite 987 passed / 5 pre-existing infra failures.

2. **P1 — Double lessons injection** (`core/agent.py`): `run()` injected lessons into system_content once; `_get_llm_response()` re-injected lessons into `messages[0]` every turn → system prompt grew N× per N-turn conversation. Removed re-injection from `_get_llm_response` (single canonical injection in `run()`).

### Current audit state
| Area | Status |
|------|--------|
| Agent loop (agent.py) | FIXED crashes; dead code `run_loop`/`execute_tool`/`TOOLS` still present |
| Tool exposure | Agent exposes only `execute_shell` — no `read_file`/`write_file`/`str_replace` (mission CASE 1, 5 blocked) |
| Router (router.py) | Keyword-matching: "leia X" → RAG route, never read_file |
| LLMClient bypass | `_get_llm_response()` uses `requests.post` directly, ignores LLMClient |
| Context budget | 2 implementations (core 0.85 vs nightwatch 0.7) |
| Dev.py vs agent.py | 2529 lines vs 736 lines — massive duplication |
| Voice pipeline | Not yet audited in this session |
| MCP | Not yet audited in this session |
| EventBus / Control Plane | Not yet audited in this session |
| Hardcodes | Not yet audited in this session |

---

## 2026-09-08 — Deep Forensic Audit (session 3: checkpoint + BLOCKEDs)

Checkpoint + validação da sessão paralela (Codebuff): `a0ae4ea` OK;
`e4a4e24` sólido (+1 edge fix); `873d94f` duplicava spawn RVC →
**consolidado** (`532f135`: `clone_wav` adapter fino, `_run_driver`
canônico, template honra CPU_ONLY); `af1cfb8` preservado.

### Fixes (verified, tests green)

3. **P1 — `_get_llm_response()` → `LLMClient`** (`1723b4b`): fim do bypass;
   breaker + telemetria + roteamento de backend no REPL. 26 mocks `+**kw`,
   zero mudança de lógica de teste.
4. **P1 — `read_file` + rota `read`** (`1482622`): CASE 1/5 desbloqueados.
   "leia o arquivo X" → leitura direta; precedência sobre wildcard do
   audiobook (path → read, composta → agent, resto → audiobook).
   `test_read_route.py` (11 contratos).
5. **P2 — wiring final do `run()`** (`1ffb095`): `ToolValidator`
   pós-execução, context guard por prompt, breaker duplicado removido.
   +2 testes.

### Current audit state (updated)
| Area | Status |
|------|--------|
| Agent loop | crashes FIXED; dead code REMOVED; validator+budget WIRED |
| Tool exposure | `execute_shell` + `read_file` (sempre); LLM via `LLMClient` |
| Router | read/audiobook/agent/RAG por evidência (contratos em test_read_route) |
| Config | 4 bypasses eliminados (`9b17339`); envs mortas removidas |
| ContextBudget | implementação única (c866439, pré-existente) |
| Voice RVC | spawn único (`532f135`); CPU_ONLY funcional |
| EventBus/privacy/errors | auditados, íntegros, sem mudança |
| Open P1 | personas ×3 mecanismos; dev.py convergence; WebUI state; long-run E2E |

Evidência: `docs/audit/DEEP-ARCHITECTURAL-AUDIT-2026-09.md` §10.

---

## 2026-09-08 — Pré-missão voz + Forense (RVC urgente, project-root, MCP, personas)

### Voz/RVC (pré-requisito do usuário — ENTREGUE)
- Causa do `--clone` quebrado: zsh sem env (bash tinha) + binário instalado
  STALE com fake-success (driver converteu 0 arquivos, sem verificação).
- Método superior: patchelf do venv → loader nix-ld (prova `env -i`);
  `scripts/rvc-env.sh` canônico; bash+zsh via home.nix; bootstrap com passo
  patchelf. Validação: texto exato do usuário → 15.9s Jarvis real.
- STT small declarativo (models.nix ×4 + symlinks); tiny.en morto (149MB,
  URL quebrada) removido; wget `|| true` eliminado. 2 rebuilds OK.
- STT PT-BR provado; wakeword ativo com VAD; waybar corrigida (writer sem
  ts mentia IDLE durante listening).

### Forense (coerência)
- **Project-root canônico** (`c98288a`, 19 arquivos): `core/paths.py`
  (ctx>env>walk), fim de 3 resolvers + monkeypatch (→contextvar, como o
  próprio código prescrevia). Testes A/B reescritos; `or True` corrigido.
- **MCP**: adapters finos OK; `_handle_rag_search` com schema divergente
  convertido ao store (`8770df8`).
- **Memória**: `lessons("")`→`lessons(prompt)` + teste.
- **Personas**: ADR-003 (Registry canônico, Executor consumidor,
  jarvismodes overlap BLOCKED com stack+não-persistência provados).
- **Registry privacidade**: zero consumidores → ADR-004 BLOCKED (honesto).
- **Integridade**: suite do Agent no sandbox (833→834, 0 failed);
  `hostname`→`echo` (sandbox); docstring-mark corrigida.

Evidência: `docs/FORENSIC-SYSTEM-COHERENCE-2026-09-08.md`.

### Validação viva pós-rebuild-4 (2026-09-08 ~10:46)
- `jarvis speak <270 chars>`: 17.4s wall (síntese + playback integral),
  path impresso, exit 0 — corte eliminado.
- Daemon reagiu ao playback (Speech detected RMS 630-1075) e rejeitou
  corretamente via scorer (não era wake); kill pulado via status speaking.
- Status transitions: speaking (speak) → listening (daemon phase-1) →
  idle. Waybar exibe estados reais (contrato ts ativo).
- Usuário: ABRIR NOVO TERMINAL (shells pré-rebuild não têm RVC env;
  erro agora instrui isso). tmux antigo: restart do servidor tmux.

## 2026-09-09 noite — handoff compactação (Muse Spark)

HEAD nixos-ai: `9ecc320`. Tree: só dirt do Solar (docs dele + legacy-moves
staged). Nada meu pendente. :8080 Bonsai saudável; máquina livre.

Onde parei: P0/P1 ataque executado (verdict, writes c/ approval, paralelos
2.9x, plan mode, transcript, gates, exit-code); xLAM adotado executor
strict; planner C2 VERIFIED+fix manual; suite 1068→1085/5infra; flake verde.
Docs forenses em docs/archive/forensics/ (refs atualizadas).

Aguardando usuário: janela GPU (benches terceiros, planner automático,
Gemma-vision), download nada pendente, retorno ChatGPT, voz/wakeword
(SEGURADO p/ presença dele), modelo Applio (não recebido).
Solar: branch docs/consolidacao-monorepo (prompt enviado); prompt p/ ele
na conversa. Não tocar no dirt dele. Não usar pkill -f (trava a sessão;
kill por PID/porta). Não rodar MoE-CPU nem rigs paralelos pesados.
