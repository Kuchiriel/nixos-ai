# HANDOFF — Estado Atual do Sistema (agosto/2026)

## Auditoria 2026-08-29 — Nightwatch/Harness

### O que foi corrigido nesta sessão:

1. **Nightwatch context budget** — hardcoded 8192 → query real n_ctx (32,768)
   - Antes: compactava a 6,554 tokens (80% de 8K)
   - Depois: compacta a 22,938 tokens (70% de 32K)
   - Arquivos: `context_budget.py`, `harness.py`

2. **.roomodes context info** — corrigido para refletir realidade
   - Antes: "System prompt consome 15-20K, sobram 12K"
   - Depois: "System prompt consome 4-6K, sobram 26-28K"
   - Removido "cat: PROIBIDO" — desnecessário com 32K

3. **nightwatch-timer.nix** — removido `--max-minutes 180` (inválido)
   - Causava 33 crash-loops por noite
   - Adicionado journal logging, Restart=no (emergencial)

4. **package.nix** — testes sandbox-incompatíveis excluídos do checkPhase
   - Testes que escrevem em ~/.local/state/ falham no sandbox Nix

5. **Failure classification** — FailureType enum + classify_failure()
   - Transient → retry with backoff
   - Tool failure → retry
   - Validation → no retry
   - Context exhaustion → compact
   - Unrecoverable → block
   - Arquivo: `harness.py`

6. **Context re-injection** — generate_recovery_summary()
   - Injected after compaction to prevent task amnesia
   - Includes: task, last operation, error, files modified
   - Arquivo: `checkpoint.py`

### O que AINDA NÃO funciona:

| Item | Severidade | Estado |
|------|-----------|--------|
| E2E real (LLM trajectory, não mocks) | HIGH | Parcial (mocks) |
| Observabilidade (logs estruturados por task) | MEDIUM | Básico |
| Multi-project isolation real | MEDIUM | Framework existe |
| Noite inteira sem intervenção | HIGH | Não demonstrado |

### Comandos para reproduzir:

```bash
# Verificar context budget do nightwatch
nix develop --command python3 -c "from nightwatch.context_budget import query_server_context_size; print(query_server_context_size())"

# Rodar nightwatch em dry-run
nix develop --command python3 -c "from nightwatch.harness import run_nightwatch; run_nightwatch(dry_run=True, max_tasks=2)"

# Verificar timer
systemctl status nightwatch.timer
journalctl -u nightwatch -n 20

# Testes completos
nix develop --command pytest modules/ai/jarvis/tests/ -q
```

### Decisões arquiteturais:

- **Context budget**: query_server_context_size() em vez de hardcoded
- **Compaction threshold**: 0.7 (70%) em vez de 0.8 (80%)
- **Nightwatch timer**: Restart=no (evita crash loops, mas não tem recovery)
- **.roomodes**: guidelines de eficiência, não restrições duras

---

## Resumo Executivo

JARVIS on NixOS é uma "ia de bordo" local-first rodando em Acer Nitro V15
(RTX 4050 6GB / 32GB RAM). O sistema está **funcionando no host físico** com
llama-cpp (Qwen3.6-35B MoE), Qdrant, RAG híbrido, memória episódica,
self-heal, modo idle, gaming profile e testes verdes.

## Hardware

| Componente | Especificação | Estado |
|------------|---------------|--------|
| CPU | i7-13620H (6P+8E, 20 threads) | ✅ Funcionando |
| RAM | 32GB DDR5 | ✅ Funcionando |
| GPU | RTX 4050 6GB | ✅ Funcionando (CUDA) |
| iGPU | Intel UHD 770 | ✅ Funcionando (VA-API) |
| Storage | NVMe (Gen4 + Gen3) | ✅ Funcionando (Btrfs + LUKS) |

## Serviços Ativos

Todos os serviços Jarvis são controlados por `services.jarvis.enable` (toggle global) e `jarvis.target` (systemd target mestre).

| Serviço | Porta | Estado | systemd | Observação |
|---------|-------|--------|---------|------------|
| llama-cpp-server | 8080 | ✅ Rodando | PartOf jarvis.target | Qwen3.6-35B MoE, 192K ctx (profile host) |
| llama-cpp-embeddings | 8081 | ✅ Rodando | PartOf jarvis.target | nomic-embed-text-v2, CPU |
| llama-cpp-rerank | 8082 | ✅ Rodando | PartOf jarvis.target | bge-reranker-v2-m3, CPU |
| qdrant | 6333 | ✅ Rodando | PartOf jarvis.target | Vector DB |
| jarvis-gaming-watcher | — | ✅ Rodando | PartOf jarvis.target | Detecção multi-sinal |
| jarvis-idle | — | ✅ Rodando | — | Self-knowledge |
| jarvis-heal | — | ✅ Ativado | PartOf jarvis.target | Self-heal com MAX 5 restarts |
| jarvis-telegram | — | ⏳ Pendente | — | Precisa criar bot + env file |
| litellm | 4000 | ✅ Rodando | — | Cascade local → Groq → Gemini → OpenRouter |

## Configuração llama-cpp (Host)

```
Profile:    host (ativo)
Modelo:     Qwen3.6-35B-A3B MoE (UD-Q4_K_M, ~20.6GiB)
GPU layers: ngl=45 (atenção na GPU)
MoE:        n-cpu-moe=99 (todos experts na CPU)
Contexto:   196608 tokens (192K, KV cache q4_0)
Threads:    12
VRAM:       ~5.1GB / 6GB
Flags:      --no-mmproj-offload --jinja --split-mode layer --parallel 2
```

**Performance medida (benchmark.sh, 5 runs com warmup)**:
- Prefill: ~367 t/s
- Decode: ~32 t/s (estável, 0.7% drift)
- Descoberta: mmproj na GPU causa degradação 32→14 t/s após 1º request
  (solução: --no-mmproj-offload mantém mmproj em CPU, libera 900 MiB VRAM)

## Testes — USE `nix develop`

```bash
# ✅ CORRETO — provisiona jarvis + pytest + hypothesis + PYTHONPATH:
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# ❌ ERRADO — nix-shell com pacotes soltos não tem dependências do jarvis:
# nix-shell -p python3Packages.pytest python3Packages.requests --run "pytest ..."
```

| Categoria | Quantidade | Status |
|-----------|------------|--------|
| Unitários (sem numpy) | ~578 | ✅ Passando |
| Integração (llama+qdrant) | 4 | ✅ Passando |
| E2E Agent (live) | 10 | 4/10 tools usadas |
| PBT (hypothesis) | 31 | ✅ Passando |
| Security | 6 | ✅ Passando |
| Fuzzing/Mutation | 56 | ✅ Passando |
| Sem numpy (voice/wakeword) | 4 | ❌ Falta numpy |
| Bulldozer (jarvis dev) | 6 | ⏳ Precisa CLI |
| Devtools (pós-refactor) | 9 | ✅ Passando |
| **Total executável** | **~500+** | **✅ Passando** |

## Arquitetura da IA

```
Trigger Word (wakeword)
    ↓
Fast Path / Rules (core/rules.py) — zero LLM
    ↓
Doctor (core/doctor.py) — zero LLM
    ↓
NixOS MCP (providers/mcp.py) — zero LLM
    ↓
RAG (core/rag.py) — embedding + BM25 + RRF + rerank
    ↓
Agent (core/agent.py) — LLM tool-calling
    ↓
Tools / MCP
    ↓
Validator (core/validator.py) — post-tool-call verification
    ↓
Memory (core/memory.py) — Qdrant episódica
    ↓
Self-Heal (core/heal.py) — restart + audit + lesson
    ↓
Validation (core/ast_guard.py) — AST check
```

**Caminhos que bypassam a LLM**: fastpath (regras declarativas), doctor (health checks), nixos (mcp-nixos read-only).

## Componentes Implementados

### Core AI
- `core/agent.py` — Agente com tool-calling (11 ferramentas + output truncation + duplicate detection + loop detector + context budget + validator)
- `core/vision.py` — Captura de tela (grim) + observe_screen (screenshot→vision API→descrição)
- `core/validator.py` — Validação pós-tool-call (shell errors, file existence, test failures)
- `core/eval_harness.py` — Eval harness (task templates, trajectory recording, success criteria)
- `core/loop_detector.py` — Detecção de loops (duplicate, cycle, edit-revert, stagnation)
- `core/context_budget.py` — Gestão de contexto (token estimation, truncation, compression)
- `core/router.py` — Roteamento em cascata (fastpath → doctor → nixos → rag → agent)
- `core/rules.py` — Motor de regras declarativas (substitui RiveScript)
- `core/rag.py` — RAG híbrido (dense via nomic-embed-text-v2-moe + sparse BM25 + RRF + rerank via bge-reranker-v2-m3, chunk 2000, mtime cache)
- `core/memory.py` — Memória episódica (Qdrant: remember/recall/lessons/forget)
- `core/vault.py` — Memória de longo prazo (markdown git-syncado)
- `core/voice.py` — STT (faster-whisper) + TTS (Kokoro-82M)
- `core/heal.py` — Self-heal (restart + audit JSONL + lesson, MAX 5 restarts, post-restart verify)
- `core/validator.py` — Post-tool-call validation (shell errors, file existence, test failures, NixOS patterns)
- `core/eval_harness.py` — Eval harness (task templates, trajectory recording, success criteria)
- `core/loop_detector.py` — Loop detection (duplicate, cycle, edit-revert, stagnation)
- `core/context_budget.py` — Context budget management (token estimation, truncation, compression)
- `core/doctor.py` — Health checks (9 verificações, HTTP check, pgrep -x)
- `core/benchmark.py` — Benchmark da cascata
- `core/eval_rag.py` — Avaliação de qualidade RAG (NDCG/Recall)
- `core/regression.py` — Teste de regressão
- `core/hwdetect.py` — Detecção de hardware
- `core/hwprofile.py` — Profile de otimização por hardware
- `core/idle.py` — Modo idle (self-knowledge)
- `core/user_profile.py` — Perfil de usuário dinâmico
- `core/emotion.py` — Estado emocional para TTS
- `core/audiobook.py` — Handler de audiobooks
- `core/devtools.py` — Ferramentas de desenvolvimento (estilo Aider)
- `core/circuit_breaker.py` — Circuit breaker (fallback remoto)
- `core/health_monitor.py` — Monitor de saúde
- `core/eventbus.py` — Barramento de eventos
- `core/triggers.py` — Triggers declarativos
- `core/vision.py` — Captura de tela
- `core/feedback.py` — Feedback ao usuário
- `core/logging.py` — Logging JSONL
- `core/config.py` — Configuração central (env-driven)
- `core/gaming.py` — Detecção de jogos (multi-sinal: GPU + Hyprland + Steam)
- `core/ast_guard.py` — Validação AST
- `core/ast_cache.py` — Cache de AST

### Providers
- `providers/llm.py` — Cliente LLM (OpenAI-compatible)
- `providers/vector_store.py` — Store vetorial (Qdrant)
- `providers/mcp.py` — Cliente MCP (mcp-nixos)
- `providers/reranker.py` — Reranker (bge-reranker-v2-m3)
- `providers/telegram.py` — Canal Telegram

### Serviços NixOS (todos com mkIf services.jarvis.enable + PartOf jarvis.target)
- `nixos/modules/jarvis-env.nix` — Master toggle + jarvis.target
- `services/llama-cpp.nix` — llama.cpp (server + embeddings + rerank)
- `services/qdrant.nix` — Qdrant vector DB
- `services/jarvis-heal.nix` — Self-heal daemon (MAX 5 restarts)
- `services/jarvis-idle.nix` — Idle mode daemon
- `services/jarvis-telegram.nix` — Telegram bot
- `services/jarvis-vault.nix` — Vault summarization
- `services/jarvis-gaming.nix` — Gaming profile detection
- `services/litellm-cascade.nix` — LiteLLM cascade

### Home Manager
- `hyprland/` — Window manager (cyan borders, animations)
- `waybar.nix` — Status bar (GPU/CPU/Memory/Battery)
- `services/jarvis-wakeword.nix` — Wake word detection
- `mpvpaper.nix` — Animated wallpaper (iGPU VA-API)

## Achados da Auditoria Code-First (agosto/2026)

### CORRIGIDO NESTA SESSÃO
- **execute_shell duplicado** — tool existia em agent.py E devtools.py. Removido de devtools.py.
- **Sem output truncation** — execute_shell retornava stdout inteiro (MB). Adicionado TOOL_OUTPUT_MAX_CHARS=8000.
- **Sem duplicate detection** — modelo podia chamar mesma tool infinitamente. Adicionado tracking + warning após 3x.
- **RAG chunk 300→2000** — embeddings perdiam contexto com chunks muito pequenos.
- **RAG sem change detection** — re-indexava tudo sempre. Adicionado mtime cache.
- **Self-heal sem max restarts** — loop infinito de restart possível. Adicionado MAX_RESTARTS=5.
- **Self-heal sem verify** — systemctl retornava 0 mas serviço podia não subir. Adicionado polling pós-restart.
- **Doctor pgrep -f muito amplo** — trocado para pgrep -x (match exato).
- **Doctor check_network frágil** — socket 1.1.1.1:53 bloqueável. Trocado para HTTP check.
- **Memory dedup agressiva** — chave 200 chars causava falsos positivos. Aumentado para 500.
- **RAG sparse_terms sem acentos** — regex [a-zA-Z0-9_] descartava PT-BR. Trocado para \w+.

### Pendências que continuam
- **RAG code_index** — collection NÃO EXISTE no Qdrant (nunca indexado)
- **Thinking overhead** — 88% dos tokens no aider são thinking

### Código morto/legado
- `agent.py.bak` — backup no código ativo (remover)
- `rag.py.bkp` — backup na raiz (remover)
- `legacy_index.py` — requer numpy, 4 testes falham

## Pendências Reais

### Críticas
1. **RAG não indexado** — executar `jarvis rag index` para criar `code_index`
2. **Telegram não ativado** — precisa criar bot no BotFather + `/etc/jarvis-telegram.env`

### Importantes
3. **Limpar legado** — remover agent.py.bak, rag.py.bkp
4. **Validar voz/wakeword no host** — implementado mas não testado E2E
5. **sudo ALL NOPASSWD** — temporário, precisa minimizar

### Melhorias
6. **Forçar tool calling** — testar tool_choice: required no Agent
7. **Proxy thinking** — interceptar aider para desabilitar thinking
8. **Vision no host** — validar grim/slurp no Hyprland real
9. **Push para remote** — remote configurado mas sem autenticação SSH/token

## Riscos

| Risco | Severidade | Mitigação |
|-------|------------|-----------|
| sudo ALL NOPASSWD | 🔴 Alto | Minimizar escopo no host |
| Serviços sem sandbox | 🟡 Médio | DynamicUser + ProtectSystem |
| --host 0.0.0.0 sem auth | 🟡 Médio | Firewall + auth no host |
| Sem backup/impermanence | 🟡 Médio | Definir estratégia no host |
| Chave Groq exposta | 🟡 Médio | Rotacionar |

## Decisões Consolidadas (NÃO reabrir)

1. **llama.cpp > Ollama** — declarativo, sem daemon desnecessário
2. **Qdrant > ChromaDB/NumPy** — production-ready, hybrid search nativo
3. **rules.py > RiveScript** — não está no nixpkgs, quebraria tese declarativa
4. **models.nix = única fonte de verdade** — nada de download imperativo
5. **KV cache q4_0** — eficiente para 128K contexto em 6GB VRAM
6. **n-cpu-moe 50** — experts na RAM, atenção na GPU
7. **Telegram > ntfy** — bidirecional + aprovação inline
8. **services.jarvis.enable** — toggle global com mkIf + jarvis.target
9. **rebuild-host.sh** — sempre validar com nix eval antes do switch
10. **Self-heal MAX 5 restarts** — nunca loops infinitos de restart
11. **Context budget** — 192K tokens (~135K úteis), wc -l antes de ler, max 200 linhas para arquivos grandes
12. **observe_screen** — screenshot→vision→descrição para GUI interaction

## Serviços Ativos (atualizado 2026-08-27)

| Serviço | Porta | Modelo | Status |
|---------|-------|--------|--------|
| LLM | 8080 | Qwen3.6-35B-A3B Q4_K_M | ✅ |
| Embeddings | 8081 | nomic-embed-text-v2-moe Q8_0 | ✅ |
| Rerank | 8082 | bge-reranker-v2-m3 Q4_K_M | ✅ |
| Qdrant | 6333 | Vector DB | ✅ |

## MCP Servers (Roo Code)

| MCP | Tools | Status |
|-----|-------|--------|
| jarvis | 10 tools (execute, read, write, str_replace, observe_screen, capture_screen, nix_eval, nix_check, nix_search, read_chatgpt) | ✅ |
| nixos-mcp | nix, nix_versions (130K+ packages) | ✅ |
| tavily-search | web search (local tavily-mcp@latest, sem mcp-remote) | ✅ |
| context7 | library docs | ✅ |
| playwright | browser automation | ✅ |

## Comandos para Retomar

```bash
cd ~/projects/nixos-ai

# Status rápido
git log --oneline -5
systemctl status llama-cpp-server qdrant llama-cpp-embeddings llama-cpp-rerank

# Rebuild
./rebuild-host.sh

# Testes
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Saúde
jarvis doctor

# VRAM
nvidia-smi

# Code indexer (Roo Code)
# Configurado em vscode-roo.nix: nomic-embed + qdrant local
```


## Sessão 2026-08-29 (continuação)

### P1.4 — Real E2E Test ✅

**Arquivo:** `modules/ai/jarvis/tests/test_nightwatch_real_e2e.py`

27 testes que exercitam o harness com filesystem real (não mocks):

| Classe | Testes | O que valida |
|--------|--------|-------------|
| TestSafeEditorReal | 5 | Atomic write, truncation rejection, markdown rejection, invalid Python, valid change |
| TestValidationReal | 3 | AST validation, invalid Python, truncated file detection |
| TestCheckpointReal | 3 | Save/load, recovery summary, context structure |
| TestTaskQueueReal | 3 | Task lifecycle, failure/block, stats |
| TestContextBudgetReal | 2 | Server query, budget tracking |
| TestFailureClassification | 5 | Transient, validation, context, unrecoverable, default |
| TestFullPipeline | 3 | Edit→validate→commit, failure→recovery, multiple edits→rollback |
| TestLoopDetector | 3 | Threshold, loop detection, reset |

**Correções aplicadas durante o desenvolvimento:**
- `apply_edit` expects `Path`, not `str` — tests corrigidos
- `validate_change` doesn't accept `cwd` — tests reescritos
- TaskQueue and Checkpoint persist to disk — tests usam monkeypatch para isolar STATE_DIR
- `Task.fail()` só marca FAILED após `max_attempts` — tests ajustados
- `_run_agent_loop` referenciava `reasoning_level` sem ser parâmetro — corrigido

### P2 — Anti-Loop Detection ✅

**Arquivo:** `nightwatch/task_queue.py` — `LoopDetector` class
**Arquivo:** `nightwatch/harness.py` — integração no execute_task

Comportamento:
- `LoopDetector(max_attempts=3, window_seconds=300)` — rastreia tentativas por task
- Se uma task falha 3 vezes em 5 minutos → marcada como BLOCKED (anti-loop)
- `loop_detector.reset(task_id)` chamado no sucesso → limpa histórico
- Logging estruturado em JSONL com `loop_detected` status
- Config: `HarnessConfig.loop_max_attempts`, `HarnessConfig.loop_window_seconds`

### P2 — Structured Logging (já existente)

O `_log_progress()` já escreve JSONL em `~/.local/state/jarvis/nightwatch/progress.jsonl`.
Cada entrada contém: `task_id`, `status`, `timestamp` (implícito), e campos extras.
Entradas adicionadas: `loop_detected` (nova).

### Correção: reasoning_level NameError

**Arquivo:** `jarvis/cli/dev.py`

`_run_agent_loop` referenciava `reasoning_level` sem ser parâmetro → NameError em testes.

**Fix:** Adicionado parâmetro `reasoning_level: str = "medium"` e passado nas chamadas.

### Commits desta sessão

```
b518e2b test(nightwatch): add LoopDetector unit tests for anti-loop detection
b25bb8f e2e(test): real E2E test — 27 tests with filesystem operations
```

### Estado atual dos testes

```
27/27 nightwatch E2E pass
105/105 combinados pass (nightwatch + longrun + safe_editor + config + devtools)
```

---

## Auditoria ChatGPT — 2026-08-29

### O que foi feito nesta sessão (complemento)

#### Event Bus Integration ✅

**Problema:** O Event Bus (`core/eventbus.py`, 251 linhas, 13 testes) existia mas não era usado por nenhum módulo de produção.

**Solução:** Integrado no nightwatch harness:

1. **Initialization** — `Harness.__init__` agora cria `EventBus` com subscribers:
   - `harness.notify` → `_handle_bus_notify` (Telegram)
   - `harness.task` → `_handle_bus_log` (JSONL logger)

2. **notify()** — Agora publica via `self._bus.publish("harness.notify", {"message": ...})`

3. **_emit()** — Novo método para eventos de lifecycle:
   - `task_started` — quando task começa execução
   - `task_completed` — quando task termina com sucesso
   - `task_failed` — quando task falha
   - `loop_detected` — quando anti-loop detecta ciclo
   - `recovery` — quando recupera tasks stuck
   - `run_started` — quando harness inicia

4. **Teste** — `test_eventbus_integration` verifica que eventos fluem pelo bus

**Benefício:** Novos subscribers (Waybar, ntfy, Obsidian) podem ser adicionados sem modificar o harness.

#### Bug Fix: LoopDetector Initialization ✅

**Problema:** `self.loop_detector` era usado mas nunca inicializado em `Harness.__init__`.

**Solução:**
- Adicionado `loop_max_attempts` e `loop_window_seconds` ao `HarnessConfig`
- `self.loop_detector = LoopDetector(...)` agora é inicializado no `__init__`

**Impacto:** Sem essa correção, qualquer task que falhasse causaria `AttributeError` em runtime.

### Estado dos testes

```
28/28 nightwatch E2E pass (incluindo Event Bus integration)
13/13 Event Bus pass
122/122 combinados pass
211/211 core suite pass
nix flake check: all checks passed
```

### Commits desta sessão

```
bd76e3c feat(harness): integrate Event Bus + fix LoopDetector initialization
```

### Gaps restantes (prioridade decrescente)

1. **Event Bus em agent.py** — O REPL não emite eventos de lifecycle (baixa prioridade, REPL é síncrono)
2. **Event Bus em idle.py/heal.py** — Usam `send_notification` diretamente (funcional, não quebrado)
3. **Testes para audiobook, hackmd, multi_ai_reader** — 3 módulos sem teste
4. **Nightwatch long-running validation** — Framework existe mas não validado em execução real de horas
5. **Multi-agent coordination** — Primitives existem mas sem implementação real
