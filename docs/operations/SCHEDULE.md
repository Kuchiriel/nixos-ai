# SCHEDULE — inventário único de timers e jobs de fundo

> Levantado em 12/11/2026 com `systemctl list-timers --all` (user e system),
> conferido contra `rg OnCalendar` no repo. Este arquivo é a **fonte única**:
> timer novo entra aqui na mesma mudança que o cria, senão não existe.
> Regra do dono (12/11): "evitar duplicações, consolidar coisas semelhantes".

## Por que existe ordem e por que ela se perdeu

Os timers nasceram em ondas: harness do JARVIS (user), auditorias noturnas
(system), jobs de outros repos (loose files). Nada disso era inventariado,
então: (a) unit de outro projeto aparecia como falha do nixos-ai, (b) dois
jobs pesados podiam coincidir, (c) unit solto em `~/.config/systemd/user/`
sobrevivia a rebuild e ninguém via.

## Consolidação: "team-suite" (personas/coord/kanban/telegram) — 12/11

O antigo `team-suite` (timer 03:30, unit solto, jogo de teste "dungeon")
foi substituído. O sistema vivo hoje é **um só**, no nixos-ai:

| Peça antiga (legado, `~/projects/team/`) | Equivalente vivo hoje |
|---|---|
| bots shell + `queue.md` (kanban markdown) + `MEMORY.md` | bus do coord + `AGENTS-QUEUE.md` + memórias/RAG |
| `suite-bot.sh` / `drift-bot.sh` / `coord.sh` por timer | `night-comms` (00:00, lê bus, entrega pendências) + `agents-watcher.sh`/`agent-api.py` (acorda por API) + `agent-keepalive.sh` |
| `tg.sh` / bot tokens por persona em `/etc/jarvis-team-bots.env` | Telegram do JARVIS + `night-comms` avisa o dono |
| personas/roles em `team/roles/` | `jarvis/core/team.py` (escolha de personalidade/modelo/agente por tarefa) + `coord_http.py`/MCP `jarvis_coord_*` (roster, workitems, mensagens) |

Os scripts de `~/projects/team/` permanecem no lugar (legado, não deletado).
O que rodava por timer solto (`team-coord`, `drift-bot`, `team-suite`) foi
**desabilitado e movido para quarentena** (reversível) em
`~/.local/state/jarvis/legacy-units-2026-11-12/`. O symlink fantasma
`timers.target.wants/team-suite.timer` foi removido. Regra: fila única é o
bus (`AGENTS-QUEUE.md`/coord), sem kanban paralelo.

## User timers (10) — estado atual

| Timer | Quando | O que faz | Veredito |
|---|---|---|---|
| `night-comms` | 00:00 | lê o bus, entrega pendências por nota, avisa Telegram | MANTER (barato, 1x/dia) |
| `jarvis-sessions-index` | ~30 min | indexa sessões opencode no RAG + consolida memórias de sessão (incremental) | MANTER (pipeline de memória) |
| `jarvis-idle-worker` | 5 min | self-knowledge quando o sistema está ocioso | MANTER (só age em idle) |
| `session-snapshot` | 5 min | `restore-sessions.sh --capture` (layout das janelas) | MANTER (5 min: ~288 escritas/dia; 12/11: 1 min era excessivo para layout que muda pouco) |
| `git-sync-obsidian` | 15 min | commit/push do vault Obsidian | MANTER |
| `rclone-sync` | a cada 4 h | backup do `~/projects` para o Drive | **BLOQUEADO**: OAuth sem escopo de escrita (403). Ação do dono: `rclone config reconnect gdrive` |
| `bench-qwen` | 04:00 | bench noturno do default (4B-MTP+LoRA, :8092) | MANTER (janela noturna) |
| `swap-probe` | 06:00 | reinicia o default se não responder | MANTER (12/11: 06:00 + `ExecCondition` para não rodar se `bench-qwen.service` ativo, evita colisão GPU/LLM) |
| `systemd-tmpfiles-clean` | 12 h | limpeza padrão do systemd | padrão, não é nosso |

Removidos/desligados em 12/11: `team-suite` (fantasma), `team-coord` (standup
do time legado, loose), `drift-bot` (loose, acoplado ao canary), e
`guia-checa-respostas` (loose, repo guia-renamer-pro, estava failed). Os 3
últimos ficam em quarentena para reativação explícita no repo dono se fizer
sentido.

## System timers (6)

| Timer | Quando | O que faz | Veredito |
|---|---|---|---|
| `audiobook-audit` | 01:00 | roda `applio-lab/scripts/nightly-audit.sh` (outro repo) | **COUPLING**: job de outro projeto agendado por módulo do nixos-ai. Mover para o repo dono |
| `jarvis-consolidate` | 03:00 | `jarvis-reflect.py` + `jarvis consolidate --apply` | MANTER. Dívida: usa o **venv do karaok** como interpretador (funciona; trocar exige provar que o env do pacote tem as deps) |
| `logrotate` | 11:00 | rotação padrão | padrão |
| `nh-clean` | seg 00:00 | limpeza do store (nh) | MANTER |
| `fstrim` | seg 01:00 | TRIM semanal | padrão |
| `systemd-tmpfiles-clean` | 12 h | limpeza padrão | padrão |

## Sobreposições reais (não são duplicatas exatas)

1. **Memória**: `jarvis-sessions-index` (a cada 30 min, incremental, escopo
   sessões) e `jarvis-consolidate` (diário, escopo episódico, dedup por
   embedding). Ambos "consolidam"; antes de fundir, medir quantos clusters
   cada um remove — se o incremental já remove tudo, o noturno é redundante.
2. **GPU/LLM à noite**: `bench-qwen` (04:00, ocupa a GPU) e `swap-probe`
   (06:00, reinicia o service se necessário). Regra da casa: **um job pesado por vez**.
   Correção aplicada em 12/11: probe às 06:00 com `ExecCondition` que pula se
   `bench-qwen.service` ainda estiver ativo.
3. **03:00**: `jarvis-consolidate` (system) e `nightwatch` (módulo existe,
   desligado). Se o nightwatch voltar, colide no mesmo minuto.

## Units soltos em `~/.config/systemd/user/` (não declarativos)

Sobrevivem a rebuild, não aparecem no flake, ninguém audita. Depois da
quarentena de 12/11 restam:

| Unit | Origem | Veredito |
|---|---|---|
| `chisel-client.service` / `chisel-tunnel.service` | túnel (auditoria/manutenção) | declarar no módulo dono ou remover |
| `dono-gate-ivan.service` | gate local de push Kaggle (applio-lab) | declarar ou remover |
| `llama-wackmall.service` | experimento/profiling | remover se não usar |

## Regras (para não voltar a bagunçar)

1. **Timer só existe se estiver nesta tabela.** A mudança que cria o timer
   cria a linha.
2. **Job de outro repo mora no repo dono.** O nixos-ai agenda o que é do
   nixos-ai; `guia`, `team`, `applio-lab` e `canary-official` carregam os seus.
   Foi o que fizemos em 12/11 com `sandbox-verificacao` e `xref-watch`
   (comando fica, timer desligado por padrão).
3. **Nada de unit solto** em `~/.config/systemd/user/`: ou é `home.file`/
   `systemd.user.*` declarado, ou não existe.
4. **Um job pesado por vez** (GPU/VRAM/RAM). Se dois precisam da GPU, o
   segundo depende do primeiro (`After=`/`ExecCondition`), não só do horário.
5. **Job que falha sem ninguém ver não é job**: todo timer que pode falhar
   publica no canal do time ou no bus.
