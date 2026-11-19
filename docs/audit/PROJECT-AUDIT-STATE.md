# PROJECT-AUDIT-STATE — nixos-ai

> **Checkpoint operacional da missão contínua** (criado 2026-11-19).
> Índice de alto valor; detalhes ficam nos documentos especializados linkados.
> Regra: toda retomada começa aqui, depois lê `PROJECT-AUDIT-LOG.md` (append-only).

## Objetivo e escopo
Auditoria histórica, forense e evolução integral do `Kuchiriel/nixos-ai`:
reconstruir o nascimento, entender cada subsistema, corrigir problemas
comprovados, consolidar duplicações e reduzir entropia/dívida técnica.
Não é um relatório único — o trabalho continua enquanto houver dívida.

## Datas e HEADs
- Início da missão: 2026-11-19.
- HEAD inicial da auditoria: `57c9176517ca2f27d8e3285deb43f009cb0a21b3` (`main`).
- HEAD atual: `b907a442` (checkpoint 2026-11-19 12:30).
- Primeiro commit do projeto: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (2024-11-23, fork de `nixos-config-reborn`).

## Fases
| Fase | Estado | Entrega |
|---|---|---|
| 0 — Estado inicial / checkpoint | **CONCLUÍDA** | este arquivo + `PROJECT-AUDIT-LOG.md` |
| 1 — Arqueologia (git/DB/docs) | **CONCLUÍDA** | `PROJECT-HISTORY.md` + `CHRONOLOGICAL-REVIEW-2026-11-19.md` |
| 2 — Inventário arquitetural | **CONCLUÍDA (v1)** | `ARCHITECTURE-MAP.md` (medido 19/11 11:41) |
| 3 — Auditoria do conhecimento | **CONCLUÍDA (v1)** | `KNOWLEDGE-SYSTEM-AUDIT.md` (outra lane) + ranking medido e corrigido em `b907a442` |
| 4 — OpenCode/contexto | **CONCLUÍDA** | `OPENCODE-CONTINUITY-AUDIT.md` (`c9397991`) |
| 5 — NixOS/config | **CONCLUÍDA** | `NIXOS-AUDIT.md` (`a828c568`) |
| 6 — Código/org | PARCIAL | AGENTS.md 1684→400 linhas no handoff |
| 7 — Implementação contínua | **EM ANDAMENTO** | commits abaixo |
| 8 — Validação/regressão | PARCIAL | test_handoff 4/4; jobs 16/0 |
| 9 — Auditoria final | PENDENTE | — |

## Subsistemas já investigados (com evidência)
- **Git**: 2.931 commits; origem 2024-11-23; salto de ~9 meses; explosão JARVIS em 2026-08-19.
- **opencode.db** (1,9 GB, `mode=ro`): 723 sessões tituladas (2026-08→11); 259 compactações,
  27 degeneradas (<300 chars, 5 com 0).
- **Qdrant**: 22 coleções (`code_index` 275.724 pts); 10 `test_*_memories` órfãs exportadas
  em `qdrant-orfaos-manifesto.json` (ai-mesh) — NADA apagado.
- **Vault**: 570 notas .md em `~/.local/state/jarvis/vault`; 570 hashes únicos
  (nomes com variação de caixa NÃO são duplicatas).
- **Memória episódica**: 352 linhas (termux) + 5 (host) — somente erros/fixes,
  sem registro de decisões bem-sucedidas.
- **Forense 09/08**: 6/8 achados confirmados corrigidos; F2/F4 re-verificados.

## Problemas corrigidos (com commits)
1. `AGENTS.md` injetado por inteiro (1.684 linhas) no handoff → 400 + ponteiro,
   `test_handoff.py` 4/4 — `d02c4371`.
2. `fleet_model_route` v1 com MAP próprio (4ª política) → v2 lê
   `provider_registry.route()` × saúde medida — `e119db50`.
3. Hub: botão "fechar sessão" no arquivo UI REAL + short model + roster primeiro
   (51 cards/51 botões, `--dump-dom`) — `acdf09d5`.
4. `Task.project` sem sufixo desde `3f063d20` → harness lia 0 tarefas e
   **toda A/B recente por nível era inválida** — `9f5678e8`.
5. Guard de compactação degenerada portado para o host — `57c91765`.
6. Chunking L2: níveis L2A/B/C + baseline pré-A* + checkers validados — `9f5678e8`.
7. RAG acumulava versões antigas (35,8% do `code_index` removível) →
   `rag_prune.py` + `jarvis rag-prune` (dry-run + manifesto) — `3c0c4f20`.
8. Consolidação noturna apagava memória e escolhia keeper por tamanho de
   texto (chave `timestamp` inexistente) → marca `superseded`, keeper por
   `ts` — `70f65895`. Vale no próximo 03:00 (timer roda do source).
9. Revisão cronológica com a seção Era 0 repetida 15x (395→102 linhas) — `5b2cd8c9`.
10. Chunk que estoura o ctx do embedder: vetor de metade com payload do
    chunk inteiro, e descarte silencioso — `11686c78`.
11. Auditoria de conhecimento preservada em duas versões concorrentes:
    merge sem perder a seção da outra lane — `7de768b5`.
12. Ranking do RAG: boost de filename vazio (+100000 para hit sem path) e
    fusão do rerank quase simétrica anulavam o cross-encoder. Medido com 15
    perguntas: recall@8 0.36 → 0.93, MRR 0.357 → 0.762 — `b907a442`.
13. `docs/HANDOFF-FORMAT.md` não existia apesar do ponteiro no `AGENTS.md`
    da raiz: criado com formato, nome e regra de supersessão.

## Conflito de lanes (2026-11-19 12:30)
`docs/audit/KNOWLEDGE-SYSTEM-AUDIT.md` tem outra sessão ativa escrevendo:
ela reescreveu o arquivo e reverteu a correção de setas e a seção com as
medições desta sessão. **Regra para o próximo agente: ler antes de editar
esse arquivo e não reeditar por cima.** O registro desta sessão vive no
`PROJECT-AUDIT-LOG.md` (append-only) e nas mensagens de commit.

## Decisões arquiteturais
- **ADR-003** (personas): manter BLOCKED — exige convergência `dev.py`→`agent_loop.py`;
  micro-patch proibido pela regra §0.1. Ver `../ADR-003-DECISAO-19-11.md` (ai-mesh).
- **ADR-004** (routing): parcialmente fechada — registry tem 9 consumidores;
  hot path do LLM segue BLOCKED. Ver `../ADR-004-RESOLUCAO-PARCIAL-19-11.md`.
- **Qdrant**: coleções órfãs exportadas, não apagadas; cleanup exige autorização.

## Hipóteses rejeitadas (evidência)
- "BUFFY.md é duplicata de 90 KB" → é **symlink** (`ls -l`).
- "22 definições de `find_repo_root`" → 1 definição, 21 imports (`grep def`).
- "16 scripts com LD_LIBRARY_PATH duplicado" → guards legítimos (`bench-llm.sh`).
- "hub não renderiza" → `jarvis_browser extract` era stale-page; `--dump-dom` provou 51 cards.
- "10 notas duplicadas no vault por caixa" → 570 únicos em 570 arquivos (hash).

## Pendências
- **#18** (único backlog aberto): A/B de chunking. O run em background
  **morreu por timeout** (`subprocess.TimeoutExpired` após 700 s no
  `nix develop ... dungeon.run`), 2/12 amostras; o log para em traceback.
  Não é falha do chunker: o harness estoura o teto por comando.
- **rag-prune --apply** em `code_index` (98.732 pts) e `books` (203):
  **exige autorização do dono** (dados de produção, §10.1/§10.2).
- `knowledge_schema.py` sem consumidor e divergente do payload real
  (P2-1 do KNOWLEDGE-SYSTEM-AUDIT): decidir executável vs documento.
- Migrar resultados A/B antigos (inválidos por `Task.project`) — marcar como suspeitos.
- Fase 6/9 do plano ainda não concluídas.

## Bloqueios
- Tailnet oscila (2 VPNs no lado Android); Host acessível por IPv6 quando up.
- Dados de produção do Qdrant e opencode.db: **somente leitura**.
- Serviços ativos/VM/Hyper-V: nãoAlterar sem autorização.

## Entregáveis permanentes (9/9 presentes em `docs/audit/`)
`PROJECT-AUDIT-STATE.md`, `PROJECT-AUDIT-LOG.md`, `PROJECT-HISTORY.md`,
`ARCHITECTURE-MAP.md`, `KNOWLEDGE-SYSTEM-AUDIT.md`, `OPENCODE-CONTINUITY-AUDIT.md`,
`NIXOS-AUDIT.md`, `TECHNICAL-DEBT.md`, `IMPROVEMENT-ROADMAP.md`.

## Próxima tarefa exata
1. Fase 6: varredura de código morto real (sem referência textual, com
   entrypoints dinâmicos): começar por `core/consolidate.py` (P2-2 do
   KNOWLEDGE-SYSTEM-AUDIT) e pelos `.bak-*` na raiz de `scripts/`.
2. Fase 4: auditar `rehydrate` de ponta a ponta (ordem, dedup, limite de
   tokens) contra o que o MCP devolve hoje.
3. Recall da fusão para a pergunta "chars por chunk" (falha com e sem
   rerank): ela não entra nos candidatos crus — investigar dense/sparse e o
   cap de `top_k*4` (outra lane já claimou esse ponto: conferir antes).

## Arquivos que o próximo agente precisa ler
- `AGENTS.md` (raiz, 1.684 linhas — ler o cabeçalho e as regras pinadas; o resto sob demanda).
- `docs/audit/INDEX.md`, `docs/audit/CHRONOLOGICAL-REVIEW-2026-11-19.md`.
- `../NIXOS-AI-ORIGEM-CRONOLOGICA.md` (ai-mesh, síntese verificada).
- `PROJECT-AUDIT-LOG.md` (este diretório).

## Riscos de retomada
- 42 alterações não commitadas no host (principalmente `.bak` de patches + trabalho de outros agentes).
  **Não usar `git add -A`**; inspecionar cada arquivo.
- Worktrees: `.worktrees/coord-mcp` (branch `fix/coord-pending-json`) e `/tmp/ack-patch-wt` (prunable).
- Outros agentes ativos: Falcao em `#18`, Cervo em `#10`, Lince em TAB — verificar claim antes de editar.

## Histórico incremental de progresso
- 2026-11-19: checkpoint criado; fases 0 concluída, 1/7 em andamento; 6 correções com commit.
- 2026-11-19 11:51: Fase 3 concluída (auditoria do conhecimento com medições);
  Fase 2 fechada v1; 3 commits novos (`3c0c4f20`, `70f65895`, `5b2cd8c9`);
  A/B #18 registrada como morta por timeout.
