# Gap Analysis — 2026-08-29

Fonte: Conversa com ChatGPT via MCP (`jarvis_read_chatgpt`)

## O que o ChatGPT identificou

### 1. Problema Central: "Mimo foca no final da conversa"

> "o Mimo está usando a conversa como contexto, mas está priorizando o trecho final, então ele tende a atacar o estado mais recente sem reconstruir a cadeia de decisões, problemas já investigados e pendências."

**Impacto**: O agente local repete trabalho já feito, ignora decisões anteriores, e não mantém memória de longo prazo entre sessões.

### 2. README era enganoso (JÁ CORRIGIDO ✅)

ChatGPT identificou problemas específicos:
- "100% local" mas documenta fallback remoto
- "12 fases implementadas" sem distinguir funcional/experimental
- NDCG@5 = 1.0 como propriedade, não como resultado de avaliação
- "auto-cura, auto-melhora" sem autonomia real validada
- 405+ testes = maturidade funcional
- Arquitetura Mermaid = sistema desejado, não implementado

**Status**: README reescrito nesta sessão.

### 3. Missões que o ChatGPT criou (6 prompts na fila)

| Missão | Prioridade | Status |
|--------|-----------|--------|
| P0.1 — Sanear m3ta e fixpoints Nix | P0 | ✅ Resolvido |
| P0.2 — Hardening avaliação e rebuild Nix | P0 | ✅ Resolvido |
| P0.3 — Editor seguro para agentes LLM | P0 | ✅ Resolvido (SafeEditor) |
| P0.4 — Consolidar Nightwatch v2/v3 | P0 | ✅ Resolvido |
| P1.1 — E2E harness real | P1 | ✅ Parcial (27 testes E2E) |
| P1.2 — Autonomia long-run e multi-projeto | P1 | 🧪 Framework existe, não validado |

### 4. Princípio que falta no harness

> "TESTE UNITÁRIO PASSANDO NÃO É EVIDÊNCIA DE QUE UM AGENTE CONSEGUE COMPLETAR UMA TAREFA."

Níveis de evidência que o harness deveria diferenciar:
```
unit pass
→ integration pass
→ tool execution pass
→ agent trajectory pass
→ behavioral pass
→ task acceptance
→ mission completion
```

**Gap atual**: O harness termina em "unit pass" e "task success" mas não valida "mission completion".

### 5. Context Management ainda inconsistente

> "unificar n_ctx real do llama.cpp com o ContextBudget do Nightwatch/Roo"

**Feito nesta sessão**:
- REPL: query `/props` → n_ctx=32,768 ✅
- Nightwatch: query server → auto-detect ✅
- .roomodes: info corrigido ✅

**Gap restante**: Roo Dev ainda pode ter limites independentes.

### 6. O que o ChatGPT recomenda para next step

> "transformar o Nightwatch em um harness orientado a evidências, começando por context management + execução E2E real + edição estrutural segura"

Critérios de sucesso que o ChatGPT define:
1. Agent trajectory executa de verdade
2. Tools são chamadas de verdade
3. Resultados são consumidos
4. Agente verifica resultado independentemente
5. Artefato é sintaticamente/estruturalmente válido
6. Validação behavioral/E2E passa
7. Evidência é persistida
8. Recovery de interrupção funciona

## Gaps Restantes (após esta sessão)

### P0 — Crítico
- [ ] Nightwatch não validado em execução autônoma real (multi-hora)
- [ ] Recovery após condensing não testado E2E

### P1 — Importante
- [ ] E2E harness: trajetória LLM completa (não mocks)
- [ ] Observabilidade: logs estruturados por task com timestamps
- [ ] Anti-loop: detectado mas não testado em cenário real

### P2 — Estabilidade
- [ ] 2 falhas pre-existentes em testes (harness_e2e, test_memory)
- [ ] Roo Dev context limits podem conflitar com harness

### P3 — Capacidade
- [ ] Multi-agent coordination
- [ ] Sub-agents especializados
- [ ] Obsidian/HackMD integration

## Ação Imediata Recomendada

O ChatGPT sugere: **não mandar mais um prompt genérico**. Em vez disso:

1. Usar o MCP para ler a conversa como contexto
2. Mandar tarefa específica e operacional
3. Obrigar separação entre: investigado / implementado / medido / hipótese / débito técnico

Isso é exatamente o que o `AGENTS.md` + `HANDOFF.md` + `NIGHTLOG.md` deveriam suportar — e parcialmente suportam.

---
**Ver também:** [[../HANDOFF]] | [[../AGENTS.md]] | [[../README]]

---

# Round 3 — Verificação (2026-08-29)

## Componentes verificados nesta rodada

### ✅ Funcional e integrado
| Componente | Evidência |
|-----------|-----------|
| Vision (screenshot) | `vision.py` — grim → PIL → base64 → llama.cpp vision |
| MCP vision tools | `jarvis_capture_screen`, `jarvis_observe_screen` expostos |
| Idle mode | Integrado no CLI (`jarvis idle status/worker`) |
| HackMD | Integrado no MCP server (list/get/create/update/sync) |
| Legacy preservation | router (312L), rules (242L), triggers (322L), emotion (117L) |
| Recovery context | `generate_recovery_summary()` agora integrada no harness |
| Context budget | `should_compact()` agora chamada antes de LLM calls |
| Failure classification | `FailureType` enum + `classify_failure()` |
| Loop detector | `LoopDetector` com `record_attempt()` + anti-loop no harness |

### ❌ Gap: Infrastructure existe mas não integrada
| Componente | Linhas | Status |
|-----------|--------|--------|
| Event Bus | 264L | Definido, testado, mas **não importado em nenhum módulo de produção** |
| Audiobook | 476L | Implementado, **zero testes** |
| Multi-AI Reader | 225L | Implementado, **zero testes** |
| HackMD tests | 212L | Implementado, **zero testes** |

### ⚠️ Gap: Parcialmente integrado
| Componente | Status |
|-----------|--------|
| Voice (STT/TTS) | 12 testes, mas requer `jarvis-voice` flag |
| Nightwatch long-run | Timer configurado, mas não validado em execução real multi-hora |
| Multi-agent | TaskQueue existe, mas sem orquestração real |

## Ações recomendadas (prioridade)

### P1 — Integrar Event Bus
O Event Bus (pub/sub, retry, DLQ) está pronto mas não conectado.
Módulos que deveriam usar: voice, triggers, doctor, heal.
Esforço: Médio (importar e conectar, não reescrever).

### P2 — Testes para módulos sem cobertura
- `test_audiobook.py` — 476L sem teste
- `test_hackmd.py` — 212L sem teste
- `test_multi_ai_reader.py` — 225L sem teste

### P3 — Validar nightwatch long-run
O timer systemd está configurado, mas o harness nunca foi testado
rodando por >30 minutos com múltiplas tasks.

## Resumo das 3 rodadas

| Rodada | Foco | Gaps encontrados |
|--------|------|-----------------|
| 1 | README, MCP reader, test fixes | shell=True, test failures, m3ta aliases |
| 2 | Segurança, legacy, performance | recovery context não integrada, context budget não chamada |
| 3 | Orquestração, módulos não integrados | Event Bus não integrado, 3 módulos sem teste |

---
**Ver também:** [[../HANDOFF]] | [[../AGENTS.md]] | [[../README]]

---
**Ver também:** [[../HANDOFF]] | [[../AGENTS.md]] | [[JARVIS-COMPARISON]] | [[NIGHTWATCH]]
