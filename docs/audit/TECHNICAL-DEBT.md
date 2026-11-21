# TECHNICAL-DEBT — priorizado (medido 2026-11-19)

Classificação: P0 perda/corrupção/vazamento; P1 falha funcional; P2 duplicação/
dívida; P3 estética. Impacto real, não quantidade de arquivos.

## P0 — nenhum aberto no momento
- Qdrant produção e opencode.db foram **somente leitura**; nenhuma migração destrutiva.
- IP do dono redacionado nos docs públicos (`a1dc642`) — risco resolvido.
- Dados sensíveis (receita médica, IP no script) em quarentena **privada** (600/700).
- Violação Tailscale/Mullvad resolvida por `vpn-guard.timer` (15 min).

## P1 — alto
| # | problema | evidência | estado |
|---|---|---|---|
| 2 | A/B por nível inválido de `3f063d20` até `9f5678e8` (Task.project sem sufixo → 0 tarefas) | `discovery_stats.returned=0`; **113/1119 registros** com `nivel` na janela, marcados por índice `~/logs/ab_loop/marked/results-suspect-index-20261120-083910.json`; detalhe em `AB-SUSPECT-SUMMARY-2026-11-20.md` | **corrigido**; antigos marcados `suspect` em cópia derivada (original intacto) |
| 3 | 27/259 compactações degeneradas no host (10,4%) | DB `session_message type=compaction` | **mitigado** (guard avisa); core substitui resumo? não |
| 4 | AGENTS.md 1.684 linhas (próprio alvo <150); 400 ainda injetadas no handoff | `wc -l`, `main.py:615` | **mitigado** (`d02c4371`) |
| 5 | Falta de checkpoint verificável entre camadas (código/memória/vault/RAG) | mission §4 | **criado** `PROJECT-AUDIT-STATE.md` |

## P2 — médio
- `cli/dev.py` 4.204 linhas; ADR-003 BLOCKED até convergência `agent_loop.py`.
- 10 coleções Qdrant `test_*_memories` órfãs (payloads exportados, não apagados).
- ~20 alterações não commitadas no host (docs de outra lane, `.bak`, `memory/`,
  `docs/agentes/`) — cada uma tem dono; nada commitado sem pathspec.
- **Backfill do payload canônico**: `8834e98c` faz o indexador preencher
  `source_type`/`authority`/`status`/`canonical_path`/`source_modified_at`, mas
  só em pontos novos ou reindexados. Os 275.724 pontos atuais de `code_index`
  continuam sem esses campos; filtros por eles só valem depois de reindexar
  (escrita em produção, exige autorização).
- sync host↔phone: drift 176 (`sync-status`, report-only).
- Memória episódica error-only (sem decisões bem-sucedidas) — `KNOWLEDGE-SYSTEM-AUDIT.md`.
- Relatórios CYCLE-4..9 com itens abertos (Harbor BLOCKED por framework ausente).

- **Placeholders de `api_key` em texto literal**: `home.nix:876` e 4 chaves em
  `modules/services/litellm-cascade.nix` (ver `SECRETS-AUDIT-2026-11-20.md`).
  Não são segredos hoje, mas o padrão grava qualquer chave futura no Git e no
  Nix Store (world-readable/immutável). Migrar para agenix/sops ou env — exige
  rebuild autorizado. Nenhum token real encontrado no HEAD, no histórico ou nos
  32 generations do Store.

- **28 worktrees `ai-mesh-sync-*` no celular (~2,4 GB)**: 27 são checkouts
  antigos com tree divergente do `main`; nenhum tem arquivo ausente no canônico
  nem linha de memória não preservada. Não apagar sem decisão do dono — inventário
  completo em `ai-mesh/docs/ai-mesh-sync-worktrees-2026-11-20.json` (`d7a7cee`).
  Se o dono autorizar, usar `phone-fs propose` + manifesto antes de qualquer limpeza.

## P3 — baixo
- Worktree `/tmp/ack-patch-wt` prunable.
- Nomes com variação de caixa no Vault (não duplicatas; 570 hashes únicos).
- `session_part` V2 com 0 linhas (partes em `session_message.data.content`).

## Corrigidas / reclassificadas (medido 19/11)
- "`knowledge_schema.py` sem consumidor e divergente" — **metade falsa**: tem
  consumidores (`scripts/reindex_code.py`, `scripts/index_opencode_sessions.py`,
  `test_knowledge_schema.py`, `test_architecture_invariants.py`). A divergência
  era real e estava no outro lado: o indexador do RAG gravava payload sem os
  campos indexados. Corrigido em `8834e98c` (payload via `build_payload` +
  teste de contrato); backfill dos pontos antigos segue pendente.

## Rejeitadas com evidência
- "RAG recall da fusão híbrida 1/5" — **stale, reclassificada em 21/11**:
  com `b907a442` o `rag-eval.py` mede 13/14 (0,93) nos dois modos. A/B de
  profundidade (4–10×) e de `dense_weight`/`sparse_limit` não melhora o único
  erro; ver `docs/audit/RAG-FUSION-TOPK-2026-11-21.md`. Gate permanente:
  `rag-eval.py --min-recall 0.9` (rc=2 abaixo do alvo).
- CRC32 em IDs → é SHA-256 63 bits desde P0-1.
- BUFFY.md duplicata → symlink.
- 22 `find_repo_root` → 1 definição, 21 imports.
- Hub "não funciona" → `--dump-dom` provou 51 cards (extract stale).
- `jarvis_rehydrate` quebrado → hidden tool, funciona via `tools_call`.
- RAG "ranking ruim" → isolado: boosts corretos, recall da fusão é o defeito.
