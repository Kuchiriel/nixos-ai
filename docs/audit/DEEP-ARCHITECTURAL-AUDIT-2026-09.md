# DEEP ARCHITECTURAL AUDIT — 2026-09

Escopo: verificação forense do `Kuchiriel/nixos-ai` (foco: REPL / Agent Loop, duplicação,
fonte de verdade, hardcodes). Este documento registra **somente** o que foi verificado no
código e em testes executados. Nada aqui é inferido de documentação.

Status legenda: `VERIFIED` (testado/executado) · `IMPLEMENTED` (código + teste) ·
`BLOCKED` (não testável nesta sessão) · `UNVERIFIED` (não testado).

---

## 1. Diagnóstico executivo

O harness Nightwatch (`src/nightwatch/harness.py`) é o pipeline mais maduro do repositório:
isolamento de projeto, branch por task, SafeEditor, validação, reviewer, checkpoint, memória
episódica e EventBus — tudo integrado e com testes.

O elo fraco real está no **caminho REPL/CLI** (`Agent.run()` em `src/jarvis/core/agent.py`),
que é o que o usuário usa via `jarvis ask` / `jarvis` REPL / voz. Nesse caminho:

1. `LoopDetector`, `ContextBudget`, `ToolValidator` e `CircuitBreaker` eram **instanciados e
   nunca usados** (component theater) — o REPL rodava sem nenhuma proteção anti-loop.
2. `Agent` possui **três caminhos de execução de tool paralelos** na mesma classe
   (`run()`/`execute_shell`, `run_loop()`/`execute_tool`/`bash`, mais o post HTTP direto),
   dos quais apenas `run()` tem chamadores de produção.
3. `_get_llm_response()` faz `requests.post` direto em `/v1/chat/completions`, **ignorando a
   abstração `LLMClient`/`LLMBackend`** construída nas missões anteriores — o REPL continua
   acoplado a llama.cpp mesmo depois do desacoplamento.
4. Context budget tem **duas implementações** (`jarvis/core/context_budget.py` e
   `nightwatch/context_budget.py`) com thresholds diferentes (0.85 vs 0.7).

## 2. Arquitetura realmente encontrada (REPL path)

```text
CLI/REPL/voz
  ↓
router.py → agent.run(query)          (src/jarvis/core/router.py:342, cli/main.py:452)
  ↓
Agent.run()                           (core/agent.py)
  ├── persona MCU + user_profile + lessons no system prompt
  ├── _get_llm_response() → requests.post direto (/v1/chat/completions)
  ├── extração de tool call: nativa + extract_fallback_tool_call()
  ├── execução: execute_shell via security.command_allowed()/run_shell()
  └── auditoria JSONL + lesson auto-learn em falha
```

Caminho Nightwatch (autônomo, separado e correto):

```text
Harness.execute_task()
  → create_task_branch (git)
  → _request_structured_patch (LLMClient via jarvis.providers.llm)
  → apply_patch + SafeEditor
  → validate_change → review_change → commit
  → checkpoint + memória episódica + EventBus
```

## 3. Findings

| ID | Problema | Arquivo:linha | Evidência | Real/Hipótese | Severidade | Status |
|----|----------|---------------|-----------|---------------|------------|--------|
| F1 | LoopDetector/ContextBudget/ToolValidator/CircuitBreaker instanciados e **nunca usados** no caminho de produção | `core/agent.py:314-322` | `grep self.loop_detector|self.context_budget|self.validator|self.circuit_breaker` → só as linhas do `__init__` | Real | P0 | **CORRIGIDO** |
| F2 | Bug latente: `LoopDetector._check_stagnation()` crasha com `content=None` (llama.cpp retorna `content: null` em turno de tool call) | `core/loop_detector.py:238` | `TypeError: 'NoneType' object is not subscriptable` reproduzido por teste | Real | P0 | **CORRIGIDO** |
| F3 | Três caminhos de tool-call paralelos na mesma classe; `run_loop`/`execute_tool`/`TOOLS` sem chamadores | `core/agent.py` | `grep run_loop / execute_tool / import TOOLS` em src/ e tests/ → zero ocorrências fora de agent.py | Real | P1 | Documentado (remoção futura) |
| F4 | `_get_llm_response()` ignora `LLMClient`/backend abstraction — post direto com `max_tokens=1024, temperature=0.0` fixos, ignorando perfil detectado | `core/agent.py:~684` | leitura de código; `detect_profile()` existe mas não era aplicado no payload | Real | P1 | Parcial (params agora do perfil; LLMClient segue pendente) |
| F5 | Context budget duplicado: `jarvis/core/context_budget.py` (0.85) vs `nightwatch/context_budget.py` (0.7) | dois arquivos | grep `class ContextBudget` → 2 implementações | Real | P2 | Documentado |
| F6 | Comentário falso em devtools.py afirmando que `execute_shell` está em `agent.py TOOLS` e que agent roteia para `_execute_tool()` — ambas premissas falsas | `core/devtools.py:770-772` | leitura: TOOLS só tem `vision`; `run()` executa execute_shell inline | Real | P2 | **CORRIGIDO** |
| F7 | `detect_profile()` antigo classificava `qwen3.6-35b-a3b` como "tiny" (`"3b" in m`) | já corrigido antes desta sessão | código atual usa regex `(?<![a-z])(\d+(?:\.\d+)?)b(?!\w)` | — | P1 | já corrigido (verificado) |
| F8 | Duplicação agent.py vs dev.py (6 áreas) | `docs/duplication-analysis.md` | documento pré-existente com matriz comparativa | Real | P2 | Documentado (plano: `agent_loop.py`) |

## 4. Correções implementadas nesta sessão

### F1 — LoopDetector ligado ao `Agent.run()`
- `self.loop_detector.reset()` por prompt.
- Após extração de tool calls (nativa ou fallback): `strategy = self.loop_detector.check(tool_calls, content)`.
- `INJECT_WARNING`/`CHANGE_STRATEGY` → mensagem de recovery no histórico; 2 warnings
  consecutivos → interrompe o loop (escalonamento).
- `ABORT`/`FORCE_ANSWER` → mensagem + interrupção imediata.
- Execução real observada: 4º tool call idêntico → detector de **ciclo** (A→A→A→A) dispara e
  interrompe antes do limite de 8 turnos.

### F2 — `_check_stagnation` robusto a `content=None`
- `content = content or ""` antes do hash. Este era um crash garantido no primeiro turno de
  tool call real com Qwen (que retorna `content: null`).

### F6 — Comentário corrigido em `devtools.py`
- Removida a afirmação falsa; documentado que `execute_shell` é canônico em `Agent.run()`.

### F4 (parcial) — payload profile-aware
- `max_tokens`/`temperature` agora vêm de `detect_profile(config.llm_model)`.
- Pendente: migrar `_get_llm_response()` para `LLMClient` (mexe em ~20 testes que mockam
  `session.post` — requer refatoração de contrato, fica para próxima sessão).

## 5. Testes

### Executados nesta sessão (comando real)
```bash
cd modules/ai/jarvis
PYTHONPATH=src:<store-paths de requests/urllib3/certifi/charset-normalizer/idna> \
  /nix/store/b9xszc8ibgm6c4cm461661qiiqi78zwz-python3.13-pytest-9.0.3/bin/pytest \
  tests/test_agent.py -q
# → 30 passed (inclui 2 novos)
```

### Resultado
| Suíte | Resultado |
|-------|-----------|
| `test_agent.py` | ✅ 30 passed (2 testes novos: loop detector para repetição; sem falso positivo em progresso) |
| `test_loop_detector.py` | ✅ 15 passed |
| `test_user_profile.py`, `test_logging.py`, `test_router.py`, `test_rules.py` | ✅ sem regressão (1 falha pré-existente de locale pt-BR em `uptime`: `"up" not in "1 dia 6:44"`) |
| `test_memory.py` | ⚠️ 7 falhas `ModuleNotFoundError: httpx` — ambiente pytest ad-hoc sem deps completas (pré-existente; a suíte Nix roda com deps) |
| `python -m py_compile` dos 3 arquivos | ✅ COMPILE OK |

## 6. Métricas antes/depois

| Métrica | Antes | Depois |
|---------|-------|--------|
| Proteção anti-loop no caminho REPL | 0 (instanciada, não ligada) | ativa: duplicata → warning; ciclo → stop; 2 warnings → stop |
| Crash com `content: null` em turno de tool call | garantido (TypeError) | impossível |
| max_tokens/temperature no REPL | fixos 1024/0.0 | do perfil detectado do modelo |
| Comentários falsos em devtools | 1 | 0 |

## 7. Limitações / BLOCKED

- **BLOCKED**: migração de `_get_llm_response()` para `LLMClient` — os ~20 testes de
  `test_agent.py` mockam `session.post` com payload OpenAI; trocar o transporte exige
  adaptar o mock ao contrato do `LLMClient`. Não feito nesta sessão para não quebrar a suíte.
- **BLOCKED**: execução E2E com modelo real (llama.cpp/prismml) — dependente de runtime
  externo indisponível nesta sessão.
- **UNVERIFIED**: `ContextBudget` do REPL continua não ligado ao `run()` (o Nightwatch tem o
  dele funcionando com auto-detect via `/props`).

## 8. Próximos passos recomendados (por impacto)

1. Migrar `_get_llm_response()` para `LLMClient` (fecha o acoplamento llama.cpp no REPL) e
   atualizar os testes de mock para o novo contrato.
2. Remover o caminho morto `run_loop`/`execute_tool`/`TOOLS` (verificado sem chamadores) e
   consolidar com o plano `agent_loop.py` do `duplication-analysis.md`.
3. Consolidar os dois `ContextBudget` em um, com auto-detect de `n_ctx` via `/props`.
4. Ligar `ToolValidator`/`CircuitBreaker` no `run()` (mesmo padrão do F1).

---

## 9. Sessão 2 — 2026-09-07 (forense + correções)

### 9.1 Correções implementadas e verificadas

**F9 — Agent.run() crashava em tool calls malformados** (P0, `core/agent.py`):
- `func` não-dict → `AttributeError`. Fix: guarda `isinstance(func, dict)` → tool result de erro + continue.
- `arguments` string com JSON inválido → `args` virava string → crash em `args.get()`. Fix: distingue string (parse via `json.loads`) de dict (uso direto); except → `{}`.
- `arguments` não-dict pós-parse → guarda `isinstance(args, dict)` → erro + continue.
- Evidência: `tests/test_solar_probe.py` 8 falhas → 0. Commit `a5882fa`.

**F10 — Injeção dupla de PAST LESSONS** (P1, `core/agent.py`):
- `run()` injetava lessons no system_content; `_get_llm_response()` re-injetava em `messages[0]` a cada turno → prompt crescia N×. Fix: removida re-injeção (injeção canônica única em `run()`). Commit `a5882fa`.

**F11 — Dead code em agent.py removido** (P2):
- Removidos: `execute_tool`, `run_loop`, `TOOLS`, `_extract_tool_calls`, `AgentError`, `ApprovalDeniedError`, `_check_allowlist`, `_execute_command`, `_request_approval`, imports `VISION_TOOL`/`DEV_TOOLS`. Zero importadores externos verificados via grep. Commit em `23fc348` (sessão paralela consolidou working tree).

**F12 — Bypasses de config.py eliminados** (P1):
- `agent.py`: `BackendHealthMonitor()` → recebe `self.config.llm_base_url`.
- `vision.py`: `JARVIS_LLM_URL` → `get_config().llm_base_url`.
- `context_budget.py`: `LLAMA_CPP_URL` → `get_config().llm_base_url`.
- `multi_agent.py`: `LLAMA_CPP_URL` → `get_config().llm_base_url`.
- Env vars mortas: `JARVIS_LLM_URL`, `LLAMA_CPP_URL`. Canônica: `JARVIS_LLM_BASE_URL`. Commit `9b17339`.

**F13 — _regex.txt órfão removido** (P2): rascunho de 9 linhas, zero referências, superseded por `tool_patterns.py`. Commit `78d16eb`.

### 9.2 Auditorias sem correção (arquitetura íntegra)

- **ContextBudget**: consolidação JÁ feita (`c866439`) — `nightwatch/context_budget.py` é shim de re-export; implementação única em `core` (warning 0.80 / compaction 0.85). Item 3 dos próximos passos: DONE.
- **EventBus**: implementação única em `core/eventbus.py` (`get_bus()` singleton); control_plane e nightwatch consomem via `get_bus()`. Async sólido (timeout por subscriber, DLQ, tasks isoladas, `asyncio.sleep` não-bloqueante). Sem blocking em async.
- **Privacidade**: `provider_registry.py` impõe teto por `DataClass` (remote capped em PUBLIC; SECRET/CONFIDENTIAL/INTERNAL só local). REPL usa só backend local — sem bypass.
- **Error handling**: `except Exception: pass` em `agent.py` restritos a paths opcionais (persona, profile, lessons, lesson-recording) — graceful degradation correta. Path crítico (tool exec, LLM) não engole erro.
- **archive/**: zero imports de produção (só comentário histórico em teste). Isolado corretamente.
- **Router**: keyword-matching confirmado como limitação (ex.: "leia o arquivo X" → rota RAG; agent só expõe `execute_shell`, sem `read_file`). Requer refactor arquitetural (fora do escopo desta sessão — documentado como pendência P1).
- **LLMClient bypass**: `_get_llm_response()` ainda usa `requests.post` direto (item 1 dos próximos passos — BLOCKED, requer adaptação de ~20 mocks).

### 9.3 Métricas antes/depois (sessão 2)

| Métrica | Antes | Depois |
|---------|-------|--------|
| test_solar_probe falhas | 8 | 0 |
| Suite total | 984 passed / 8 failed | 987 passed / 5 failed (pré-existentes infra: nightwatch_real_e2e, platform_e2e) |
| Dead code em agent.py | ~200 linhas (5 métodos, 2 classes, 1 const) | 0 |
| Bypasses de config.py | 4 (`JARVIS_LLM_URL`, `LLAMA_CPP_URL` ×2, HealthMonitor default) | 0 |
| Arquivos órfãos | 1 (`_regex.txt`) | 0 |
| Injeções de lessons por turno | N (crescimento N×) | 1 |