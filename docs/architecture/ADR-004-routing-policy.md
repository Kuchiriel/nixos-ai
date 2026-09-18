---
title: "ADR-004: Routing Policy (declarada) vs Mechanism (ligado)"
status: proposed
status_note: BLOCKED — wiring com blast radius no hot path LLM
layer: architecture
related:
  - architecture/ADR-001-agent-platform
  - architecture/agent-harness
  - architecture/context-engineering
---

# ADR-004: Routing Policy (declarada) vs Mechanism (ligado)

## Status: Proposed (BLOCKED — wiring com blast radius no hot path LLM)

## Contexto

Três peças coexistem sem hierarquia explícita:

1. `provider_registry.py`: REGISTRY (LOCAL/FREE/PAID), `DataClass`
   (PUBLIC→SECRET), `route()` / `route_for_persona()` — política de
   privacidade + custo. **Zero consumidores em produção** (só testes).
2. `llm_factory.create_backend()` + `LLMClient`: mecanismo — constrói o
   backend a partir de `config.llm_backend` (string), sem consultar o
   Registry. Caminho quente do REPL (migrado em 1723b4b).
3. `model_policy.ModelPolicy`: eixo ortogonal (stage→tier, VRAM-aware),
   consumido só por `platform_bridge.get_model_tier_for_stage` (advisory).

## Evidência

- `grep route_for_persona|provider_registry import` em src/ (fora do
  próprio módulo): zero ocorrências.
- `test_llm_backend.py::test_aggregators_are_public_only` impõe teto
  PUBLIC a agregadores — política-como-teste, sem enforcement em runtime.
- Consequência atual: nada impede (em código) um backend remoto de
  receber SECRET — a proteção existe como declaração, não como choke
  point ligado. Na PRÁTICA o REPL só usa backend local (config), então
  o risco é latente, não ativo.

## Decisão proposta

- Registry = política autoritativa (o que PODE ir para onde).
- Factory + LLMClient = mecanismo (como constrói/conversa).
- Wiring: `LLMClient.__init__` (ou factory) resolve
  `(data_class, task)` via `Registry.route()`; recusa explícita
  (erro tipado, não fallback silencioso) quando nenhum provider
  atende a classe — fail-closed.
- `ModelPolicy` permanece no eixo stage→tier; Registry pode consumir
  `tier.vram_required_gb` como sinal (convergência futura, não hoje).

## Por que BLOCKED

Toca o hot path LLM recém-estabilizado (1723b4b); exige decidir default
quando múltiplos providers atendem (custo vs latência vs privacidade) e
o contrato de erro (fail-closed quebra fluxos que hoje passam `SECRET`
para `local` implicitamente). Decisão de produto + janela de teste E2E
com backends reais.

## NÃO fazer

- Deletar o Registry ("código morto"): ele é a política declarada e
  seu teste trava regressão de teto. Morte aqui = perda de segurança.
- Wire parcial (só alguns call sites): choke point precisa ser único.

---

**Ver também:** [[ADR-001-agent-platform|ADR-001-agent-platform.md]] | [[agent-harness|agent-harness.md]]
[[context-engineering|context-engineering.md]]
