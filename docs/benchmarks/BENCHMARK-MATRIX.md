# BENCHMARK MATRIX (20/09 — empírica, bonsai salvo menção)

| Dimensão | Baseline | Candidato | Evidência | Incerteza |
|---|---|---|---|---|
| RAG→behavior | C0 0/3 (alucina) | C2 chunk-alvo 3/3 | EXP-A jsonl | n=3; retrieval-hit simulado |
| Retrieval negativa | — | C1 distrator 0/3 | EXP-A | 1 distrator só |
| Lesson→behavior | B0 3/3 | B2 c/ números 1/3; B3 value-free 3/3 | EXP-C jsonl | variante-dependente |
| MCP seleção | 12/18 | confusão recall→lessons 0/3; nix 0/3 | EXP-E json | probe-form, não chain completa |
| Substrate selection | 12/18 | vault 0/3; git 0/3→read_file | EXP-D json | 1 task ambígua (vault) |
| False-green resist. | stale passava | `stale_artifact:*` flag | 2 testes novos | não-bloqueante por desenho |
| Config integrity | — | CANONICAL_CONTEXT fonte única | test_context_drift | pré-existente 18/09 |
| Retrieval quality | — | P/R/NDCG 11 queries | eval_rag --seed | não re-executado hoje |
| Latência por rota | — | metas ROUTE_CASES | benchmark.py | não re-executado hoje |
| Suite regressão | 1395/0 (19/09) | +2 testes harness | pytest | sandbox skip integration |

Próximas (não executadas): F context-ablation, G self-knowledge agente,
H two-loop (recon feito, sem experimento), J failure-injection, B memória
episódica pura (coberta parcial via lessons), I deep (2 casos feitos).
