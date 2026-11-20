# Painel do ciclo de auto-melhoria (20/11)

Fonte única: artefatos duráveis (`--audit`, snapshots, idle trace, marcadores
do plugin, summaries do lab e LOG). Nada aqui é reexecutado para este painel.

## Precisão do refill

| métrica | valor |
|---|---|
| wakes desde o fix (`29f3d13`) | 16/10 |
| enqueues novos do gerador | 5/5 |
| executados até agora | 0/5 |
| precisão pós-correção | 0,0 (ainda não executados) |
| decisão | **KEEP_MAX_REMOTE_1** (gate 0,8) |
| precisão histórica (pré-fix) | 0,333 (1/3) |
| falsos positivos históricos | 2/3 (vago e stale), eliminados pelo validador |
| snapshots registrados | 11 |

Os 5 enqueues são gaps **reais** da auditoria de sync, versionados em
`ai-mesh/docs/auto-improve-gaps.jsonl` — não são tarefas sintéticas criadas
para inflar a métrica.

## Uptime do hook idle

- 51 eventos em 14 grupos; 9 sequências completas `peek→budget→wake`.
- 5 bloqueios de budget, todos dentro do gap mínimo de 180 s (43–172 s após
  wake anterior) — comportamento esperado, não falha.
- Hook registrado às 14:53Z; último wake às 16:10Z (~77 min sem stall).
- Total histórico de wakes sintéticos: 114.
- Fila atual: 8/9; budget 3/12 nesta hora.

## Laboratório A/B (ck=v3, L2)

| braço | amostras | status |
|---|---:|---|
| api | 5/5 | concluído: modelo falhou checker, patch vazio (não é infra) |
| bonsai | em curso | loop ativo, `--model bonsai --level L2` |
| mtp | pendente | inicia após bonsai |

Critério corrigido: `discovery_stats.returned=0` não invalida a amostra quando
a fila já tinha tarefa READY; a prova é `tasks_completed+tasks_failed>0`.

## Validação e dívida restante

- Suíte completa: **2117 passed / 27 skipped / 0 failed** (111,81 s, rc=0).
- RAG: `code_index` com 99.276 pontos removíveis (36%) em dry-run; falta
  `git_commit` no payload antes de qualquer `--apply`.
- Vault: 5 `AGENTS.md` stale (mt5, ai-mesh, cactus-needle, red-teaming,
  spiritvale-audit); `sync-vault.sh` já gera ponteiros, precisa reexecutar.
- Contratos: capability cards sem skills/scripts; Windows sem cartão canônico.
- Plugin: `consulta-obrigatoria.js` aponta direto ao repo; backup live sem par HM.

## Próximo limite útil

**Não é `MAX_REMOTE`.** O limite que trava valor agora é a **proveniência do
índice RAG** (`git_commit`/branch ausentes) e, em segundo, a reexecução do
`sync-vault.sh` para os 5 contratos stale. Só voltar a calibrar `MAX_REMOTE`
depois que as 5 tarefas de gaps reais forem executadas e a precisão passar de
0,8 com evidência no `--audit`.
