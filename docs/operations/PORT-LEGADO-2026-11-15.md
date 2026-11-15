# PORT: legado → sistema novo (15/11, com os insights do transcript)

> O dono: *"é pra portar/mesclar/melhorar isso no sistema novo com os insights
> das transcrições"*. O legado (`~/projects/team/`) tinha personas, fila com
> dono, handoff em arquivo, handover bot-a-bot e reports. O sistema novo tem
> tudo isso **e mais** — mas tinha perdido as **regras de condução por papel**
> (`roles/*.md`: Pode ver / Não pode / Entrega / Handoff).

## Os 4 insights do transcript (Codacus, "Is this how Local AI reaches Frontier Capabilities?")

| insight (medido no vídeo) | o que foi feito na casa |
|---|---|
| *"My experts only saw what the planner wrote; they never saw my original request"* — o time passou **menos de 3 de 8** checks, o especialista sozinho passou **6 de 8** | o wake anexa `[PEDIDO ORIGINAL (contexto do remetente)]` (a `task` do roster de quem manda). **Prova**: o Falcão respondeu *"sim, vi o PEDIDO ORIGINAL acima"* |
| **o planejador é o elo fraco**, não o especialista (4B planejador 2/4 · 35B planejador 4/4) | regra nova: quem delega tem de ter modelo forte; `HarnessConfig` saiu do **MoE 35B morto (:8084)** para o **MTP vivo (:8092)** |
| *"a model can be almost perfect on one step and still fail a long task"* (terminal-bench 85% vs 27%) | **job curto → especialista pequeno; job longo → modelo grande** (regra no AGENTS.md) |
| *"don't touch production — copy to a sandbox, fix it there, then hand me a script"* + checker de 4 pontos | o dungeon roda em **worktree por lane** (produção intacta) e o **checker é fixado antes**: `pytest test_astar.py` → 4 passed |

## O mapa do port (legado → novo)

| peça do legado | onde estava | onde está no sistema novo | insight aplicado |
|---|---|---|---|
| **playbook do papel** (`roles/{dev,auditor,researcher}.md`) | `~/projects/team/roles/` | `jarvis/playbooks/*.md` + `jarvis/core/playbook.py`; anexado no **spawn** (prompt inicial) e no **wake** (payload) | "o especialista precisa ver o pedido original **e as regras do papel**" |
| **persona + MBTI + lane** | `bots/*.md` | roster (`coord_roster`) + `agent-spawn` (classify → persona) | o plano forte é o do modelo forte |
| **fila com dono** ("nobody is the router") | `queue.md` | `nightwatch/task_queue.TaskQueue` (priority, dependências, attempts, evidence, commit_sha) | dependências explícitas (o plano de 5 etapas) |
| **handoff em arquivo** (create/claim/complete, sem daemon) | `handoff.sh` → `handoffs/<id>.md` | vault (`HANDOFF-<era>.md`) + bus (issue) + `send_message` | o pedido original viaja no handoff |
| **handover bot-a-bot** (sem dono no meio) | protocolo da fila | fila do sistema + painel (quem pega a próxima `@any`) | — |
| **report por tarefa** | `reports/*.md` | a **própria fila** (status + `last_validation` + `evidence` + `commit_sha`) | o checker fixado vira o veredito |
| **kanban / visão grok-bot** | não existia | **painel novo** (`agent-hub.mjs`): `/api/state`, `/api/transcript`, `/api/dungeon-ab` | — |

## O que foi implementado hoje (verificado)

1. **Playbooks portados** (3 papéis, verbatim do legado + cabeçalho de origem)
   em `modules/ai/jarvis/src/jarvis/playbooks/`.
2. **Loader** `jarvis/core/playbook.py`: `playbook_for_kind()` (tipo de tarefa)
   e `playbook_for_agent()` (lane/contexto do agente).
3. **Spawn**: o `system_prompt()` já nasce com `--- PLAYBOOK DO PAPEL ---`.
4. **Wake**: o payload do par é `[PLAYBOOK DO PAPEL]` + `[PEDIDO ORIGINAL]` +
   `[TAREFA]`. **Prova real**: o Falcão respondeu *"SIM — 'Não corrigir o que
   achou (quem corrige é o dev via handoff)'"* (citou a seção "Não pode").
5. **A/B do dungeon dentro do sistema** (`nightwatch/dungeon.py`): fila +
   sandbox (worktree) + checker fixado + Harness do próprio nightwatch; o
   painel dispara (`/api/dungeon-ab`). O script solto foi removido.

## O que ainda falta (fila)

- **Handover bot-a-bot**: a regra "quem termina enfileira a próxima `@any`"
  dentro da fila do sistema (hoje o `get_next_task()` é por prioridade).
- **Kanban no painel**: colunas da fila por status (o painel mostra o A/B,
  mas não a fila geral por papel).
- **Relatório por papel**: o `evidence` da fila não vira ainda um `reports/*.md`
  no formato do legado.
- **Hot swap**: `maxResident=1` no registry (6 GB de VRAM, MTP ocupa 5,5 GB) →
  o TMax/VibeThinker exigem **trocar o residente em idle**; existe
  `scripts/agents-reload.sh` (hot reload de plugin/config), falta o
  `llama-swap`.
