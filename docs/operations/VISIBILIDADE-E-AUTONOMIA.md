# Visibilidade e Autonomia (nightwatch, coord noturna, mission control)

> Atualizado em 2026-11-12. Objetivo: responder "o que roda de noite?", "para onde vão os dados?" e "o que melhorou de fato?" sem adivinhar.

## 1. Mapa rápido: coisas diferentes, nomes parecidos

| Peça | O que faz | Quando roda | Usa LLM/GPU? | Onde escreve | Como ver "o que mudou" |
|---|---|---|---|---|---|
| **night-comms** ("coord noturna" de comunicação) | Lê o bus de coordenação, entrega pendências aos agentes como NOTA (`noReply`, não acorda o modelo) e envia resumo ao Telegram | Timer user `night-comms.timer` 00:00 (ativo) | Não (zero token) | `~/.local/state/jarvis/night-comms.jsonl` (1 linha por passada), mensagem no Telegram (se configurado), notas nas sessões dos agentes | `tail -n 5 ~/.local/state/jarvis/night-comms.jsonl`; `journalctl --user -u night-comms.service -n 120 --no-pager`; `/board` no Telegram |
| **agents-watcher** | Watcher contínuo: acorda agentes ociosos quando há trabalho/pendências no bus, faz keepalive/checkpoint hints | Serviço user sempre ativo (`agents-watcher.service`) | Indiretamente (pode acordar agentes) | Journal do serviço | `systemctl --user status agents-watcher.service`; `journalctl --user -u agents-watcher.service -n 80 --no-pager` |
| **nightwatch** (harness autônomo de código) | Executa tarefas da fila (LLM), edita/valida em branch isolada, checkpoint/review, pode reportar no Telegram | CLI `jarvis nightwatch ...` ou timer `nightwatch.timer` (sistema; opt-in no módulo NixOS reescrito, ainda depende da config deployada) / scripts overnight | Sim (LLM; competir com GPU é risco) | `~/.local/state/jarvis/nightwatch/` (`progress.jsonl`, `checkpoint-*.json`, `task_queue-*.json`, `mission_state-*.json`, backups/evidence), journal do serviço, branches/commits `nightwatch/*` quando houver | `tail -n 20 ~/.local/state/jarvis/nightwatch/progress.jsonl`; `ls ~/.local/state/jarvis/nightwatch/`; `jq -r '.event_type,.task_id,.reason'` nos eventos; `git branch --list 'nightwatch/*'`; `journalctl -u nightwatch.service -n 200 --no-pager` |
| **overnight-loop / loop-close** (fechar o laço por medida) | Mede bateria (pré) → nightwatch/MoE patcha → re-mede → gate (reverte se regredir). Foco: melhoria mensurável, não só rodar | Manual/script (`scripts/overnight-loop.sh`, `scripts/loop-close.py`) | Sim | Relatórios em `/tmp/opencode/overnight-*.md` e `/tmp/opencode/loop-pre|post-*.json` (efêmeros em `/tmp`) | Ler o `overnight-*.md` (PRE/POST + gate + commits mantidos/revertidos); comparar JSONs pré/pós |
| **jarvis-consolidate / session-snapshot / rag-index** | Consolidação/memória, snapshots, indexação | Timers user/sistema conforme agenda | Parcial | `~/.local/state/jarvis/`, vault/RAG/Qdrant | Logs/journals dos serviços e estado em `~/.local/state/jarvis/` |
| **Mission Control (WebUI)** | Visibilidade/interação: dashboard de tarefas, serviços, chat, MCP | Serviços sistema `jarvis-webui.service` (FastAPI, :8090) e `jarvis-webui-frontend.service` (SvelteKit preview, :5173), quando habilitados e ativos | Backend pode chamar LLM conforme uso | Estado do JARVIS (tasks/memória/vault) lido pelo backend | `systemctl status jarvis-webui.service jarvis-webui-frontend.service`; abrir `http://127.0.0.1:5173/` (frontend) / `http://127.0.0.1:8090/` (API) localmente |

**Resumo:** `night-comms` = comunicação/visibilidade de pendências (barato). `nightwatch` = trabalho autônomo de código (caro, precisa de fila/tarefa clara e evidência). Eles não são a mesma coisa; `night-comms` ajuda a saber o que ficou pendente, `nightwatch` só "melhora" algo se tiver tasks e conseguir aplicar/validar mudanças.

## 2. "O que melhorou de fato?" (evidência, não impressão)

- **Nightwatch melhorou algo** quando: há entrada em `progress.jsonl` com tarefa concluída/validada, diff/commit em branch `nightwatch/*` ou merge, e validação/teste registrado. Sem isso, "rodou" não significa "melhorou".
- **Overnight-loop melhorou algo** quando: o relatório `overnight-*.md` mostra gate `MELHOROU` (ou manteve com commits úteis) e os JSONs pré/pós confirmam métrica melhor. Gate `REGREDIU` reverte e descarta patches: isso é sucesso do guardrail, não melhora de produto.
- **Night-comms cumpriu o papel** quando: há linha nova no `night-comms.jsonl` e o resumo chegou (Telegram/log) com pendências entregues. Não altera código.
- **Pendências reais (bus)**: `agents-watcher` + bus mostram o que está esperando ação; `night-comms` só entrega o digest da madrugada.

Checklist rápido de evidência:
```bash
# coord noturna (comunicação)
tail -n 3 ~/.local/state/jarvis/night-comms.jsonl

# nightwatch (autonomia de código)
tail -n 30 ~/.local/state/jarvis/nightwatch/progress.jsonl
git -C ~/projects/nixos-ai branch --list 'nightwatch/*' | head
find ~/.local/state/jarvis/nightwatch -maxdepth 1 -type f | sort

# loop medido (se rodou)
ls -lt /tmp/opencode/overnight-*.md /tmp/opencode/loop-*.json 2>/dev/null | head

# timers/serviços
systemctl --user list-timers --all --no-pager | head -20
systemctl list-timers --all --no-pager | head -20
systemctl --user status night-comms.timer agents-watcher.service --no-pager
systemctl status nightwatch.timer jarvis-webui.service jarvis-webui-frontend.service --no-pager
```

## 3. Por que parece invisível

- Saídas ficam em lugares diferentes (`~/.local/state/jarvis/*`, journal, `/tmp/opencode`, Telegram, branches git) e nada agrega num único painel confiável.
- Nightwatch pode rodar sem tarefas úteis na fila, falhar por falta de LLM/config, ou ser bloqueado por guardas: sem olhar `progress.jsonl`/journal parece que "nada aconteceu".
- Relatórios de overnight-loop em `/tmp` são efêmeros (somem em reboot/limpeza).
- Mission Control existe no código, mas depende de serviços ativos e build/preview do frontend saudável.

## 4. Mission Control (WebUI SvelteKit) — estado e diagnóstico

- Código: `modules/ai/jarvis/src/jarvis/webui/` (backend FastAPI em `server.py`/`api.py`, frontend SvelteKit em `webui/frontend/`).
- Serviços NixOS: `jarvis-webui.service` (porta 8090) e `jarvis-webui-frontend.service` (porta 5173, `npm run preview`).
- Sintomas comuns: serviços parados; preview sem `build/` de produção; backend sem acesso ao estado esperado; portas não expostas como o usuário imagina (bind local).
- Verificação: `systemctl status jarvis-webui.service jarvis-webui-frontend.service`; checar se existe `modules/ai/jarvis/src/jarvis/webui/frontend/build/`; testar `curl -sS http://127.0.0.1:8090/` e `http://127.0.0.1:5173/`.
- Correção típica local (sem rebuild): `cd modules/ai/jarvis/src/jarvis/webui/frontend && npm run build`, depois reiniciar serviços (requer privilégio/config conforme host).

## 5. "Missão do jogo" (o que é, pelo que consta)

- O `night-comms.nix`/script registram que o slot noturno substituiu o legado `team-suite.timer` (unit solto em `~/.config/systemd/user`, fora do Nix) que rodava bots do `team/` no "projeto de teste de jogo" (dungeon) — exercício de time de bots, migrado em 07/11 para comunicação.
- Evidência no repo: diretórios/artefatos como `team/`, `team/reports/*dungeon*.md`, `jarvis-dungeon/` existem. Isso indica que o jogo/teste de dungeon foi criado/exercitado naquele contexto; ele não é o Mission Control de visibilidade.
- Se "missão do jogo" significar outra missão específica (ex.: validar o Mission Control com um jogo/cenário), isso precisa estar descrito em uma issue/queue/doc específica para ser rastreável; hoje não há evidência inequívoca além do contexto acima.

## 6. Melhorias de visibilidade recomendadas (baixo risco)

1. Manter este documento como referência única de "onde olhar" e atualizar quando timers/paths mudarem.
2. Persistir resumos de overnight-loop fora de `/tmp` (ex.: `~/.local/state/jarvis/overnight-reports/` ou `docs/benchmarks/...`) para sobreviver a reboot.
3. Fazer nightwatch sempre emitir um resumo final (Telegram + arquivo) com: tasks tentadas, aprovadas/revertidas, motivo de bloqueio, links/paths de evidência.
4. Mission Control: garantir build do frontend no deploy, healthcheck e página inicial mostrando últimas execuções (night-comms/nightwatch/progress) lendo os mesmos arquivos de estado.
5. Habilitar nightwatch só com fila/escopo claro, janela sem disputa de GPU e orçamento; caso contrário ele "roda no escuro" ou não roda.

## 7. Nightwatch: estado de deploy (atenção)

- O módulo `modules/services/nightwatch-timer.nix` neste repo foi reescrito como opt-in/configurável (default `enable=false`, janela 03:30, guardas). **Isso só vale após rebuild/switch do host que consome o módulo.**
- No sistema observado, existe `nightwatch.timer/service` carregado de `/etc/systemd/system/` (timer ativo). Conclusão: a unidade em produção pode diferir do módulo local até o deploy; confirme com `systemctl cat nightwatch.service nightwatch.timer` antes de assumir o comportamento.
