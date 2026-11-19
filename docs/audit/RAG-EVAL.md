# RAG-EVAL — avaliação de recuperação (medido 19/11)

> Este doc resolve a referência pendente em `core/rag.py:1111`
> ("ver RAG-EVAL no docs/audit"). Nenhum documento existia.

## 1. Metodologia
Perguntas com resposta conhecida em documentos reais do repo,
`top_k=10`, `collection=code`, via `HybridSearch` com `PYTHONPATH` do repo
(o CLI `jarvis rag` usa o wrapper do Nix store e não reflete mudanças locais).

## 2. Achados medidos
| medição | resultado |
|---|---|
| `rag_retrieval_test.py` (5 perguntas, antes do fix) | **1/5** no top-8 |
| `check_rag_indexed.py` (4 docs esperados) | **4/4 indexados** — não é cobertura |
| `test_boost.py` (`apply_legacy_boosts`) | CYCLE-9 → 100005, 1º — boosts OK |
| `rag_phrasing_probe.py` (antes) | "CYCLE-9" #1; "CYCLE-9 Harbor" fora do top-10 |
| `rag_direct_rank.py` (depois de `de1cbf66`, `use_rerank=False`) | **4/4 frases no top-4** |
| `test_rag_identifier.py` | 3/3 |

## 3. Causa raiz
Tokens adicionais à query diluem o **embedding denso**. O ID forte do
documento (ex.: `CYCLE-9`) sozinho recupera bem; acrescentar "Harbor"
desloca o vetor. Sparse/RRF/boosts estavam corretos.

## 4. Correção
`strong_query_identifier()` (`core/rag.py`) detecta IDs fortes
(`[A-Z]+-digitos` ou arXiv `NN.NNNNN`) e constrói o dense vector apenas
com o ID. Sparse/RRF/boosts continuam usando a query completa.
Commit `de1cbf66`.

## 5. Reranking
`rag.py:1111` registra que subir o rerank de 5 para 8 piorou o acerto de
3/5 para 0/5 no k=8 — o cross-encoder com 350 chars/doc desordena mais do
que ajuda. Mantido em 5. **Não alterar sem novo A/B**.

## 6. Rerank ON (medido depois do fix)
`rag_rerank_test.py` com `use_rerank=True`, 5 perguntas: **2/5** hits
(CYCLE-9 e ADR-004 no rank 1; ADR-003/ARCHITECTURE-FINDINGS/RUNTIME-FORENSICS
fora do top-8). Antes do fix eram 1/5 — melhora, mas **abaixo do gate ≥4/5**.
Causa provável: o cross-encoder com 350 chars/doc desordena documentos
longos (já observado em `rag.py:1111` para k=8). Próximo: aumentar o trecho
de documento fornecido ao reranker ou desligá-lo quando houver ID forte.
NÃO alterar o rerank sem novo A/B.
