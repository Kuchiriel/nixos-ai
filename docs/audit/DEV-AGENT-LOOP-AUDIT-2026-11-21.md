# Auditoria estrutural: `cli/dev.py` × `agent_loop.py` (21/11)

## Pergunta da tarefa

"Auditar `cli/dev.py` (4204 linhas) e propor convergência com `agent_loop.py`
conforme ADR-003."

## Evidência medida

| artefato | medição |
|---|---|
| `modules/ai/jarvis/src/jarvis/cli/dev.py` | 4205 linhas, 71 definições de topo; `dev_repl` em 3098, `dev_once` em 4017; loop interno `_run_agent_loop` |
| `archive/core/agent_loop.py` | 602 linhas, 3 classes (`ToolExecutor`, `ASTValidator`, `RealAgentLoop`); **arquivado** |
| git history de `agent_loop.py` | criado em `4a936a92` ("real agent loop"), arquivado em `88c34f68` ("archive 9 dead modules") |
| ADR-003 | `proposed` / `BLOCKED`; propunha usar `agent_loop.py` como alvo de convergência |
| ADR-005 | `ACCEPTED`; substitui ADR-005 na prática por `jarvis/runtime/AgentRuntime` |

Trecho literal de ADR-005: *"Substitui na prática ADR-003 (convergência dev.py,
bloqueada até reconstrução do loop)"* e *"Um único `AgentRuntime.run(task)`"*.

`tests/test_runtime_convergence.py` trava **3 loops cognitivos** conhecidos
(`core/agent.py`, `cli/dev.py`, `nightwatch/harness.py`), com target F8 de 1
loop no runtime; a suíte passa **31/31**.

## Veredito

**Não convergir para `agent_loop.py`.** Ele é protótipo arquivado, sem testes
de convergência e fora do caminho canônico; revivê-lo seria regressão
arquitetural e violaria ADR-005.

A parte **técnica** da ADR-003 continua válida e mensurável: o REPL empilha
identidades (`PERSONA ATIVA` do Registry + `MODE:` do `/mode`) e o extra do
modo evapora em rebuilds de prompt. Mas a correção deve morar no par
`AgentRuntime` + REPL fino, não no loop arquivado.

## Proposta de convergência (ADR-005, sem micro-patch)

1. Manter `archive/core/agent_loop.py` como evidência histórica; não remover.
2. F8: extrair o loop de `dev.py` para `AgentRuntime.run()` usando o linter
   estrutural como ratchet (3 → 2 → 1 loops); `dev.py` fica com sessão,
   compaction, checkers, catálogo e approval, conforme ADR-005 §2/§8.
3. Depois da extração: aplicar a decisão de persona da ADR-003 dentro do REPL
   fino — modo vira alias + extras, uma única identidade no prompt,
   `active_mode` sobrevive a `/clear`.
4. Critérios objetivos: `test_runtime_convergence.py` com 1 loop, testes de
   modo persistente e prompt com uma só identidade; suíte de runtime verde.

## Mudança aplicada nesta auditoria

Atualizei apenas o status de `ADR-003` para `superseded` (com ponteiro para
ADR-005), preservando todo o texto original. **Nenhuma linha de `dev.py` foi
alterada** — a ADR-003 proíbe micro-patches antes da convergência, e a decisão
de produto permanece pendente.
