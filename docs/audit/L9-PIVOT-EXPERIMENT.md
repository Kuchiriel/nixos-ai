# L9-PIVOT-EXPERIMENT (Ciclo 5 — PHASE 4)

Condições (mesma task/mundo/avaliador; só observação/superfície mudam):
- L9-A baseline (sem world-delta, sem exec): 0/9. Sem arquivos (dead-end
  por construção do runner — evaluator defeituoso, corrigido).
- L9-B (+world-delta no 2º erro): pivot_rate 0.67→0.83 ≈ baseline
  (sem movimento mensurável); world 0/3.
- L9-D (+exec parity): arquivos aparecem; world 0/3 (fidelidade).
- Métrica pivot_metrics (retry=mesma tool seguida; pivot=troca):
  unit-testada; L9 mostra pivot_rate alto com world 0 → tentativa ≠
  recuperação (corretude exige mundo).
- Intervenções no ciclo: tool-honesty ERROR (comportamentalmente
  validada), deliverables .json/.txt (51 testes), world-delta,
  no-crash dispatch (StopIteration real pego com traceback!),
  shebang-split defensivo.
- Atribuição final: HARNESS melhorou (falhas legíveis, sem vácuo, sem
  crash conhecido); MODEL trava em serialização Python-repr,
  fidelidade de evidência, aplicação de regra sob variância, no-pivot
  persistente em 1/3 dos runs. L9 = MODEL-LIMITED no estado atual,
  com harness esgotado no observável (resta: crash tardio IndexError).
