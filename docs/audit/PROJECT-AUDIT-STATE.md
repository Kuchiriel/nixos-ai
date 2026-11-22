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
- HEAD de código (último commit com mudança de código): `7fe7e4fc`
  (exclusividade 4B). Commits de checkpoint podem estar 1 à frente;
  fonte de verdade na retomada: `git rev-parse HEAD`.
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
| 8 — Validação/regressão | **CONCLUÍDA** | 2109 passed / 0 failed / 27 skipped (240 s, 19/11) |
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
- "LoRA do :8092 caiu para scale 0.0 depois do switch" → **comportamento
  correto**: `scripts/duplex-voice.py:723` aplica scale 1.0 só durante a
  classificação e `:765` envia `[]` (off) no cleanup, para o chat com tools
  ficar limpo (medido 19/11: 0.0 estável em idle com cliente active).
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
- `knowledge_schema.py` **tem consumidor desde `8834e98c`**: `rag.py` usa
  `build_payload` para o payload canônico; `test_architecture_invariants`
  guarda `EMBED_DIM`. Pendência real: só manter o contrato único (P2, não P1).
- **FEITO**: 113 resultados A/B antigos marcados `suspect` em cópia derivada
  com índice sha; resumo em `AB-SUSPECT-SUMMARY-2026-11-20.md`. 5 amostras
  `api@L2` já re-medidas com `ck=v3`; faltam bonsai e mtp.
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

## Hub da frota / endpoints LLM (19/11, noite — pedido do dono)
- `/api/transcript` corrigido: ordem cronológica, dedupe, schema V2 (`m.text`)
  e erros de provider visíveis; hub recarregado e provado (`ordered=asc`).
- `scripts/fleet-endpoint-sweep.py`: um agente por provider, modelo forçado,
  tarefa read-only, manifesto diário em
  `~/.local/state/jarvis/fleet-endpoint-sweep/<data>.json`.
- Limites medidos dos free tiers: groq 413 TPM com o prompt do spawn;
  vários providers 429; catálogo marca modelo EOL como `active` (corrigido
  no seletor). Não concluir que "o endpoint está quebrado" sem ler o erro no
  transcript — agora ele aparece no log.
- Log consolidado: `~/.local/state/jarvis/conversation-log/<data>.md`
  (sha256 ao lado), gerado pelo `--consolidate-only`.

## Bus em tempo real + dataset de conversas (20/11 — retomada 21)
- Hub lê os 3 caminhos reais do bus (`bus-gh#100`, `coord-mcp`, `hub-wake`),
  com cache de 10 s e etiqueta de origem em cada mensagem.
- Registro automático a cada 5 min em
  `~/.local/state/jarvis/bus-journal/` (append-only, dedup por hash) — é o
  dataset a usar em auditorias e melhorias. Manifesto exposto em `/api/bus`.
- Nunca escrever esse dataset em coleções de produção sem autorização.

## Desafio FROZEN-USDT-FLEET (20/11 — retomada 19)
- Pacote: `benchmarks/fleet-challenge/frozen-usdt/` (mock USDT-like, fixtures,
  4 personas, checker cego, 17 testes). Prompt **sem conclusão implantada**;
  objetivo declarado é evitar perda de valor.
- `GROUND_TRUTH.md` é operador-only: research aponta `unfreeze_via_code=false`
  para a carteira, mas o checker aceita uma rota legítima com caller `owner`.
- Nunca rodar contra carteiras/chaves/RPC reais nem escrever em produção.

## Resultado dos endpoints LLM (20/11 — retomada 18)
- 7 providers spawnados na noite; 4 produziram trabalho real e conversa no
  bus (cloudflare, gemini, openrouter, kilocode). Log consolidado auditado:
  cronológico, dedupado, sem USER vazio, com 11 linhas `ERROR`.
- `groq` é **pendência justificada por limite externo**: 413 TPM mesmo com
  prompt mínimo (11.843 pedidos vs 8.000 permitidos). Não repetir sem
  upgrade da conta/outra rota.
- `nvidia` com ID curado também estourou o timeout de 240 s no spawn;
  investigar caminho alternativo (wake em sessão existente) antes de insistir.
- **FEITO**: `retry-summary.json` gravado; ovhcloud funcionou (tag no bus);
  llm7 atingiu cota horária; cohere sem modelo ativo no momento; nvidia
  já é usado por 14 sessões reais (não precisa de spawn). groq segue como
  pendência externa justificada (upgrade de conta/outra rota).

## Descoberta dinâmica e contratos (20/11 — retomada 23)
- Hosts/agentes vêm de `fleet-discover` (Tailscale/mDNS/ARP/ICMP/TCP/HTTPS/
  SNMP/bus), nunca de lista fixa. Dois Windows descobertos via `coord-json`.
- `AGENTS.md` do Linux segue canônico (1684 linhas); vault e celular são
  ponteiros com sha256. `sync-vault.sh` não copia mais contratos.
- `manifest-check --parity` detecta divergência de hash e declaração stale.
- Pendências vivas: racionalizar as 64 divergências de hash `~/bin` vs
  `shared/scripts`; declarar qual `termux.jsonl` é canônico; rag-prune --apply
  (produção, só com autorização explícita); Windows segue sem SSH/RDP/MCP.

## Pendências abertas (20/11 — consolidadas)
- **FEITO**: 70 divergências classificadas por evidência (59 shebang, 5 env,
  4 runtime, 2 identidade), zero drift de implementação; relatório em
  `ai-mesh/docs/script-parity-2026-11-20.md`.
- `rag-prune --apply` ainda exige autorização explícita de escrita em produção.
- Windows: dois peers descobertos e contratados, mas sem SSH/RDP/MCP — paridade
  depende de decisão do dono.
- **REGRA**: comitar sempre com `git commit --only` em árvore compartilhada
  (um commit varreu arquivos staged de outra lane; registrado em ARMADILHAS).

## Próxima tarefa exata
1. **FEITO nesta janela (Fase 8)**: suíte completa
   `nix develop --command python3 -m pytest -q modules/ai/jarvis/tests
   -p no:randomly` → **2109 passed / 0 failed / 27 skipped**, 240 s, rc=0
   (1 DeprecationWarning em `test_eval_judge`, não regressão).
2. **FEITO**: `AUDIT-FINAL.md` reconciliado com HEAD vivo e suíte 2115 passed.
   Próxima reconciliação só se HEAD mudar por outra lane.
3. **FEITO (verificação)**: `knowledge_schema.build_payload` produz 19 campos
   de proveniência e `rag.py:841` passa todos (medido 19/11). Sem divergência.
   Não tocar coleções de produção sem autorização.
4. **FEITO**: exclusividade 4B (`7fe7e4fc`) e busca por outros `setsid nohup`
   (só o whisper-server em `duplex-voice-run.sh`, legítimo). `TOOLS-INDEX`
   regenerado pelo gerador canônico em `9f8d1537` (`--check` limpo).
   **Não** rodar `--start-mtp code` sem permissão (derruba a voz via
   `Conflicts=` — comportamento correto).
5. **FEITO nesta janela (20/11)**: paridade `~/bin` x `shared/scripts`
   consolidada — 66 divergencias brutas classificadas em 54 adaptacoes, 12
   semanticas e, apos correcao, **0 reais**. `entropy-watch` stale (schema
   antigo `down`/`dead`) virado shim; 8 scripts promovidos ao canonico com
   overrides `TA_LINUX_*`; ai-mesh `ded5b4c`/`08b56b1`. Ver secao abaixo.
6. **EM CURSO**: auditoria de sync AGENTS/vault/memory/RAG/plugins e contratos
   Termux/Linux/Windows. Corrigir gaps medidos, validar com testes/rebuild
   autorizado e atualizar este checkpoint.

## Arquivos que o próximo agente precisa ler
- `AGENTS.md` (raiz: cabecalho e regras pinadas; detalhes sob demanda).
- `docs/audit/PROJECT-AUDIT-STATE.md` e `docs/audit/PROJECT-AUDIT-LOG.md` (ultimas entradas).
- `docs/audit/INDEX.md`, `docs/audit/PROJECT-HISTORY.md`, `docs/audit/ARCHITECTURE-MAP.md`, `docs/audit/KNOWLEDGE-SYSTEM-AUDIT.md`, `docs/audit/OPENCODE-CONTINUITY-AUDIT.md`, `docs/audit/NIXOS-AUDIT.md`, `docs/audit/TECHNICAL-DEBT.md`, `docs/audit/IMPROVEMENT-ROADMAP.md`.
- `../NIXOS-AI-ORIGEM-CRONOLOGICA.md` (ai-mesh), se disponivel no host.

## Riscos de retomada
- `scripts/hot-swap-model.sh` está **untracked (outro agente)** e duplica
  `llama-swap.sh` na porta 8096 com `nohup` + `kill` por PID — reintroduz
  exatamente o órfão que `7fe7e4fc` removeu. Não editar/apagar; preciso
  decidir com o dono da lane se vira wrapper do `llama-swap.sh`.
- Arvore suja com ~20 itens nao commitados (mix de docs/audit de outra lane, memory.js, scripts/agent-roster.py, .bak e diretorios nao rastreados como docs/agentes e memory/). **Nao usar `git add -A`**; inspecionar cada arquivo e respeitar o dono de cada mudanca.
- Worktrees: `.worktrees/coord-mcp` (branch `fix/coord-pending-json`) ativo, dono Onca — NAO tocar; `/tmp/ack-patch-wt` ja foi removido com `git worktree prune -v`.
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
- 2026-11-19 (retomada 14, lote 4): `54845ffa` declarou `vpn-guard`
  (`home-manager/modules/services/vpn-guard.nix`) e adicionou a migration que
  faltava em `duplex-voice` (sem ela o switch aborta com "file in the way").
  Medicao com `readlink -f` (o `FragmentPath` devolve o symlink e engana):
  17 units de usuario servidas por arquivo comum; 12 familias seguem soltas
  (chisel-*, context-guard, dono-gate, fleet-*, llama-wackmall, night-watch,
  wurm-*). Validado por `nix eval` do flake: timer e as duas activations
  aparecem. `a388c7a0` fez o bloco de auditoria do rehydrate entregar HEAD
  vivo + "proxima tarefa" + "bloqueios" (antes eram 14 linhas de cabecalho).
- 2026-11-19 (retomada 14, lote 5 — switch P0): HEAD final `7b9dd96a`.
  Causa raiz do `error: creating symlink "/nix/var/nix/profiles/.0_system":
  Permission denied` medida: `nixos-rebuild switch` herdado como uid 1000
  (`nixos`) chama `nix-env --set`; `/nix/var/nix/profiles` é root:root 755
  (`sudo touch` prova que root escreve). Correção: rodar o switch com
  `sudo -n env ... NIX_PATH=... timeout 700 nixos-rebuild switch --flake .#nitro-v15`
  (snapshot/restore de `.git/index`). Segundo bloqueio: HM abortou por
  `opencode.json.backup` já existir (`backupFileExtension = "backup"`) —
  23 arquivos `*.backup` arquivados com MANIFEST em
  `~/.local/state/jarvis/patch-backups-2026-11-19/hm-backup-collisions/`.
  Terceiro bloqueio (real): a unit gerada `duplex-voice.service` tinha
  `ExecStartPre` multilinha e o systemd fechava com `expected entry key name
  but got '/' at line 6, column 2`. `7b9dd96a` reescreveu `waitPort` para
  comando de uma linha com `;`; `nix eval` confirmou zero newlines.
  Estado final MEDIDO: switch rc=0; `home-manager-nixos.service` active;
  `~/.config/systemd/user/duplex-voice.service` é symlink para
  `/nix/store/cz5v0fv...-duplex-voice.service` e está active; `vpn-guard.timer`
  active; `llama-uncensored-4b.service` (:8092) active com LoRA v9 scale 1.0 e
  `/health` ok; `llama-uncensored-4b-code.service` (:8096) inactive;
  staged=0. Efeito colateral corrigido no caminho: os dois perfis do 4B-MTP
  competem por VRAM e o `llama-vram-guard` (4200) matou o :8092; restabelecido
  com stop do perfil code + start do perfil voice.
- 2026-11-19 (retomada 14, lote 5): 23 `.bak` próprios arquivados fora do repo
  com `MANIFEST.json` (sha256); `git worktree prune -v` removeu
  `worktrees/ack-patch-wt`; work de outros agentes intacto (25 itens);
  `nixos-rebuild build` rc=0 em 116 s e 96 s com staged=0 antes/depois.

## Reconciliação 19/11 — janela 2 (supera a seção "Organização" acima)
As linhas da seção **Organização** que dizem "Switch NÃO executado" e
"Unit ainda solta (não Nix-managed)" estavam obsoletas no momento da retomada.
Estado MEDIDO agora:
- `nixos-rebuild switch --flake .#nitro-v15` **rc=0** (via `sudo -n env`,
  porque `nix-env --set` exige root em `/nix/var/nix/profiles`).
- `home-manager-nixos.service` active; `duplex-voice.service` e
  `vpn-guard.service` são symlinks do `/nix/store`.
- `:8092` `/health` ok, LoRA v9 scale 1.0; `llama-uncensored-4b-code.service`
  (:8096) inactive. Exclusividade ainda por VRAM guard (ver Próxima tarefa 2).
- `f83644e6` corrigiu o bug que impedia a ativação: `ExecStartPre` multilinha
  na unit gerada (`expected entry key name but got '/' at line 6`).
- `105214e4` (P1): `scripts/voice-watchdog.sh` parou de criar órfão com
  `setsid nohup` e passou a delegar start/stop a `systemctl --user`. Antes,
  `--pause` matava o pid e o `Restart=always` da unit reanimava o cliente.
  Prova: `--self-test` 6/6 com `systemctl`/`pgrep`/`setsid` falsos; nenhum
  serviço real foi reiniciado no teste; `duplex-voice.service` segue active.
- Novo bloqueio descoberto: `jarvis_rehydrate` NÃO está disponível como tool
  nesta sessão (`mcp search rehydrate` vazio); o checkpoint substitui a tool.

## Paridade de scripts consolidada (20/11 — retomada automated)
- `manifest-check --parity` comparava hash bruto e reportava 66 divergencias;
 85% eram adaptacao de host, mas entre as 12 "semanticas" havia um bug real:
 `~/bin/entropy-watch` (06:44) usava `down`/`dead` enquanto o canonico
 (`f8d7855`, 11:47) ja usava `servicos[].vivo`/`fora_do_ar`.
- Correcao na origem: shim intencional em `~/bin/entropy-watch` (mesmo padrao
 de `auto-improve`); `semantic_hash` colapsa wrappers de variavel com valor
 default (inclusive aninhados) e `os.environ.get` ao literal antes de normalizar
 IP/usuario/marca; `is_shim` separa adaptacao de logica.
- Consolidacao: 8 scripts (`api-contract`, `fleet-doctor`, `lab`, `mcp`,
 `oc-doctor`, `owner-brief`, `session-clients`, `wake-direct`) promovidos ao
 canonico com os overrides de host — o canonico agora e portatil nos dois hosts.
- Evidencia: 0 divergencias reais (65 esperadas documentadas), teste com fixture
 detecta divergencia logica artificial, `lab --help`/`entropy-watch --help` OK
 no celular e no Linux, `house docs --check` OK (18), ambos os clones ai-mesh
 sincronizados. HEAD nixos-ai nesta janela: `cb76c0b8`.
- Risco resolvido: nao usar `git add -A`; commits com `--only` e pre-commit
 `repo-integrity-check` OK (sem conflict markers, JSONL valido).

## Auditoria de segredos (20/11 — retomada)
- Confirmado: 0 tokens reais em HEAD/historico/Store/`/etc`. Placeholders
  literais em 5 pontos viraram risco P2 em `TECHNICAL-DEBT.md`.
- Nao rotacionar, nao reescrever historico, nao alterar config sem rebuild
  autorizado. Relatorio: `docs/audit/SECRETS-AUDIT-2026-11-20.md`.

## Histerese do cap (20/11 — retomada)
- Validada com fixture isolada: 0,3/cap2 -> REVERT, 0,9/cap1 -> EXPAND,
  0,3/cap1 -> KEEP. Estado real do cap intacto (sha `7fcf90abd6eb…`).
- Teste permanente: `ai-mesh/tests/test_auto_improve_hysteresis.py` (1/1 nos 2 hosts).

## Contratos de frota (21/11 — retomada)
- Windows tem contrato canonico (`manifests/windows.json`) com lacunas declaradas;
  `fleet-parity` mede capacidades por host sem IPs/segredos (3/3 testes nos 2 hosts).
- Nao ativar SSH/MCP em peer Windows sem decao do dono do peer.
- Proximo: usar `fleet-parity --json` como fonte de gaps do auto-improve.

## Retomada 21/11 (missão contínua)
- HEAD no início desta janela: `f6764878`; HEAD final: `f6764878` (mudanças
  desde o checkpoint anterior: proveniência do `code_index`, sops-nix,
  cleanup do `ta-state`, migração de proveniência e correção do produtor de
  worktrees — todas documentadas em arquivos especializados).
- Worktrees de outras lanes preservados: `coord-mcp`, `rag-full-pool-boost-ab`,
  `rag-payload-index-decision`. Árvore com ~23 itens de outros agentes; não
  usar `git add -A`.
- Próxima tarefa exata: auditar divergência entre `main.py` oficial e
  `minimal_qat.py` local (fila auto-wake), com preflight verificável para
  hardware maior — sem treino longo nesta janela.
- Riscos: quota Kaggle (kernel longo 2000 passos em execução); d0008/d0009
  fecharam sozinhas por condições inválidas, d0010=Sim e d0011=Sim já
  executadas; nenhuma decisão pendente no momento.

## Retomada 22/11 (missão contínua — auditoria de sync/contratos)

- **HEAD no início da janela:** `d4adacb7`; **HEAD final:** `ec7ef23b`
  (commit isolado `--only`: correção do `/api/transcript`). Delta desde o
  checkpoint anterior (`f6764878`): LittleBit-2 PRs #13–15, proveniência RAG,
  sops, d0013, fleet-dispatch — todos documentados em seções próprias.
- **Protocolo de retomada:** AGENTS.md lido; checkpoint e log lidos; roster
  e bus consultados; Git/worktrees inspecionados. `jarvis_rehydrate` NÃO está
  disponível no MCP desta sessão (ferramentas jarvis = coord/health/roster),
  então a reidratação foi feita pelos registros persistentes.
- **Item 6 (auditoria de sync) FECHADO com evidência:**
  - `sync-status` v2 no canônico `ai-mesh/shared/scripts` — classifica
    `shim|env|shebang|REAL`, skills recursivo, `--check` gateia só drift real.
    Medido: `drift_total=184` → **`drift_real=0`**, rc=0. 9 testes (phone+host).
    Cópia antiga arquivada com sha em `~/work/hub/backups/2026-11-22/`.
  - `downgrade-opencode-2.2.5.sh` do host era **stale** (sem fix de contrato
    09/11) → virou shim ao canônico; backup com sha arquivado.
  - `notify` e `decidir` (cópia full) → shims do canônico: `manifest-check
    --parity` **0 antes / 0 depois**, help/lista idênticos byte-a-byte, notify
    real OK, `jobs-audit` 0 quebrados. Backups com sha arquivados.
  - Plugins de memória: **não há divergência funcional**. Medido:
    `summaryIsDegenerate` (824 chars) e `fallbackSummary` (749) idênticas
    após normalizar; 11 funções só-phone e 15 só-host são específicas de
    runtime. Criado `plugin-core-parity` (3 testes, PASS 2/2 real) como
    guarda permanente — **NÃO fundir os plugins** (API V2 vs hooks do host).
  - `manifest-check --parity` final: 0 divergências, 139 scripts, 4 serviços OK.
- **Hub da frota (P1 corrigido):** `/api/transcript` usava `slice(-30)` em
  array **newest-first**, cortando o fim de conversas longas (medido: 02:15:43
  vs 02:22:37). Corrigido para `slice(0,30)`, `node --check` OK, commit
  `ec7ef23b`. **Pendente:** reiniciar `agent-hub.service` (não é o opencode)
  e consolidar o log diário assim que o sweep noturno terminar.
- **LittleBit-2:** validador dos 7 gates (`ai-mesh/shared/scripts/littlebit2-validate`,
  8 testes, provado 0/7 no output do harness antigo) + runbook + lição P0 do
  log JSONL do Kaggle. Kernel v3 medido **QUEUED** às 12:59/13:10/13:24Z;
  gap segue aberto. 4 hipóteses de uso com gates em
  `ai-mesh/docs/littlebit2-uso-hipoteses-2026-11-22.md`; backlog #23–25.
- **Testes nesta janela:** ai-mesh suite 129/129 OK; littlebit2-validate 8/8;
  sync-status 9/9 (phone+host); plugin-core-parity 3/3; suíte nixos-ai
  2109 passed / 0 failed / 27 skipped (medida anterior, sem mudança de código
  Python nesta janela).
- **Lições P0 registradas** em `ai-mesh/docs/ARMADILHAS.md` + memória
  episódica: log Kaggle é JSONL; runtime full-copy fica stale; opencode escuta
  só no IP do tailnet; `/tmp` remoto não grava; `backlog` sem subcomando.

## Pendências (22/11 — consolidadas)
- Kernel Kaggle oficial: aguardar COMPLETE → baixar output → validar 7/7 →
  só então fechar `gap-littlebit2-full-qat-b4`. Tarefa na fila auto-wake.
- Sweep noturno de endpoints LLM em background; ao terminar: restart
  `agent-hub.service` + `fleet-endpoint-sweep.py --consolidate-only`.
- `rag-prune --apply` (produção) continua exigindo autorização explícita.
- Windows: contratos declarados, mas sem SSH/MCP — depende do dono.
- Árvore suja com ~30 itens de outras lanes (memory.js, agent-roster.py,
  reports, untracked) — **NUNCA `git add -A`**; commits sempre `--only`.
- Worktrees de outras lanes preservados (coord-mcp/Onca, littlebit2-*, rag-*).

## Próxima tarefa exata
1. Confirmar fim do sweep → `systemctl --user restart agent-hub.service`
   (NÃO reiniciar opencode) → validar `/api/transcript` com sessão >30 msgs
   → rodar `--consolidate-only` e conferir o log diário.
2. Levantar dono/lane das mudanças não commitadas do host e registrar no bus
   (fila auto-wake), sem commitar.
3. H3 LittleBit-2: RAG binário ITQ com 1000 queries (backlog #23).

## Riscos de retomada
- Sweep em background pode ainda estar vivo; reiniciar o hub antes dele
  terminar interrompe chamadas `/api/models` e `/api/transcript`.
- Nenhuma escrita em Qdrant de produção, opencode.db, serviços ativos ou VM.
- Segredos apenas em variáveis de shell locais; nunca bus/repo/clipboard.

## Retomada 22/11 — lote 2 (contratos, papers, hub, frota)

- **HEAD final desta janela:** `7ce0c825` (fix do timeout do sweep). Commits
  intermediários: `ec7ef23b` (transcript), `7ce0c825`.
- **Contratos de capacidade:** gap real corrigido — não existia
  `manifests/linux.json`; criado gerador medido `linux-manifest`
  (TCP connect + skills/scripts/plugins do disco + providers do hub),
  manifesto com 8 serviços up, 14 skills, 8 plugins, 9 providers. Ajuste P0:
  sondar também o IP do tailnet (só loopback subnotificava). Windows segue
  `status: limited` por decisão do dono. Matriz em
  `ai-mesh/docs/fleet-capability-contracts-2026-11-22.md`.
- **Guarda de plugins:** `memory.js` × `memory-termux.js` **não divergem**:
  as 2 funções compartilhadas são idênticas (824/749 chars normalizados);
  11 funções só-phone e 15 só-host são específicas de runtime. Criado
  `plugin-core-parity` (3 testes, PASS real 2/2) — não fundir plugins.
- **Papers de memória:** pesquisa com fontes primárias (arXiv 2606.06448,
  2602.06052, ACL 2026) levou à decisão de **não** adotar Letta/Mem0/Zep.
  Criado `memory-ledger` (read-only): medido 547 registros na malha,
  6 decisões, 460 lições, 0 duplicatas (índice 0.0) → problema é cobertura
  de decisões, não dedup. 3 testes.
- **Hub/frota:** `/api/transcript` corrigido e commitado; sweep noturno ainda
  em execução no fim da janela (5/9 spawns). Medido que 3 "spawn timeout
  240s" eram **falso negativo** — sessões existiam com tool calls reais;
  timeout do wrapper alinhado para 900s.
- **Testes do lote:** ai-mesh suite 129/129 + novos módulos (3+3+3+8+9),
  `manifest-check --parity` 0/0, `jobs-audit` limpo, `node --check` do hub OK.

## Pendências do lote 2
- Ao terminar o sweep: `systemctl --user restart agent-hub.service` (NÃO o
  opencode), validar `/api/transcript` com sessão >30 mensagens e rodar
  `fleet-endpoint-sweep.py --consolidate-only` (tarefa enfileirada no auto-wake).
- Verificar por que alguns providers não postaram no bus (429 no gemini,
  ovhcloud com 2 linhas) antes de declarar endpoint improdutivo.
- Windows: SSH/MCP dependem de declaração do dono (registrado no bus).

## Próxima tarefa exata (atualizada)
1. Concluir hub + log diário pós-sweep (enfileirado).
2. Auditoria de dono das mudanças não commitadas do host (enfileirada).
3. H3 RAG ITQ 1000 queries — backlog #23 (enfileirada).

## Riscos adicionais
- `docs/auto-improve-resolution.json` no clone do celular fica sujo por job
  de outra lane; usar `git merge --ff-only` em vez de `pull --rebase`.
- Nenhum manifesto ativa serviço; plataforma Windows exige decisão humana.

## 22/11 — rag-prune --apply EXECUTADO (autorização absoluta do dono)

- ANTES (dry-run medido): `code_index` 275.724 pontos, 99.661 removíveis
  (33.395 stale + 66.266 missing; 0 no_identity); `books` 12.778 pontos,
  203 removíveis (35 stale + 168 missing; 4.463 no_identity **preservados**).
- APLICAÇÃO: `jarvis rag-prune --collection <code|books> --apply`
  (entrypoint canônico da CLI, não `python -m jarvis.cli.rag-prune`).
  Deletados exatamente 99.661 e 203. Manifestos ANTES do delete:
  `~/.local/state/jarvis/rag-prune/rag-prune-{code_index,books}-20261122T105215.json`
  (2.538.175 e 6.392 bytes; 99.661 e 203 ids; sha256 583e53e2… e cb50fdb5…).
- DEPOIS (re-scan): `code_index` 176.063 current, 0 stale/missing/removível;
  `books` 8.112 current + 4.463 no_identity intactos, 0 removível.
- VALIDAÇÃO: `jarvis eval-rag --json` → 11 queries, 0 erros, recall@5 0,364,
  nDCG@5 0,278. Não havia baseline pré-apply medido nesta janela: o número
  é registrado como "sistema responde", não como prova de melhoria.
- Nada foi apagado de Qdrant fora dessas duas coleções, nenhuma coleção
  foi recriada, nenhum serviço reiniciado. Reversão: ids/paths nos manifestos.
- Item "rag-prune --apply" das pendências: **FEITO**.

## 22/11 — H3 e donos das mudanças
- H3 (backlog #23) fechada com resultado NEGATIVO: ITQ no RAG binário com
  1.000 queries deu Δrecall@8 0,004, IC95 [-0,022,0,027], p=0,388 —
  gate pré-registrado falhou; **não adotar**. Harness commitado no host.
- 35 itens não commitados classificados por dono/lane e publicados no bus
  (duplex, bench-token, xref/audit, rag-proveniência, littlebit2, runtime,
  frozen-usdt, legado). Nenhuma mudança de outra lane foi commitada.

## 22/11 — validação final desta janela
- Suíte Fase 8 reexecutada: **2126 passed / 0 failed / 27 skipped** (157 s).
- `AUDIT-FINAL.md` reconciliado (rag-prune feito, memória não mais error-only,
  hub com nova correção, H3 negativa, kernel ainda QUEUED).
- Bloqueio externo: kernel Kaggle em QUEUED desde ~12:59Z; sem output. Gap
  LittleBit-2 permanece aberto por decisão, não por falta de validador.

## 22/11 — fechamento da janela (autonomia absoluta do dono)

- **HEAD final:** `c7568497`; fila auto-wake com 1 tarefa (kernel Kaggle).
- **Tudo que era acionável localmente foi feito:** shims e sync-status v2,
  guarda de plugins, manifesto canônico do Linux, papers + memory-ledger
  (decisões 6→9), hub transcript, log diário 3→7 conversas,owners audit,
  H3 com gate falho, rag-prune aplicado com manifesto, suíte 2126/0/27,
  AUDIT-FINAL reconciliado e 3 decisões registradas na memória episódica.
- **Bloqueios externos (registrados no bus 7080199089):** kernel Kaggle
  QUEUED desde `lastRunTime=2026-11-22T09:53:23Z` (~5 h na fila T4x2);
  Windows sem SSH/MCP depende de declaração do dono; providers com cota
  esgotada (gemini/cloudflare/openrouter/llm7/groq/cohere).
- **Próxima tarefa exata:** quando o kernel virar COMPLETE, baixar output
  com `kaggle kernels output ... -p ~/work/littlebit2/official-2026-11-22`,
  rodar `littlebit2-validate --strict` nos 7 gates e só então fechar
  `gap-littlebit2-full-qat-b4`. Tarefa já está na fila auto-wake.
- **Riscos:** árvore com ~30 itens de outras lanes (não usar `git add -A`);
  `docs/auto-improve-resolution.json` sujo por job no clone do celular
  (usar `git merge --ff-only`); não reiniciar opencode nem serviços ativos.

## 22/11 — AGENTS.md / BUFFY.md (context engineering, lote final)

- **HEAD:** `35205b4c` (antes `3d74083a`). Árvore segue com itens de outras
  lanes; commits feitos somente com caminhos explícitos.
- **Problema medido:** `AGENTS.md` tinha 1.684 linhas / 90.047 bytes e o
  próprio cabeçalho declarava alvo `<150 linhas`; quase todo o volume era o
  protocolo BUFFY embutido. O config `local-mtp.json` já registrava o custo
  de contexto ("20k+ tokens porque o AGENTS.md do projeto com 46 KB").
- **Armadilha P0:** `BUFFY.md` era **symlink** para `AGENTS.md` — encurtar o
  alvo apagaria o protocolo integral. Backup com sha em
  `~/work/hub/backups/2026-11-22/AGENTS.md.full-1684.bak`; materializei
  `BUFFY.md` como arquivo regular com os bytes originais (sha256 f1aaa1c0…).
- **Resultado:** `AGENTS.md` 406 linhas / 26.888 bytes (−70%); `BUFFY.md`
  1.684 linhas / 90.047 bytes intacto; marker do gerador de handoff mantido.
  Nenhum consumidor assume o symlink (grep negativo). Testes: handoff 4/4,
  suíte completa **2126 passed / 0 failed / 27 skipped** (122,68 s).
- **Risco de retomada:** se algum agente esperar o protocolo dentro de
  `AGENTS.md`, o ponteiro no fim do arquivo aponta para `BUFFY.md`; nao
  reconstruir o bloco embutido (reintroduz o custo de contexto).

## 22/11 — verificação Vault (somente leitura)
- 570 notas, repo do vault limpo, 102 pontos/34 paths indexados, 0 orfãos;
  fronteira Vault≠RAG confirmada. Nenhuma ação de escrita tomada.
- HEAD final desta janela: 54279a45 (após docs de context engineering).
