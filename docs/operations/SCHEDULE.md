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

## User timers (12)

| Timer | Quando | O que faz | Veredito |
|---|---|---|---|
| `night-comms` | 00:00 | lê o bus, entrega pendências por nota, avisa Telegram | MANTER (barato, 1x/dia) |
| `jarvis-sessions-index` | ~30 min | indexa sessões opencode no RAG + consolida memórias de sessão (incremental) | MANTER (é o pipeline de memória) |
| `jarvis-idle-worker` | 5 min | self-knowledge quando o sistema está ocioso | MANTER (só age em idle) |
| `session-snapshot` | 1 min | `restore-sessions.sh --capture` (layout das janelas) | MANTER, **candidato a 5 min** (1440 escritas/dia para um layout que muda pouco) |
| `git-sync-obsidian` | 15 min | commit/push do vault Obsidian | MANTER |
| `rclone-sync` | a cada 4 h | backup do `~/projects` para o Drive | **BLOQUEADO**: OAuth sem escopo de escrita (403). Ação do dono: `rclone config reconnect gdrive` |
| `bench-qwen` | 04:00 | bench noturno do default (4B-MTP+LoRA, :8092) | MANTER (janela noturna) — ver colisão abaixo |
| `swap-probe` | 05:00 | reinicia o default se não responder | MANTER, mas **1 h depois do bench**: se o bench atrasar, o probe reinicia o service no meio |
| `drift-bot` | dom 05:00 | `team/drift-bot.sh` | **MOVER** para o repo `team` (hoje é unit solto) |
| `guia-checa-respostas` | 18:30 | vigia respostas de leads no Gmail (repo guia-renamer-pro) | **MOVER** para o repo dono; hoje é unit solto e está **failed** |
| `team-suite` | — | **fantasma**: sem unit file, sem service, sem próximo disparo | REMOVIDO |
| `systemd-tmpfiles-clean` | 12 h | limpeza padrão do systemd | padrão, não é nosso |

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
   (05:00, reinicia o service). Regra da casa: **um job pesado por vez**.
   Se o bench passar de 1 h, o probe interfere. Correção mínima sugerida:
   probe às 06:00, ou `ExecCondition` checando `systemctl is-active bench-qwen`.
3. **03:00**: `jarvis-consolidate` (system) e `nightwatch` (módulo existe,
   desligado). Se o nightwatch voltar, colide no mesmo minuto.

## Units soltos em `~/.config/systemd/user/` (não declarativos)

Sobrevivem a rebuild, não aparecem no flake, ninguém audita:

| Unit | Origem | Veredito |
|---|---|---|
| `chisel-client.service` / `chisel-tunnel.service` | túnel | declarar no módulo dono ou remover |
| `dono-gate-ivan.service` | gate local | declarar ou remover |
| `drift-bot.service` + `.timer` | repo `team` | mover para o repo `team` |
| `guia-checa-respostas.service` + `.timer` | repo `guia-renamer-pro` | mover para o repo dono (está failed) |
| `llama-wackmall.service` | experimento | remover se não usar |

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
