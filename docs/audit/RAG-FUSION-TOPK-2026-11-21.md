# Investigação do top-k da fusão híbrida (21/11)

## Pergunta

`TECHNICAL-DEBT.md` (linha 15, blame `2d52584d`, 19/11) dizia "RAG recall da
fusão híbrida: 1/5 known-answer hits; investigar top-k da fusão". O número foi
medido com o harness anterior, antes de `b907a442` ("cross-encoder volta a
mandar na ordenação final").

## Reprodução atual

`nix develop --command python3 scripts/rag-eval.py --top-k 8`:

| modo | recall@8 | MRR |
|---|---:|---:|
| rerank off | 0,93 (13/14) | 0,667 |
| rerank on | 0,93 (13/14) | 0,762 |

A única pergunta sem acerto é "how many characters per chunk does the code
indexer use" (`expect: core/rag.py`). A resposta existe em `rag.py:792`
(`chunk_size = 1200`) e o arquivo está indexado em `code_index`.

## A/B de parâmetros (somente leitura, sem escrita em Qdrant)

1. **Profundidade da fusão**: o `HybridSearch.search` passa `top_k*4` como
   limite final do RRF; o prefetch já traz `dense_limit=50`/`sparse_limit=50`
   por retriever. Multiplicadores 4/6/8/10 mantiveram recall 0,929 e MRR
   0,667 em todos os valores (latência 21–38 ms/consulta). Com `top_k=64`,
   o documento aparece no rank 33 — ou seja, não está fora do pool, está
   mal ranqueado.
2. **Peso RRF e sparse**: `dense_weight` 1/2/3/5 × `sparse_limit` 50/150/300.
   Nenhuma combinação recuperou o acerto sem regredir MRR; a configuração
   atual (`dense_weight=5`, `sparse_limit=50`) foi a de maior MRR (0,667).

Conclusão: **não é problema de top-k nem de peso RRF**. É um caso de
relevância (o chunk de `rag.py` que contém `chunk_size` não sobe no ranking).
Aumentar limites só aumentaria latência; mudar pesos pioraria as outras 13
perguntas. Nenhuma mudança de ranking foi aplicada.

## Melhoria permanente aplicada

`scripts/rag-eval.py --min-recall F` transforma o harness em gate de
regressão: sai 2 se qualquer modo ficar abaixo de F. Validado com F=0,9
(rc=0) e F=0,95 (rc=2). Isso impede que o recall volte a 1/5 sem ser notado.

Estado da dívida: **reclassificada** — o 1/5 é stale; o alvo atual é manter
>=0,9 com o gate; o 1 erro restante é dívida de relevância, documentada.
