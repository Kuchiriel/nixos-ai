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
