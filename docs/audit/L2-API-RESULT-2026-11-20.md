# Resultado L2 — braço api (5 amostras, 20/11)

## Execução

`lab-l2-plan` validou 5 gates (OK=5), loop iniciado diretamente (sem
`lab restart`, para não apagar lock/pid), `AB_LEVELS=L2 AB_MODELS=api`,
5 amostras com timeout de 900 s cada. Resumo:
`~/logs/ab_loop/l2-api-summary.json` — 5/5 amostras, 1119→1124 linhas,
modelos `api`, níveis `L2`, `ck=v3`, `rc=0`, controle final `pause`,
sem processos de dungeon e GPU devolvida.

| amostra | checker | patch_bytes | motivo | tasks no ciclo |
|---:|---|---:|---|---|
| 1 | 4 failed, 1 passed | 0 | checker | 1 |
| 2 | 4 failed, 1 passed | 0 | checker | 1 |
| 3 | 4 failed, 1 passed | 0 | checker | 1 |
| 4 | 4 failed, 1 passed | 0 | checker | 1 |
| 5 | 4 failed, 1 passed | 0 | review | 1 |

## Correção de interpretação

O plano original exigia `discovery_stats.returned>0`, mas esse campo conta
**tarefas novas descobertas no ciclo**, não trabalho executado. A fila
`task_queue-dungeon-api-l2.json` já tinha 1 tarefa `READY`
(`dungeon-ab-api-L2-1795187846`, projeto `dungeon-api-l2`), e os logs mostram
`tasks_completed=1` ou `tasks_failed=1` em todas as 5 amostras. Portanto
`returned=0` é esperado e **não invalida** as medições. O critério foi
corrigido em `docs/lab/L2-REMEASURE-PLAN-2026-11-20.md` e `scripts/lab-l2-plan`.

## Veredito

São 5 medições válidas no formato ck=v3/L2. O modelo `api` **não resolveu a
tarefa** nas 5: patch vazio e checker 4/5 falhando. Isso é resultado do modelo,
não falha de infra. Os 93 registros L2 antigos seguem suspeitos; estes 5
substituem apenas o braço `api` e faltam 5 para `bonsai` e 5 para `mtp`
para fechar a matriz.
