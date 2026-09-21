# PIVOT CONTRACT — PIVOT_AFTER_INVALIDATED_PLAN (Ciclo 5)

Precondições: plano em curso; tool disponível p/ alternativa; estado
preservado; falha observável (ERROR honesto, sem crash).
Falha observável: ERROR determinístico + STATE(world_unchanged/changed)
no 2º erro idêntico + deliverables ausentes cobrados.
Comportamento requerido do modelo: após evidência de invalidez, trocar
materialmente de estratégia (pivot_metrics: tool diferente), não repetir
nem desistir sem tentativa.
Evidência determinística: retry streak (mesma tool+args) vs pivot (troca);
world-delta (snapshot CWD); deliverables do prompt.
Sucesso: world state correto (world_check). Falhas: retry-3× (STUCK),
desistência, pivot incorreto (volta ao attractor), fidelidade.
Teste: `test_eval_harness.TestPivotMetrics` (métrica) + L9 runner
(comportamento, host). Métrica ≠ correção: pivot_rate alto com
world 0/12 (L9) prova que tentativa não é recuperação.
Status: PARTIAL (mecanismos implementados; world L9 segue 0/12).
Não-prescrição (§PHASE 12): o harness nunca diz QUAL alternativa; só
fatos (ERROR, world-delta, deliverables). Plano alternativo é do modelo.
