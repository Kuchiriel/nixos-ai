# A/B de payload index para git_commit/branch (20/11)

Escopo: **somente** `jarvis_test_gitprovenance`. `code_index` medido antes e
depois em **275.724 pontos** — nenhuma escrita de produção.

## Método

`scripts/rag-index-ab.py --n 500`: 500 documentos sintéticos com
`git_commit`/`branch` no payload e vetores densos/esparsos determinísticos.
Para cada documento, uma busca híbrida com filtro exato em `git_commit`;
medidas recall@8 e latência (média/máx) antes e depois de criar os payload
indexes `keyword` nesses dois campos.

| fase | recall@8 | latência média | latência máx |
|---|---:|---:|---:|
| sem index | 1,000 | 2,13 ms | 3,88 ms |
| com index | 1,000 | 2,16 ms | 3,96 ms |

## Veredito

O índice **não mudou recall** (esperado: filtro exato já funciona sem index) e
não trouxe ganho de latência mensurável nesta escala. **Não criar payload
indexes em `code_index`** com esta evidência. Os campos `git_commit`/`branch`
continuam gravados no payload para proveniência; um novo A/B com carga
realista e seletividade baixa seria necessário para justificar índice.

Vetores sintéticos medem comportamento do filtro/índice, não qualidade
semântica de embeddings — esta limitação está registrada de propósito.
