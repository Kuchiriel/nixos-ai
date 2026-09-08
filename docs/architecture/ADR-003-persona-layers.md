# ADR-003: Persona Layers — Identidade, Execução e Modos REPL

## Status: Proposed (BLOCKED — decisão de produto pendente, evidência técnica completa)

## Contexto

Três mecanismos coexistem: `PersonaRegistry` (core/persona.py, 10 personas
código), `PersonaExecutor` (core/persona_executor.py, runner de tasks) e
`.jarvismodes` (5 modos YAML do REPL `jarvis dev`: code/architect/
nightwatch/organizer/research).

## Evidência (código, não opinião)

1. **Executor consome Registry** (`persona_executor.py:60,100`:
   `self.registry = PersonaRegistry()`, `select_for_task`) — camadas
   distintas e legítimas (identidade vs execução). NÃO duplicação.
2. **Sobreposição real Registry × jarvismodes**: `architect` e `research*`
   existem nos dois, com role text e tool lists autorados
   independentemente (`persona.py:119,249` vs `.jarvismodes:47,114`).
3. **Identidades empilhadas (bug)**: `/mode architect` faz append de
   `MODE: <roleDefinition>` sobre o system prompt que JÁ contém
   `PERSONA ATIVA: jarvis` do Registry (`dev.py:2198` vs `:2013`) —
   duas definições de papel, potencialmente conflitantes, num só prompt.
4. **Modo não persiste (bug)**: rebuilds de prompt (`/clear` :2055,
   pin :2119, etc.) reformatam só com `_persona_block()` — o extra do
   /mode evapora no próximo rebuild.

## Decisão proposta

- `PersonaRegistry` = identidade canônica (prompt + capabilities→tools).
- `PersonaExecutor` = camada de execução (inalterado).
- `.jarvismodes` = UX do REPL: mantém APENAS o específico de sessão
  interativa (output limits, regras de fluxo); roleDefinition/tool lists
  delegam ao Registry (modo vira alias + extras, nunca papel paralelo).
- Prompt assembly: modo ativo SUPRIME o bloco persona default (escolha
  explícita vence fallback) e o extra do modo participa de TODOS os
  rebuilds (estado `active_mode`, não mutação pontual de messages[0]).

## Por que BLOCKED e não implementado

A mudança altera comportamento visível do REPL (`jarvis dev`) e o
dev.py (2529 linhas) tem convergência planejada (`agent_loop.py`) ainda
não iniciada — patch pontual em 5 sites de format + threading de
`active_mode` é exatamente o micro-patch que a missão proíbe (§0.1).
Implementar junto da convergência do dev.py.

## Migração (quando desblocked)

1. `.jarvismodes`: cada modo ganha `persona: <registry-id>`; role/tool
   duplicados saem do YAML.
2. `dev.py`: `_select_persona(hint)` considera `active_mode.persona`;
   `_persona_block()` suprimido quando modo tem role própria; extra do
   modo entra no template (todos os rebuilds).
3. Testes: modo persiste após /clear; prompt contém UMA identidade.
