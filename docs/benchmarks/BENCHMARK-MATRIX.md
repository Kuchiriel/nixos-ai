# BENCHMARK MATRIX (20/09 — empírica, bonsai salvo menção)

| Dimensão | Baseline | Candidato | Evidência | Incerteza |
|---|---|---|---|---|
| RAG→behavior | C0 0/5 | C2 5/5 (+T2/T3 3/3) | EXP-A+R1 | replicado n=5, 3 docs |
| Retrieval negativa | — | C1 distrator 0/3 | EXP-A | 1 distrator só |
| Lesson→behavior | B0 4/5 | B2 valores 1/5; B3 value-free 3/3; L4 scoped 1/3; L5 rule 2/3 | EXP-C+R2 | números prejudicam confirmado |
| MCP seleção | E1-all falha | E2-only 9/9 | EXP-E2/D2 | entropia, não capacidade |
| Substrate selection | E1 0/6 | E2 6/6 | EXP-E2/D2 | read_file atrai |
| False-green resist. | stale passava | `stale_artifact:*` flag + crash honesto | 3 testes novos | outage≠nada |
| Config integrity | — | CANONICAL_CONTEXT fonte única | test_context_drift | pré-existente 18/09 |
| Retrieval quality | — | P/R/NDCG 11 queries | eval_rag --seed | não re-executado hoje |
| Latência por rota | — | metas ROUTE_CASES | benchmark.py | não re-executado hoje |
| Suite regressão | 1395/0 (19/09) | +2 testes harness | pytest | sandbox skip integration |

Próximas (não executadas): F context-ablation, G self-knowledge agente,
H two-loop (recon feito, sem experimento), J failure-injection, B memória
episódica pura (coberta parcial via lessons), I deep (2 casos feitos).
