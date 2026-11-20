# Proveniência Git no índice RAG (20/11)

## Problema

`code_index` tem 275.724 pontos e 99.294 removíveis (36%) em dry-run, mas o
payload não dizia de qual commit/branch veio cada ponto. O manifesto
`logs/code_index-reindex.json` (18/09) também não tinha commit, então não é
possível provar que o índice corresponde ao HEAD atual.

## Mudança (somente leitura em produção)

- `knowledge_schema.git_provenance()`: HEAD/branch via `git -C <repo>` com
  timeout 5 s, overrides `JARVIS_GIT_COMMIT`/`JARVIS_GIT_BRANCH` e fallback
  `unknown`. Read-only, cacheado.
- `build_payload()` já tinha `git_commit`; agora também grava `branch`.
- `rag.py` preenche ambos no payload canônico de cada chunk.
- `reindex_code.py` grava `git_commit`, `branch` e `schema_version` no manifesto.
- **Não** criamos payload indexes novos: isso exigiria migração da coleção de
  produção. Os campos ficam no payload para consulta/proveniência; indexação
  futura precisa de validação explícita.

## Evidência

- `py_compile` OK; testes focados `test_knowledge_schema.py` +
  `test_architecture_invariants.py`: **20 passed**.
- `git_provenance()` medido: commit `eb122765…`, branch `main`; payload
  gerado contém `git_commit` e `branch`.
- `jarvis rag-prune --collection code`: `removable=99294`, `apply=false` —
  nenhuma escrita/aplicação em produção.

Os 99.294 pontos antigos seguem sem proveniência; só novas indexações
carregam os campos. Não houve `--apply`.
