# A/B realista de payload index — 21/11

Escopo: **somente** `jarvis_test_index_ab_real`. `code_index` medido antes e
depois em **275.724 pontos** — nenhuma escrita de produção (§10.1).

## Configuração

| parâmetro | valor |
|---|---|
| pontos na coleção de teste | 12.000 |
| cardinalidade de `branch` | 4 valores (~3.000 matches por filtro) |
| seletividade | baixa (1/4 da coleção) |
| consultas amostradas | 40 (passo 300) |
| filtro | `branch` com `match.value` |
| índices criados na fase B | `branch` e `git_commit` (keyword) |

## Resultado

| fase | recall@8 | latência média | p95 | máx |
|---|---:|---:|---:|---:|
| sem índice | 1,000 | 13,79 ms | 15,04 ms | 29,40 ms |
| com índice | 1,000 | 3,37 ms | 4,00 ms | 6,15 ms |

Ganho de latência **~4,1×** na média e ~3,8× no p95, sem perda de recall.
Isso inverte o A/B anterior de 500 pontos/alta seletividade
(`RAG-INDEX-AB-2026-11-20.md`: 2,13 → 2,16 ms, sem ganho): o índice só paga
quando o filtro casa um subconjunto grande.

## Decisão

**Recomendação** (não executada): criar índice keyword em `branch` e
`git_commit` em `code_index` exigiria escrita em coleção de produção e
reindexação/migração — depende de autorização do dono (§10.1/§10.5).
Os campos já são gravados no payload desde `d8d24784`; este A/B fornece a
evidência quantitativa que faltava para a decisão.

Limitação honesta: vetores sintéticos e filtro sintético medem o mecanismo do
índice/filtro, não relevância semântica. O recall é 1,0 nos dois lados porque
o documento alvo sempre satisfaz o filtro; o benefício medido é de latência.

Bug do harness corrigido na origem: `sparse()` gerava `indices` duplicados por
colisão de hash e o Qdrant devolvia HTTP 422 (`must be unique`); agora os
índices são deduplicados e ordenados antes do upsert.
