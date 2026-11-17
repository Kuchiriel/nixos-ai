# Laboratório A/B (dungeon × modelos) — mapa e contrato

Tudo aqui roda no host `nitro-v15` (Linux). O celular (Termux) só **comanda**
por SSH; nenhum processo do laboratório roda no celular.

## Ponto de entrada único

```bash
scripts/lab.sh status          # estado: loop, nível, GPU, matriz, últimas
scripts/lab.sh status --json   # o mesmo, para máquina
scripts/lab.sh doctor          # RE-VALIDA o instrumento (checkers nos 2 sentidos)
scripts/lab.sh run             # roda agora (ciclo imediato)
scripts/lab.sh run L2          # roda agora no degrau L2
scripts/lab.sh level L1|L2|L3  # força o nível do próximo ciclo
scripts/lab.sh arm bonsai|mtp|api  # roda só um braço
scripts/lab.sh pause | resume | stop | restart
scripts/lab.sh logs 60
scripts/lab.sh gpu             # VRAM, quem ocupa, quem está no ar
```

Do celular: `lab status` (wrapper em `~/bin/lab`, mesma CLI).

## Arquivos e quem é canônico

| arquivo | papel | canônico em |
|---|---|---|
| `scripts/ab_loop.sh` | laço A/B: GPU por ciclo, escada, resultados | repo |
| `scripts/llm-swap.sh` | sobe/derruba braço; `takeover`/`release` da GPU | repo |
| `scripts/lab.sh` | ponto de entrada | repo |
| `scripts/restart-ab.sh` | reinício seguro (sem `pgrep` casar com o próprio shell) | repo |
| `scripts/dungeon-checker.py` | veredito L3 (pathfinding) | repo |
| `scripts/dungeon-checker-l1.py` | veredito L1 (método puro) | repo |
| `scripts/dungeon-checker-l2.py` | veredito L2 (desvio local) | repo |
| `scripts/prova_checkers.py` | valida os 3 checkers (referência deve passar, baseline falhar) | repo |
| `modules/ai/jarvis/src/nightwatch/dungeon.py` | tarefas, níveis, fila | repo |
| `modules/ai/jarvis/src/nightwatch/harness.py` | execução; fallback de arquivo inteiro | repo |
| `scripts/agent-hub.mjs` + `-ui.html` | mission control (porta 8091) | repo |
| `logs/ab_loop/results.jsonl` | histórico de medições | host (dado) |
| `~/.local/state/jarvis/nightwatch/ab_loop.control` | canal de comando do painel | host (runtime) |

## O contrato do veredito (não quebrar)

1. O checker é escrito **antes** e copiado para a lane com `444`; o agente não
   o vê nem o altera.
2. O checker **não** pode assumir nome de método: mede comportamento.
3. Todo checker tem um teste de **sanidade do fixture** (o cenário é possível?).
   Sem isso, um mapa impossível reprova todo mundo por horas — já aconteceu.
4. O checker é validado nos **dois sentidos**: solução de referência aprova
   100%, baseline reprova. `scripts/prova_checkers.py` faz isso.
5. Só conta medição com `"ck":"v3"` no `results.jsonl`. Linhas `v2` nasceram
   de um checker inválido e ficam como legado.

## Armadilhas já pagas (não repetir)

- **`checkpoint.py` tem fallback LEGADO.** Mesmo limpando
  `checkpoint-dungeon-<braço>.json`, ele lê o `checkpoint.json` global (um
  `fail-test` de 04/set) e reescreve como `dungeon-<braço>`: o run começa em
  `Recovering: This will fail` antes de qualquer task. Por isso o `ab_loop.sh`
  exporta **`JARVIS_STATE_DIR` próprio por braço** (`.../nightwatch/ab-<braço>`)
  e limpa só ali. Não volte a apontar o harness para o diretório de estado
  compartilhado.
- **Patch rejeitado pelo revisor não se perde: vai para o `git stash` da lane.**
  Quando o resultado vem `patch=0B` + `Review failed`, o diff do modelo está
  em `git -C ~/projects/dungeon-<braço> stash list` (`nightwatch-autosave-uncommitted`).
  Para saber se o revisor errou, copie a lane para `/tmp`, aplique o stash e
  rode o checker fixo: o veredito é do checker, não do revisor. (17/11: o
  stash do bonsai L2 só trocava `dx = 0; dy = 0` por `dx, dy = 0, 0` — o
  revisor estava certo e a falha era do modelo.)
- **`pgrep -f` casa com o próprio shell.** Use `pgrep -f 'scripts/ab_loop\.sh'`
  dentro de um arquivo, nunca na linha do SSH.
- **Crases na mensagem do `git commit -m`** são executadas pelo zsh remoto:
  use `git commit -F arquivo`.
- **O `:8092` é unit de SISTEMA** (`llama-uncensored-4b.service`), não o
  `duplex-voice.service` (user). `systemctl --user stop` não o derruba.
- **`jarvis-heal` (60 s)** ressuscita serviços parados: pausar antes.
- **`pkill -f "nix develop"`** mata o próprio shell remoto.
- **`rm -rf` em lane** é seguro (cópia do baseline), mas nunca aponte para
  `~/projects/jarvis-dungeon` (produção).
- **Node não existe no Termux**: valide `.mjs` só no host (`node --check`).

## Estado e próximos passos

Ver `docs/lab/HANDOFF.md` (atualizado a cada sessão; é o que um modelo novo lê
primeiro).
