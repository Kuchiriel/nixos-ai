# Backfill dos campos canônicos — validação isolada (21/11)

## Problema

Amostra de 5.000 pontos de `code_index`: cobertura **0** para `source_type`,
`source_id`, `repo`, `status`, `authority`, `source_modified_at` e
`canonical_path`; apenas `ingested_at`, `git_commit` e `branch` presentes.
Os payload indexes canônicos existem, mas filtrar por esses campos não casava
com nada.

## Teste em `jarvis_test_canonical_backfill`

- 2.000 pontos copiados de `code_index` (vetores + payload), sem escrita em
  produção.
- Backfill derivado do `path`: `canonical_path`, `filename`, `source_type`
  (code/doc pela extensão), `source_id` (`doc:` + sha256 do path),
  `repo`, `status=current`, `authority=source` e `source_modified_at` em
  **RFC3339** (o payload index é `datetime` — valor float foi corrigido).
- Indexes keyword/datetime replicados no teste para espelhar produção.

| campo | antes | depois |
|---|---:|---:|
| source_type / source_id / repo / status / authority | 0 | 2000 |
| canonical_path | 0 | 2000 |
| source_modified_at | 0 | 1539 |

461 pontos não receberam `source_modified_at` porque o arquivo de origem não
existe mais no disco — deixamos ausente em vez de inventar data.

| filtro | recall@8 antes | recall@8 depois |
|---|---:|---:|
| `source_type` | 0,0 | 1,0 |
| `repo` | 0,0 | 1,0 |

Teste adicional: filtro `source_modified_at` com `range.gte` em RFC3339 devolveu
8 acertos e o documento alvo no top-8.

## Decisão

O backfill é **tecnicamente válido**: os campos canônicos passam a ser
filtráveis e não degradam o recall. **Não aplicado em produção** nesta tarefa:
o objetivo era validar antes de qualquer reindexação. Aplicação futura exige
snapshot do `code_index`, execução em lotes com `?wait=true`, validação de
cobertura e aceite explícito — os 275.724 pontos atuais não devem ser
reescritos sem esse protocolo.

Utilitário: `scripts/backfill_canonical_test.py` (modo isolado).
