# Erro de relevância restante: `chunk_size` ranqueado 33º (21/11)

## Reprodução e causa raiz

A única pergunta que ainda falhava (`how many characters per chunk does the
code indexer use`, alvo `core/rag.py`) tem a resposta em `rag.py:792`
(`chunk_size = 1200`). O arquivo está indexado.

A/B em `jarvis_test_relevance` (2250 pontos reais copiados de `code_index`,
incluindo os 14 alvos da fixture e os distractores reais da pergunta) mostrou:

1. Com `top_k=8`, o RRF devolve só `top_k*4=32` candidatos finais. Mesmo com
   `dense_limit/sparse_limit=2000`, o chunk correto aparece por volta do
   **rank 95** — portanto nenhum boost aplicado *depois* da fusão pode trazê-lo
   para o top-8 quando o pool é 32.
2. O boost atual premia palavras da query no **nome do arquivo**:
   `codebase_indexer.py` ganha por `code` e `indexer`, enquanto `rag.py` não
   ganha nada — é o mecanismo que empurra o documento certo para baixo.

## A/B (somente leitura em produção)

| configuração | recall@8 | MRR | rank do alvo | ms/query |
|---|---:|---:|---:|---:|
| pool 4×, boost atual | 0,857 | 0,821 | — | 35,8 |
| pool 4×, boost de resposta | 0,857 | 0,821 | — | 32,4 |
| pool 20×, boost atual | 0,857 | 0,786 | — | 37,0 |
| **pool 20×, boost de resposta** | **0,929** | 0,804 | **4** | 34,8 |

O boost candidato só premia (`+12`) quando a query é "how many/how much" e o
**conteúdo** contém o conceito da query associado a um valor numérico
(ex.: `chunk_size = 1200`). Foi necessário também ampliar o pool final de 4×
para 20×; o ganho de recall veio da combinação dos dois.

`code_index` medido em 275.724 pontos antes e depois: **nenhuma escrita em
produção**. O ranking de produção não foi alterado.

## Decisão

**Não aplicar em produção ainda.** O A/B foi feito em 2250 pontos, não nos
275.724 reais, e o MRR piora de 0,821 para 0,804 (ganho de recall é 1 pergunta
em 14). Antes de mudar o ranking, repetir com a coleção completa e medir
latência/memória, ou\{\} validar com `--min-recall` no harness.

Scripts reproduzíveis: `scripts/relevance-boost-ab.py` (cópia dirigida + A/B de
boost) e `scripts/boost-pool-ab.py` (A/B profundo com medição de latência).
