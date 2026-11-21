# Migração de proveniência no code_index (21/11)

Autorização: `d0011 = Sim` ("reindexar/migrar code_index ... e criar os
indexes keyword"). `d0008` tinha fechado sozinha por condição inválida; a
pergunta correta foi reenviada como `d0011`.

## Antes

- 275.724 pontos; `payload_schema` sem `branch`/`git_commit`.
- Cobertura medida: **0/100** pontos com os campos.
- A/B realista prévio (`RAG-INDEX-AB-REAL-2026-11-20.md`): filtro `branch`
  com seletividade 1/4, 13,79 → 3,37 ms com índice.

## Segurança

- Snapshot Qdrant criado antes de qualquer escrita:
  `code_index-6974365916078920-2026-11-21-16-44-13.snapshot`,
  `size=1.999.933.952`, checksum `faf2802e…71d0d788f`.
- Teste em `jarvis_test_migrate_provenance` (1000 pontos copiados):
  recall@8 0,0 → 1,0, latência 1,66 → 0,91 ms; `payload_schema` ganhou
  `branch`/`git_commit`.
- Utilitário versionado: `scripts/migrate-provenance.py` com modos explícitos
  (`--prepare-test`, `--snapshot`, `--migrate --dry-run/--apply`, `--indexes`,
  `--measure`).

## Aplicação

- Payload atualizado nos **275.724 pontos** com `branch=main` e
  `git_commit=cbdbaca48aa6…` (HEAD no momento da migração).
- Índices keyword criados com `?wait=true` (branch levou 66 s; git_commit
  0,014 s) — sem `wait`, a criação era assíncrona e o schema não aparecia.
- Verificação: `payload_schema` contém `branch` e `git_commit`;
  cobertura 200/200 na amostra; 30 consultas com filtro por `branch`:
  recall@8 **1,0**, latência média **10,2 ms**.

## Limitação honesta

O `git_commit`/`branch` gravado é a **proveniência da migração**, não o
commit original de cada chunk (isso não estava registrado). O índice agora
pode ser filtrado por esses campos e futuras reindexações sobrescrevem com
o commit correto via `build_payload`/`git_provenance` (`d8d24784`).

Nenhum dado foi apagado; rollback possível restaurando o snapshot acima.
