# PROJECT-AUDIT-LOG — nixos-ai (append-only)

> Cada sessão registra aqui: identificador, data, agente, HEAD inicial/final,
> fase, trabalho, problemas corrigidos, arquivos modificados, testes, pendências.
> **Nunca apagar entradas anteriores.**

## 2026-11-19 — sessão `ses_e52816aa7ffe4zi1iV7cJ8mvtc` (Crouton Alpha)
- HEAD inicial: `57c9176517ca2f27d8e3285deb43f009cb0a21b3` (`main`).
- HEAD final: `57c9176517ca2f27d8e3285deb43f009cb0a21b3` (checkpoint criado; sem commit novo nesta entrada).
- Fase: 0 (checkpoint) + 1 (arqueologia) + 7 (correções contínuas).
- Trabalho:
  - Leitura integral das fontes: 2.931 commits (`git log --reverse`), 723 sessões do
    `opencode.db` (1,9 GB, `mode=ro`), 22 coleções Qdrant, 570 notas do Vault,
    357 linhas de memória episódica, forense 09/08 e cycle reports 4-9.
  - Síntese: `docs/NIXOS-AI-ORIGEM-CRONOLOGICA.md` (ai-mesh, commits `6e0c0d3`→`2e08594`).
- Problemas corrigidos (com commits no host):
  - `d02c4371` AGENTS.md 1684→400 linhas no handoff (teste 4/4).
  - `e119db50` model route v2 sem MAP próprio (registry × health).
  - `acdf09d5` hub: close-session no UI real (51 botões provados por `--dump-dom`).
  - `9f5678e8` Task.project sufixado — A/B recente por nível era inválida.
  - `57c91765` guard de compactação degenerada no host.
- Testes: `test_handoff.py` 4/4; `node --check` do plugin; `chromium --dump-dom` 51 cards;
  A/B chunking real executou 1 tarefa com commit + retry (verdict 3/5).
- Pendências: #18 A/B em background (2/12 amostras); fases 2/3/6/9.
- Próximo passo: verificar A/B e fechar #18; criar `KNOWLEDGE-SYSTEM-AUDIT.md`.
- Riscos: 42 uncommitted, worktrees órfãos, tailnet instável, dados de produção só leitura.

## 2026-11-19 11:51 — sessão `ses_e52816aa7ffe4zi1iV7cJ8mvtc` (continuação)
- HEAD inicial: `5b2cd8c9` antes dos commits abaixo; `main`.
- HEAD final: `5b2cd8c9` (`5b2cd8c95b4bf936d32f91b4604ec5ef96560020`).
- Fase: 3 (auditoria do conhecimento) concluída + 7 (correções) + fechamento da 2.
- Trabalho:
  - Medição somente leitura do Qdrant: `code_index` 275.724 pts (176.992
    current, 32.519 stale, 66.213 missing), `books` 11.379 (3.064 sem
    identidade por desenho), `memories` 3.034, `vault` 102, `sessions` 775.
  - `KNOWLEDGE-SYSTEM-AUDIT.md` escrito com contratos `arquivo:linha` e as
    pendências que exigem autorização.
- Problemas corrigidos:
  - `3c0c4f20` RAG acumulava versões antigas (35,8% removível): `rag_prune.py`
    + CLI `jarvis rag-prune` (dry-run default, manifesto antes do delete),
    helpers `set_payload`/`delete_by_filter`/`scroll_all`, sha do fonte
    calculado uma vez por arquivo, prune opt-in na indexação.
  - `70f65895` consolidação noturna apagava memória e escolhia keeper por
    tamanho de texto (`payload["timestamp"]` inexistente; a chave é `ts`):
    agora marca `superseded`/`superseded_by` e keeper é o mais recente.
  - `5b2cd8c9` revisão cronológica com a seção Era 0 repetida 15x.
- Arquivos: `core/rag_prune.py`, `core/rag.py`, `core/memory.py`,
  `providers/vector_store.py`, `cli/main.py`, `tests/test_rag_prune.py`,
  `tests/test_memory.py`, `docs/auditoria/CHRONOLOGICAL-REVIEW-2026-11-19.md`,
  `docs/audit/{KNOWLEDGE-SYSTEM-AUDIT,PROJECT-AUDIT-STATE,PROJECT-AUDIT-LOG}.md`.
- Testes: `pytest test_rag test_memory test_rag_prune test_rag_manifest
  test_consolidate` = 62 passed (nix develop).
- Pendências: `rag-prune --apply` (autorização), destino de
  `knowledge_schema.py`, chunk pulado sem registro em `skipped`, prune de
  `sessions`.
- Próximo passo: Fase 6 (código morto com entrypoints dinâmicos) começando
  por `core/consolidate.py` e `.bak-*` em `scripts/`.

## 2026-11-19 12:02 — mesma sessão, correção P1-C e colisão de arquivo
- HEAD final: `7de768b5`.
- Correção `11686c78`: chunk que estoura o ctx do embedder. O fallback
  embedava metade do texto e gravava o chunk inteiro no payload (vetor não
  representava o conteúdo devolvido); se a metade também falhasse, o chunk
  era descartado em silêncio. Agora ambos encurtam juntos, o descarte entra
  em `skipped` (`chunk_dropped N/M`) e `index_directory` imprime o resumo.
- **Colisão de arquivo (registro honesto)**: `KNOWLEDGE-SYSTEM-AUDIT.md` já
  existia (commit `37216195`, autor `nixos`). Meu `write_file` sobrescreveu
  sem checar, e a outra lane recommitou por cima (`81fcb511`), apagando a
  minha versão. Resolução: seções dela preservadas + seção 6 com o que esta
  sessão mediu/corrigiu (`7de768b5`); 4 setas e 1 caractere CJK do texto
  original corrigidos por `check-text-chars.py`. Lição: `read_files` antes
  de `write_file` em `docs/audit/`, onde outra lane também escreve.
- Testes: `test_rag.py` 27 passed com `test_rag_prune.py`.
- Próximo passo: reproduzir o achado de ranking (1/5 acertos no top-8) com o
  script da outra lane e medir se o prune de versões antigas muda o top-k.

## 2026-11-19 — sessão contínua (mesmo `ses_e52816aa7ffe4zi1iV7cJ8mvtc`, 2ª entrada)
- HEAD inicial: `57c91765`; HEAD final: `a50b1965` (`main`).
- Fase: 0 (checkpoint criado), 1 (arqueologia), 2 (mapa), 3 (conhecimento), 7 (correções).
- Trabalho:
  - Criados `PROJECT-AUDIT-STATE.md` e `PROJECT-AUDIT-LOG.md` (`756fd6f3`).
  - `ARCHITECTURE-MAP.md` com entrypoints/pacotes/serviços/fluxo medidos (`7b5dc985`,
    correção `d68b159a`: rehydrate é hidden-tool, funciona via `tools_call`).
  - `KNOWLEDGE-SYSTEM-AUDIT.md` com contratos reais de Memory/RAG/Qdrant/Vault
    (`81fcb511`→`a50b1965`). RAG: 1/5 known-answer hits; depois isolado — boosts
    funcionam, defeito é recall da fusão híbrida.
- Correções: RAG finding corrigido duas vezes (ranking→boost→recall) após testes isolados.
- Testes: `jarvis_rehydrate` via `tools_call` (`isError: False`); `test_boost.py`
  (CYCLE-9 sobe a 100005); `rag_retrieval_test.py` (1/5); `check_rag_indexed.py`
  (4/4 indexados); A/B 2 amostras reais (2/5, 2/5).
- Pendências: A/B morreu por TimeoutExpired em 700s (amostra 3) — gravei no estado;
  lab loop restaurado (`restart-ab.sh`, PID 1912914).
- Próximo passo: reescrever runner de A/B com try/except e timeout maior; retomar 2/12.
- Riscos: 42 uncommitted; `.worktrees/coord-mcp` ativo; Falcao claimou #18 —
  verificar claim antes de editar lane dele.
