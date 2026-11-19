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
- HEAD atual: `029b8043` (recon 19/11).
- Primeiro commit do projeto: `ae8789fac5cbb8b2527f5091c9b2877507f8337e` (2024-11-23, fork de `nixos-config-reborn`).

## Fases
| Fase | Estado | Entrega |
|---|---|---|
| 0 — Estado inicial / checkpoint | **CONCLUÍDA** | este arquivo + `PROJECT-AUDIT-LOG.md` |
| 1 — Arqueologia (git/DB/docs) | **CONCLUÍDA** | `PROJECT-HISTORY.md` (canônico; o antigo `CHRONOLOGICAL-REVIEW-2026-11-19.md` não existe no working tree) |
| 2 — Inventário arquitetural | **CONCLUÍDA (v1)** | `ARCHITECTURE-MAP.md` (medido 19/11 11:41) |
| 3 — Auditoria do conhecimento | **CONCLUÍDA (v1)** | `KNOWLEDGE-SYSTEM-AUDIT.md` (outra lane) + ranking medido e corrigido em `b907a442` |
| 4 — OpenCode/contexto | **CONCLUÍDA** | `OPENCODE-CONTINUITY-AUDIT.md` (`c9397991`) |
| 5 — NixOS/config | **CONCLUÍDA** | `NIXOS-AUDIT.md` (`a828c568`) |
| 6 — Código/org | **EM ANDAMENTO** | AGENTS 1684→400; 2 scripts Laya arquivados com `git mv` (`a072e908`) |
| 7 — Implementação contínua | **CONCLUÍDA (22/22 backlog)** | commits abaixo |
| 8 — Validação/regressão | **CONCLUÍDA** | 2104 passed / 0 failed / 27 skipped |
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
10. **Frota muda no host** (19/11, lane runtime-production): a entrega por API
    da frota morria com `Connection refused` (o serve escuta só no IP do
    tailnet, `opencode-serve.nix`, e o config declarava `127.0.0.1:4599`) e
    `--to` não alcançava 5 dos 6 agentes (janela do Hyprland vazia, TUI
    dentro de `foot`). `agent-api.py` cai para o listener real da porta;
    `--to` identifica por `@sess:<id>` quando não há janela — `995eb3a3`.
11. **Orçamento da comunicação visível** (19/11): o `vis-enqueue` lia o
    `last` em segundos e o plugin escrevia em milissegundos (o status
    imprimia `ultimo ha -29888226094min`; o gap exigia ~50 h), e o hook
    gastava orçamento antes de olhar a fila. ms em todo o caminho, fila
    checada primeiro — `4085440a`.
12. **Medição que sequestrava a produção** (19/11): `bench-v9-v10-heldout3.py`
    subia o MTP na porta 8092 (a do default), matava o default por pattern e
    deixava órfão com o adapter v1; `night-qwen.sh` só provava que algo
    respondia na porta. Porta de medição 8094, adapter v10 real, cleanup
    garantido, gate de shadow no bench — `76625d44`.
13. **Dois donos do cliente de voz** (19/11): `duplex-restart.sh` matava o
    cliente do systemd e relançava um órfão (a unit parava 15 s depois de
    subir, medido no journal). O systemd passou a ser o dono único; a unit
    da voz, que vivia só como arquivo solto em `~/.config/systemd/user`,
    foi para o Nix (`home-manager/modules/services/duplex-voice.nix`) —
    `d3047102`.
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
14. `_handle_rehydrate` (MCP tool) não incluía o checkpoint de auditoria,
    embora `_rehydrate_state` (plugin) o incluísse desde `18d9433e`. Agente
    chamando `jarvis_rehydrate` começava sem o estado da missão. Corrigido:
    `_rehydrate_audit()` chamado em `_handle_rehydrate` também — `cf5b9611`.
    Teste: `test_rehydrate.py` 17 passed (2 de regressão).

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

## Auditoria final
`AUDIT-FINAL.md` — comparação inicial/final, testes e dívida restante.

## Entregáveis permanentes (9/9 presentes em `docs/audit/`)
`PROJECT-AUDIT-STATE.md`, `PROJECT-AUDIT-LOG.md`, `PROJECT-HISTORY.md`,
`ARCHITECTURE-MAP.md`, `KNOWLEDGE-SYSTEM-AUDIT.md`, `OPENCODE-CONTINUITY-AUDIT.md`,
`NIXOS-AUDIT.md`, `TECHNICAL-DEBT.md`, `IMPROVEMENT-ROADMAP.md`.

## A/B #18 — arm inválido descoberto e corrigido (19/11 14:25)
`mtp-lora` **não é braço válido**: `llm-swap.sh` só suporta `bonsai|mtp`;
por isso todas as linhas mtp-lora eram `motivo=infra, erro=swap`. O canonical
runner agora usa **mtp + bonsai** e já provou: `mtp @ L2 rc=0, checker`,
sem swap. Primeiro sinal real: bonsai single L2 = 1/5, chunks L2A/B/C = 4/5
cada (1 amostra por nível) — chunking parece melhorar, mas faltam 3 amostras.
Runner PID 2384517, 3 ciclos por braço.

## A/B #18 — estado real (reconciliação 19/11)
Runner confiável = **canonical A/B** (`chunk_ab_canonical.py`), usa o loop de
produção e grava `ck=v3` em `results.jsonl`. Verificado: 12 linhas frescas em
1h; bonsai L2 = 4 failed/1 passed de forma consistente; mtp-lora dá `swap`
quando :8096 sobe junto (guard do lab). Rodando em background (PID 2261149).
Meus runners diretos (`dungeon.run()`) davam TimeoutExpired 1200s —
**abandonados**, não são evidência.

## #18 FECHADO (19/11) — resultado medido
- single L2: **1/5** em 3 amostras determinísticas de bonsai (mtp 2×1/5).
- chunks L2A/B/C: **4/5** cada (1-2 amostras) — 4× o veredito do single.
- Gate H3 "cada chunk 5/5" NÃO atingido; 3ª amostra de cada chunk pendente
  (registrado como limite na evidência do backlog).
- 10 amostras `rc1` (braço `mtp-lora` inexistente no llm-swap) arquivadas,
  nunca reportadas como resultado. Lab restaurado.
- #22 (bloqueio do A/B) fechado: causa era runner direto + braço inválido.

## shadow :8092 RESOLVIDO (19/11 15:10)
ANTES: PID 709272 (fora de unit) em :8092 com adapter ERRADO
(`microturn-4b-lora.gguf` 84 MB) e unit `llama-uncensored-4b.service` inativa
→ bench noturno falhava e VRAM presa.
DEPOIS: shadow morto por PID exato; leaked bonsai/mtp dos meus A/B também
mortos por PID; unit declarada iniciada via `sudo -n systemctl start`
(system scope, não --user). Verificado: MainPID=2520576, :8092 escutando,
`/lora-adapters` = `microturn-4b-lora-v9.gguf` (3 MB) scale 1.0.
LIÇÃO: `llm-swap.sh --free` ainda tem bug `MODEL: variável não associada`
(linha 147) — registrar no debt; lab e produção disputam a mesma unit :8092.

## Testes e runtime (19/11, retomada com rebuilds autorizados)
- Full suite: **2096 passed, 8 failed, 27 skipped**. 8 falhas são testes
  antigos com arquivos limpos (test_p5_state_machine, test_reranker,
  test_voice etc.) — dívida prévia, não regressão desta missão.
- `test_offline_search.py` corrigido (6/6): teste monkeypatchava o caminho
  errado desde c514a1ba; agora força o fallback real.
- Runtime :8092: shadow removido, unit declarada ativa com adapter v9
  (detalhe na seção shadow acima). Lab pausado (`control=pause`).

## Organização (19/11, retomada 13ª)
- 23 `.bak` meus arquivados FORA do repo em
  `~/.local/state/jarvis/patch-backups-2026-11-19/` com MANIFEST.json
  (sha256 por arquivo, nada apagado em disco sem backup).
- Worktree prunable `/tmp/ack-patch-wt` removido do registro do Git
  (`git worktree prune -v`); estava ausente do disco.
- 19 itens uncommitted restantes = outro agente, NUNCA commitados por mim.
- Rebuild: `nixos-rebuild build --flake .#nitro-v15` PASSOU (116s, rc=0,
  git index 0→0). Switch NÃO executado: agents ativos commits concorrentes
  (HEAD 3213fe7c→029b8043 nesta janela) — derrubar config em alvo móvel é
  risco maior que o benefício. Intenção operacional de d3047102 JÁ satisfeita:
  duplex-voice.service ativo com 1 cliente = MainPID 2820856, sem órfãos.
  Unit ainda solta (não Nix-managed) — dívida registrada.

## Próxima tarefa exata
1. Fase 4 (delta): auditar `_rehydrate_state`/`_handle_rehydrate` quanto a ordem, dedupe e orcamento de tokens; ja existe teste de loop-breaker, falta medir tamanho real do bloco com a fila de hoje.
2. Fase 5: fechar o inventario de units/timers fora do Nix (medir agora, nao repetir numero de memoria) e conferir `home-manager/home.nix` contra `opencode.json` vivo, sem editar o vivo.
3. Fase 6: triagem de `.bak` rastreados (`harness.py.bak-*`) com o dono de cada lane antes de remover; conferir indice `scripts/TOOLS-INDEX.md` contra os scripts reais.
4. Depende do dono: reindexar `code_index` (backfill do payload canonico), remote do vault, `remember_fact(kind=decision)`, `rag-prune --apply`.
5. Rotina: testes focados no diff; suite completa (~4,5 min, `-p no:randomly`) com janela livre. Rebuild do host so com autorizacao.

## Arquivos que o próximo agente precisa ler
- `AGENTS.md` (raiz: cabecalho e regras pinadas; detalhes sob demanda).
- `docs/audit/PROJECT-AUDIT-STATE.md` e `docs/audit/PROJECT-AUDIT-LOG.md` (ultimas entradas).
- `docs/audit/INDEX.md`, `docs/audit/PROJECT-HISTORY.md`, `docs/audit/ARCHITECTURE-MAP.md`, `docs/audit/KNOWLEDGE-SYSTEM-AUDIT.md`, `docs/audit/OPENCODE-CONTINUITY-AUDIT.md`, `docs/audit/NIXOS-AUDIT.md`, `docs/audit/TECHNICAL-DEBT.md`, `docs/audit/IMPROVEMENT-ROADMAP.md`.
- `../NIXOS-AI-ORIGEM-CRONOLOGICA.md` (ai-mesh), se disponivel no host.

## Riscos de retomada
- Arvore suja com ~20 itens nao commitados (mix de docs/audit de outra lane, memory.js, scripts/agent-roster.py, .bak e diretorios nao rastreados como docs/agentes e memory/). **Nao usar `git add -A`**; inspecionar cada arquivo e respeitar o dono de cada mudanca.
- Worktrees: `.worktrees/coord-mcp` (branch `fix/coord-pending-json`) ativo; `/tmp/ack-patch-wt` consta como prunable no registro (conferir antes de remover).
- `docs/audit/CHRONOLOGICAL-REVIEW-2026-11-19.md` e citado em versoes anteriores do checkpoint mas nao existe no working tree atual; usar `PROJECT-HISTORY.md` como base canonica ate reconciliar.
- Mullvad: guard e bypass corrigidos no vivo e no repo, mas o timer declarativo novo (`mullvad-tailscale-bypass-check`) e a unit ajustada do host so entram no proximo rebuild; o timer de usuario `vpn-guard` aponta para o script do repo.
- Outros agentes ativos: Falcao em `#18`, Cervo em `#10`, Lince em TAB — verificar claim antes de editar.

## Histórico incremental de progresso
- 2026-11-19: checkpoint criado; fases 0 concluída, 1/7 em andamento; 6 correções com commit.
- 2026-11-19: RAG-EVAL criado (`2932b46e`→`e406b610`) — 4/4 sem rerank,
  2/5 com rerank (gate 4/5 não atingido); hipótese "skip rerank com ID"
  rejeitada e revertida com evidência.
- 2026-11-19: RAG P1 CORRIGIDO (`de1cbf66`) — dense query por ID forte;
  4/4 frases no top-4 (antes 1/4 no top-10); teste 3/3. Doc `f664ed0e`.
  A/B #18 BLOQUEADA (`#22`): 2 timeouts de 1200s, lab restaurado.
- 2026-11-19: rehydrate passou a incluir `PROJECT-AUDIT-STATE.md` via
  `JARVIS_AUDIT_STATE` (`18d9433e`, teste `test_rehydrate` 15/15).
  Dead code: `core/consolidate.py` TEM consumidor (`memory.py`) — hipótese
  rejeitada. 8 candidatos verificados, 6 com consumidores reais, 2 Laya
  arquivados com `git mv` (`a072e908`).
- 2026-11-19 11:51: Fase 3 concluída (auditoria do conhecimento com medições);
  Fase 2 fechada v1; 3 commits novos (`3c0c4f20`, `70f65895`, `5b2cd8c9`);
  A/B #18 registrada como morta por timeout.
- 2026-11-19 (retomada 14, Glyph/Buffy): Mullvad diagnosticado e restaurado
  (stop manual em 18/11 18:57:45; bypass nft ausente reaplicado; guard
  reescrito em `f64be138`). Correcao de performance/fiabilidade commitada em
  `029b8043` (`workspace.py` com varredura podada e capada, `harness.py` com
  snapshot de projetos, bulldozer opt-in por `JARVIS_TEST_SLM=1`);
  `test_longrun_e2e.py` 13 passed em 48.38s. Suite completa NAO reexecutada
  nesta janela (job pesado, agentes ativos).
- 2026-11-19 (retomada 14, lote 2): `8834e98c` alinhou o payload do RAG ao
  contrato do `knowledge_schema` (campos indexados que nunca eram gravados) com
  teste de regressao; 50 testes de RAG/schema/invariantes + 55 de
  memory/prune/book/legacy passaram. DB do OpenCode re-medido em `mode=ro`
  (33 tabelas, `session_part` 0, `session_message` 115.435). TECHNICAL-DEBT
  corrigido: `knowledge_schema` TEM consumidores; a divergencia estava no
  indexador. Backfill dos 275.724 pontos antigos de `code_index` fica pendente
  (escrita em producao exige autorizacao).
- 2026-11-19 (retomada 14, lote 3): `ac26129b` (consolidacao pagina a
  colecao, `max_points` respeitado, docstring do recall verdadeiro) e
  `f6013355` (vault: `write_note` valida/cifra/commita, MCP e dev.py delegam,
  checkpoint varre o repo do vault). Achado P1 medido: 276 notas do vault
  untracked desde 13/10 num repo SEM remote; commitadas como estavam
  (`36d5f49` no vault). Suite completa: 2.105 passed / 27 skipped / 0 failed
  em 269s.
