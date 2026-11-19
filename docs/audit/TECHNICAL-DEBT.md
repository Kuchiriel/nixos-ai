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
| 1 | RAG recall da fusão híbrida: 1/5 known-answer hits; documentos indexados, boosts funcionais | `rag_retrieval_test.py`, `test_boost.py` | **aberto** — investigar top-k da fusão |
| 2 | A/B por nível inválido de `3f063d20` até `9f5678e8` (Task.project sem sufixo → 0 tarefas) | `discovery_stats.returned=0` | **corrigido**; números antigos suspeitos |
| 3 | 27/259 compactações degeneradas no host (10,4%) | DB `session_message type=compaction` | **mitigado** (guard avisa); core substitui resumo? não |
| 4 | AGENTS.md 1.684 linhas (próprio alvo <150); 400 ainda injetadas no handoff | `wc -l`, `main.py:615` | **mitigado** (`d02c4371`) |
| 5 | Falta de checkpoint verificável entre camadas (código/memória/vault/RAG) | mission §4 | **criado** `PROJECT-AUDIT-STATE.md` |

## P2 — médio
- `cli/dev.py` 4.204 linhas; ADR-003 BLOCKED até convergência `agent_loop.py`.
- 10 coleções Qdrant `test_*_memories` órfãs (payloads exportados, não apagados).
- 42 alterações não commitadas no host (`.bak` + trabalho de outros agentes).
- sync host↔phone: drift 176 (`sync-status`, report-only).
- Memória episódica error-only (sem decisões bem-sucedidas) — `KNOWLEDGE-SYSTEM-AUDIT.md`.
- Relatórios CYCLE-4..9 com itens abertos (Harbor BLOCKED por framework ausente).

## P3 — baixo
- Worktree `/tmp/ack-patch-wt` prunable.
- Nomes com variação de caixa no Vault (não duplicatas; 570 hashes únicos).
- `session_part` V2 com 0 linhas (partes em `session_message.data.content`).

## Rejeitadas com evidência
- CRC32 em IDs → é SHA-256 63 bits desde P0-1.
- BUFFY.md duplicata → symlink.
- 22 `find_repo_root` → 1 definição, 21 imports.
- Hub "não funciona" → `--dump-dom` provou 51 cards (extract stale).
- `jarvis_rehydrate` quebrado → hidden tool, funciona via `tools_call`.
- RAG "ranking ruim" → isolado: boosts corretos, recall da fusão é o defeito.
