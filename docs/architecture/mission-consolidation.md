# MISSÃO: CONSOLIDAÇÃO DO CÓDIGO — Eliminar Entropia, Unificar Pipeline

## CONTEXTO DA AUDITORIA

O projeto nixos-ai possui **109 arquivos Python** com **34.198 linhas de código** e **63 arquivos de teste**.

A auditoria revelou que **~40% do código é morto, duplicado ou desconectado**:

### Código Morto (0 imports externos)

| Arquivo | Linhas | Status |
|---------|--------|--------|
| `agent_loop.py` | ~600 | Nunca importado por ninguém |
| `subagent.py` | ~200 | PAUSADO, nunca limpo |
| `ast_guard.py` | ~150 | Nunca importado |
| `learning.py` | ~100 | Nunca importado |
| `vision_analyzer.py` | ~200 | Nunca importado |
| `audiobook_ui.py` | ~300 | Nunca importado |

### Módulos Duplicados (6 pares)

| Par | O que acontece |
|-----|---------------|
| `orchestrator.py` (core) vs `multi_agent.py` (nightwatch) | Dois orchestrators, nenhum funcional |
| `subagent.py` (core) vs `harness.py` (nightwatch) | Dois executors, harness é o real |
| `workitem.py` (core) vs `task_queue.py` (nightwatch) | Dois sistemas de task, task_queue é o real |
| `context.py` vs `context_budget.py` | Dois gerenciadores de contexto, context_budget é o real |
| `health_monitor.py` vs `doctor.py` | Dois monitores de saúde, doctor é o real |
| `validator.py` (core) vs `validator.py` (nightwatch) | Dois validadores, nightwatch é o real |

### Pipeline Real vs Pipeline Declarada

**Pipeline REAL** (o que funciona):
```
persona_executor.py
  → orchestrator.py (PAUSADO — mas ainda usado!)
    → harness.py
      → LLM (via _default_call_llm)
        → patcher.py
          → safe_editor.py
            → validator.py (nightwatch)
              → evaluator.py
                → checkpoint.py
                  → safety.py
                    → git commit
```

**Pipeline DECLARADA** (o que a documentação diz):
```
Agent Loop → Tool Executor → Validation → Review → Commit
```

**Problema**: A pipeline real depende de `orchestrator.py` que está marcado como PAUSADO. O `persona_executor.py` cria `Orchestrator()` e usa `work_engine.create()` e `assign_task()` — funções que existem no módulo pausado.

### O Que Está Realmente Conectado

| Componente | Conectado? | Uso Real |
|-----------|-----------|----------|
| harness.py | ✅ | Engine principal — executa tasks |
| task_queue.py | ✅ | Fila persistente de tasks |
| patcher.py | ✅ | Aplica patches do LLM |
| safe_editor.py | ✅ | Escrita atômica + validação |
| validator.py (nightwatch) | ✅ | Valida syntax + tests |
| evaluator.py | ✅ | Review independente |
| checkpoint.py | ✅ | Save/restore state |
| safety.py | ✅ | Branch isolation + protected paths |
| persona_executor.py | ⚠️ | Usa orchestrator PAUSADO |
| orchestrator.py | ⚠️ | PAUSADO mas ainda importado |
| workitem.py | ⚠️ | PAUSADO mas ainda importado |
| agent_loop.py | ❌ | Nunca usado |
| subagent.py | ❌ | Nunca usado |
| context.py | ❌ | Nunca usado (ContextPipeline) |
| health_monitor.py | ❌ | Nunca usado |
| learning.py | ❌ | Nunca usado |
| ast_guard.py | ❌ | Nunca usado |
| vision_analyzer.py | ❌ | Nunca usado |

---

## OBJETIVO

Transformar o código de 109 arquivos com ~40% de entropia em um sistema limpo com ~65 arquivos onde cada módulo tem um papel claro e é realmente usado.

**Não é refatoração cosmética. É eliminação de código morto e unificação de duplicatas.**

---

## REGRA PRINCIPAL

Antes de mover ou deletar qualquer coisa:

1. Leia o arquivo
2. Verifique todos os imports
3. Verifique se é usado em runtime (não apenas importado)
4. Se tiver lógica útil, consolide no módulo real
5. Se for código morto, mova para `archive/`
6. Nunca delete sem archive

---

## FASE 1 — AUDITORIA COMPLETA (antes de mexer)

### 1.1 Mapear cada arquivo morto

Para cada arquivo com 0 imports externos:
- Ler o código
- Identificar se há lógica útil
- Se sim: onde consolidar?
- Se não: archive/

### 1.2 Mapear cada duplicata

Para cada par duplicado:
- Qual é o real? (o que funciona)
- Qual é o morto? (o que nunca é chamado)
- Há lógica no morto que falta no real?
- Se sim: migrar antes de arquivar

### 1.3 Mapear dependências do orchestrator PAUSADO

O `persona_executor.py` depende de:
- `Orchestrator()` — cria instância
- `work_engine.create()` — cria work item
- `assign_task()` — atribui a agente
- `complete_task()` — marca como completo
- `fail_task()` — marca como falha

**Todas essas funções precisam ser substituídas antes de arquivar orchestrator.py.**

---

## FASE 2 — CONSOLIDAR PERSONA_EXECUTOR (crítico)

O `persona_executor.py` é o ponto de entrada real para execução autônoma. Ele depende do orchestrator PAUSADO. Precisa ser refatorado para usar diretamente o harness.

### 2.1 Refatorar persona_executor

```python
# ANTES (usa orchestrator PAUSADO):
self.orchestrator = Orchestrator()
item = self.orchestrator.work_engine.create(...)
agent = self.orchestrator.assign_task(item.id, persona.id)
success = harness.execute_task(harness_task)
self.orchestrator.complete_task(item.id, ...)

# DEPOIS (usa harness diretamente):
from nightwatch.task_queue import Task, TaskStatus
task = Task(id=..., project=..., description=..., ...)
harness.queue.add_task(task)
success = harness.execute_task(task)
# State transitions handled by task queue, not orchestrator
```

### 2.2 Migrar lógica de persona selection

A lógica de seleção de persona em `orchestrator.py` pode ser movida para `persona.py` (que já existe).

### 2.3 Testar

Executar PersonaExecutor em projeto real (Corretor) e verificar:
- Task criada na fila
- Harness executa
- State transitions corretas
- Events publicados
- Control Plane recebe

---

## FASE 3 — ARQUIVAR CÓDIGO MORTO

### 3.1 Criar archive/

```
nixos-ai/archive/
├── core/
│   ├── agent_loop.py
│   ├── subagent.py
│   ├── ast_guard.py
│   ├── learning.py
│   ├── vision_analyzer.py
│   ├── audiobook_ui.py
│   ├── health_monitor.py
│   ├── context.py
│   └── legacy_index.py
├── nightwatch/
│   └── multi_agent.py
└── README.md  # explica o que cada arquivo fazia e por que foi arquivado
```

### 3.2 Não deletar — mover

Cada arquivo movido para archive/ deve ter:
- Commit message explicando por que
- Referência ao módulo que o substitui
- Tag no README do archive

---

## FASE 4 — UNIFICAR CONTEXT BUDGET

Dois módulos de contexto:
- `jarvis/core/context.py` — ContextPipeline (nunca usado)
- `jarvis/core/context_budget.py` — ContextBudget (usado pelo harness)
- `nightwatch/context_budget.py` — ContextBudget (duplicata)

### 4.1 Consolidar

- `jarvis/core/context.py` → archive/
- `nightwatch/context_budget.py` → verificar se é idêntico ao core
- Se sim: usar apenas `jarvis/core/context_budget.py`
- Se não: mesclar

---

## FASE 5 — UNIFICAR VALIDATOR

Dois validadores:
- `jarvis/core/validator.py` — funções soltas
- `nightwatch/validator.py` — o real

### 5.1 Verificar

- O validator do core tem lógica que falta no nightwatch?
- Se sim: migrar
- Se não: archive/ o core

---

## FASE 6 — UNIFICAR HEALTH MONITORING

- `jarvis/core/health_monitor.py` — monitor de inferência
- `jarvis/core/doctor.py` — diagnóstico do sistema

### 6.1 Verificar

- health_monitor.py tem funcionalidade que doctor.py não tem?
- Se sim: integrar no doctor
- Se não: archive/

---

## FASE 7 — LIMPAR CLI

O `cli/main.py` e `cli/dev.py` importam orchestrator e workitem PAUSADOS.

### 7.1 Atualizar imports

Substituir imports de orchestrator/workitem por harness/task_queue.

### 7.2 Remover comandos mortos

Comandos que dependem de módulos arquivados devem ser removidos ou atualizados.

---

## FASE 8 — ATUALIZAR SELF_TEST

O `self_test.py` testa módulos PAUSADOS e mortos.

### 8.1 Remover testes de módulos arquivados

### 8.2 Adicionar testes dos módulos reais

---

## FASE 9 — VERIFICAR INTEGRIDADE

### 9.1 Rodar todos os testes

```bash
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q
```

### 9.2 Verificar imports

```bash
python3 -c "import jarvis.core; import jarvis.control_plane; import nightwatch; print('OK')"
```

### 9.3 Verificar pipeline real

Executar PersonaExecutor em Corretor e verificar chain completa.

### 9.4 Atualizar requirement matrix

---

## FASE 10 — DOCUMENTAÇÃO

### 10.1 Atualizar BUFFY.md

Remover referências a módulos arquivados.

### 10.2 Atualizar HANDOFF.md

Nova estrutura de módulos.

### 10.3 Criar ARCHITECTURE.md

Diagrama do pipeline real com apenas módulos que existem.

---

## MÉTRICAS DE SUCESSO

| Métrica | Antes | Depois |
|---------|-------|--------|
| Arquivos Python | 109 | ~65 |
| Linhas de código | 34.198 | ~22.000 |
| Módulos mortos | 8+ | 0 |
| Pares duplicados | 6 | 0 |
| Imports de PAUSADO | 8 | 0 |
| Testes passando | 60+ | 60+ |
| Pipeline real | Funciona com PAUSADO | Funciona sem PAUSADO |

---

## RESTRIÇÕES

- NÃO mexer em Hyper-V/VM
- NÃO mexer em LLM/Bonsai/PrismML
- NÃO deletar — sempre archive/
- NÃO quebrar testes existentes
- NÃO criar novos módulos duplicados
- Cada fase deve terminar com testes passando
- Commit por fase, não tudo de uma vez

---

## ORDEM DE EXECUÇÃO

1. Fase 1 (auditoria) — sem mexer em código
2. Fase 2 (consolidar persona_executor) — crítica
3. Fase 3 (arquivar morto) — baixo risco
4. Fase 4-6 (unificar duplicatas) — médio risco
5. Fase 7-8 (limpar CLI/self_test) — baixo risco
6. Fase 9 (verificar integridade)
7. Fase 10 (documentação)

**Total estimado: 3-4 sessões de trabalho focado.**

---
**Ver também:** [[agent-harness]] | [[nightwatch-components]]
[[ADR-001-agent-platform]] | [[../audit/current/FULL-REPO-AUDIT-2026-09-03]]
[[../audit/current/SESSION-AUDIT-2026-09-04]]
[[../../HANDOFF]] | [[../../AGENTS.md]] | [[../../README]]
