# Proveniência real por arquivo no code_index (21/11)

Substitui a proveniência da migração anterior (`branch=main`,
`git_commit=cbdbaca48aa6…` para todos os pontos) pelo **último commit real que
tocou cada arquivo**.

## Cobertura medida

- 275.724 pontos, 22.438 paths únicos.
- Mapa gerado por `git log --format=COMMIT %H --name-only -n 3000` por repo.
- 105.441 pontos (38,2%) receberam o commit real; os demais receberam
  `git_commit=unknown` / `branch=unknown` — honesto, em vez de atribuir um
  commit falso. Repos sem `.git` ou com histórico truncado: `harness-research`,
  `prism-llama.cpp`, `llama-wackmall`, `ik_llama.cpp`, entre outros.

## Segurança e validação

- Snapshot Qdrant antes da escrita:
  `code_index-…-2026-11-21-18-31-04.snapshot`, checksum `3e9bc84b…eecd4`.
- Teste em `jarvis_test_real_provenance` (2000 pontos): recall@8 1,0 antes e
  depois, latência 2,51 → 2,45 ms; 2000/2000 pontos atualizados.
- Produção: 275.724/275.724 pontos atualizados em 1259 grupos; scan final
  mostra **0** pontos com o commit da migração, 170.283 `unknown` e 105.441
  com commits reais; 268 distintos.
- Recall@8 com filtro por `git_commit`: **1,0** em 30 consultas; latência
  1,71 ms. Índices `branch`/`git_commit` preservados.

Armadilha corrigida no utilitário: `POST /points/payload` é assíncrono por
padrão — sem `?wait=true` um scan imediato ainda via o valor antigo. O script
agora usa `?wait=true`.

Commit local (push bloqueado por segredos em histórico antigo — ver
`LITELLM-ENV-QUARANTINE-2026-11-21.md`).
