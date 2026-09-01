# Harness Audit — P2–P9 — 2026-09-01

## AUDIT MATRIX

| ID | Problema | Evidência (arquivo:linha) | Severidade | Real/Hipótese | Corrigido? |
|----|----------|---------------------------|------------|---------------|------------|
| P2 | LoopDetector contava successos como tentativas | `task_queue.py:88` (old) | P1 | REAL | ✅ `3f6b1e4` |
| P2 | Detector é tempo-based, não content-based | `task_queue.py:88-110` | P2 | REAL | ❌ Limitação aceita |
| P3 | Task.fail() não persistia | `task_queue.py:189` (old) | P0 | REAL | ✅ `3f6b1e4` |
| P3 | Task.complete() não persistia | `task_queue.py:205` (old) | P0 | REAL | ✅ `17487b9` |
| P4 | Evaluator aprovava no-diff | `evaluator.py:100` (old) | P1 | REAL | ✅ `3f6b1e4` |
| P4 | Fallback de parse JSON é "needs_revision" (fail-closed) | `evaluator.py:92` | — | CORRETO | N/A |
| P5 | Sem state machine explícita — transições não validadas | `task_queue.py:37-46` | P2 | REAL | ❌ |
| P5 | DISCOVERED → READY happen via add_task(), não via transição | `harness.py:237` | P3 | REAL | ❌ |
| P6 | Estado é GLOBAL — task_queue.json não particionado por projeto | `task_queue.py:15` | P2 | REAL | ❌ Limitação aceita |
| P6 | Deduplication key agora inclui projeto | `task_queue.py:298` | — | CORRETO | ✅ `3f6b1e4` |
| P6 | ID é UUID — sem colisão entre projetos | `task_queue.py:130` | — | OK | N/A |
| P7 | Compaction em 70% era prematura | `context_budget.py:112` | P2 | REAL | ✅ `3f6b1e4` (→85%) |
| P7 | compress_history() perdia errors/paths/code | `context_budget.py:231` | P2 | REAL | ✅ `3f6b1e4` |
| P7 | Sem checkpoint semântico pré-compactação | `context_budget.py` | P2 | REAL | ❌ |
| P7 | Sem preservação de tool call history | `context_budget.py:250` | P3 | REAL | ❌ |
| P8 | Ignore list em package.nix está correta | `package.nix:49-64` | — | OK | N/A |
| P9 | Pipeline requer LLM real | `harness.py:145` | P0 | BLOQUEADOR | ❌ |

## ARCHITECTURE GAPS

### O que é REAL
- TaskQueue: persistência, recovery stuck tasks, deduplication
- LoopDetector: falha tracking com persistência
- Checkpoint: save/recovery de estado por task
- Project isolation: `use_project_root()` context manager
- SafeEditor: atomic writes, AST validation
- Validator: syntax + imports + test discovery
- Evaluator: fail-closed no parse, require_change para no-diff
- ContextBudget: threshold adaptativo, compressão preserva sinal

### O que é PARCIAL
- State machine: transições existem mas não são validadas
- Context compaction: preserva errors/paths mas perde tool history
- Multi-project: funciona mas estado é global
- Evaluator: "independente" mas usa mesmo LLM e contexto

### O que é BOOKKEEPING
- Persona selection: seleciona mas não muda comportamento do LLM
- Workitem lifecycle: kanban existe mas não impõe transições
- Evidence collection: grava mas não valida contra acceptance criteria

### O que NÃO é verificável sem LLM real
- Task execution end-to-end
- Patch generation
- Review pelo LLM
- Discovery via LLM

## TOP 3 — O que mais impede autonomia real

### 1. P9: Pipeline requer LLM real (BLOQUEADOR)

**Problema:** O harness inteiro depende de `call_llm()` que chama o servidor llama.cpp. Sem ele, nenhuma tarefa pode ser executada. O pipeline real é:

```
LLM → patch → SafeEditor → Validator → Evaluator → Commit
```

Sem o LLM na primeira etapa, nada mais acontece.

**Impacto:** Impossível demonstrar execução autônoma real sem servidor LLM ativo.

**Correção:** Não é um bug — é uma dependência de infraestrutura. A solução é ter o LLM rodando quando o nightwatch executa.

### 2. P7: Context compaction perde tool history (ALTO)

**Problema:** `compress_history()` preserva errors e code blocks, mas perde:
- Tool call history (que ferramentas foram chamadas e quando)
- Intermediate decisions (por que o agente escolheu A em vez de B)
- Validation state (o que foi testado e quando)
- File state (quais arquivos foram modificados)

**Impacto:** Após compactação, o agente pode repetir trabalho ou perder contexto crítico.

**Correção parcial:** A compressão agora preserva errors/paths/code. Mas tool history ainda é perdida.

### 3. P5: State machine sem validação de transições (MÉDIO)

**Problema:** Não existe validação de que uma transição é permitida. Teoricamente, `FAILED → COMPLETED` é possível se alguém chamar `task.complete()` num task que falhou.

**Impacto:** Baixo na prática (o harness controla as transições), mas é uma invariant não garantida.

**Correção:** Adicionar validação de transições no Task.

## VERIFICATION

### Testes executados

```bash
# Testes unitários relevantes
nix develop --command python3 -m pytest \
  modules/ai/jarvis/tests/test_queue.py \
  modules/ai/jarvis/tests/test_loop_detector.py \
  modules/ai/jarvis/tests/test_safe_editor.py \
  modules/ai/jarvis/tests/test_validator.py \
  modules/ai/jarvis/tests/test_eventbus.py \
  modules/ai/jarvis/tests/test_integration.py \
  -q --tb=short

# Resultado: 102 passed
```

### Verificações manuais

1. **P2 LoopDetector**: Testado com cenário success→failure→success→failure. Sucesso limpa histórico. ✅
2. **P3 Task.fail()**: Testado com atomic write. Estado persiste entre chamadas. ✅
3. **P3 Task.complete()**: Verificado que `_persist_now()` é chamado. ✅
4. **P4 Evaluator no-diff**: Testado `require_change=True` rejeita no-diff. ✅
5. **P6 Dedup**: Testado que mesmo description em projetos diferentes NÃO é deduplicado. ✅
6. **P7 Threshold**: Verificado `compaction_threshold=0.85`. ✅

### Commits desta sessão

```
17487b9 fix: Task.complete() now persists immediately (P3 gap)
3f6b1e4 fix: critical harness bugs (P2/P3/P4/P6/P7)
```

## LIMITAÇÕES AINDA EXISTENTES

1. **LLM dependency**: Pipeline não funciona sem servidor LLM ativo
2. **Context compaction**: Perde tool history e intermediate decisions
3. **State machine**: Transições não são validadas explicitamente
4. **Evaluator independence**: Usa mesmo LLM e contexto — não é truly independent
5. **Multi-project state**: task_queue.json é global, não particionado
6. **No real project demo**: Não foi possível demonstrar execução real nesta sessão

## HANDOFF

### O que foi provado
- LoopDetector: falha tracking correto com persistência
- Task.fail()/complete(): atomic write funciona
- Evaluator: no-diff rejeitado quando require_change=True
- Deduplication: project+description key funciona
- Context compaction: threshold 85%, preserva errors/paths/code

### O que continua não provado
- Execução real em projeto externo (requer LLM)
- Recovery após crash real (requer processo morto)
- Compaction sem perda de tool history
- Evaluator truly independent

### Próximos bloqueadores
1. LLM server precisa estar ativo para testes E2E
2. Context compaction precisa preservar tool call history
3. State machine precisa de validação de transições

### Comando para reproduzir verificações

```bash
# Testes unitários
cd ~/projects/nixos-ai
nix develop --command python3 -m pytest \
  modules/ai/jarvis/tests/test_queue.py \
  modules/ai/jarvis/tests/test_loop_detector.py \
  -q --tb=short

# Build Nix
./rebuild-host.sh

# Verificar serviços
sudo systemctl status jarvis.target
```
