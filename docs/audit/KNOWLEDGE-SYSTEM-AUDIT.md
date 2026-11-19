# KNOWLEDGE-SYSTEM-AUDIT — Memory, RAG, Qdrant, Vault (Fase 3)

> Medido em 2026-11-19 com leitura de código + Qdrant + DB + vault.
> Regra da missão: não tratar Memory/RAG/Vault como sinônimos; cada um tem
> contrato e fronteira próprios. Nada aqui foi alterado em produção.

## 1. Contratos reais (código)

| subsistema | arquivo canônico | contrato medido |
|---|---|---|
| Memória episódica | `core/memory.py` (438 linhas) | `MemoryEvent` → `EpisodicMemory.remember/remember_lesson/recall/lessons`; ID = `stable_id("mem", text)` (SHA-256 63 bits, **sem timestamp** ⇒ idempotente); Qdrant `memories` (3.009 pts). |
| RAG | `core/rag.py` (1.107 linhas) | pipeline extract/sanitize/chunk/embed/index/rerank (15/18/30/23/68/27 menções); `retrieve`/`fusion` aparecem 1× cada — nomes de função diferentes, não ausência. |
| Vetores | `providers/vector_store.py` (325 linhas) | `QdrantStore` com `search`, `search_hybrid`, `scroll_all`, `delete_by_filter`; `stable_id()` = SHA-256 truncado (substituiu CRC32 no audit P0-1). |
| Schema | `core/knowledge_schema.py` (234 linhas) | `vector_config`, `ensure_collection`, `build_payload`, `_content_hash` (SHA-256 cheio). |
| Vault | `core/vault.py` (204) + `core/vault_cipher.py` (133) | `MemoryVault.summarize()` escreve notas mensais com Git; cipher opcional (Fernet), `note_path`/`encrypt_text`. |

## 2. Fronteiras (o que cada um é)
- **Memória** = experiência (fatos, decisões, erros, lições) com `kind`, busca
  semântica por `recall(query)` e `lessons(query)`.
- **RAG** = conhecimento documental indexado (código, livros, papers, corpus
  offline) com proveniência de arquivo.
- **Vault** = persistência durável e legível (570 notas .md) com resumo
  periódico e Git; é o "diário de bordo" humano/agente.
- **Qdrant** = índice vetorial comum aos três (coleções separadas).

## 3. Problemas medidos (com evidência)

### P1 — Memória episódica é somente de erros
352 linhas (termux) + 5 (host), **todas** `failure`/`fix`. Não há registro de
decisões bem-sucedidas (ex.: "ADR-004 parcialmente fechada" vive em doc, não
em memória). Consequência: um agente que pergunta "o que já funcionou?" não
encontra nada; só "o que não repetir".
**Correção proposta (não implementada)**: quando uma decisão é validada por
teste, gravar `remember_fact` com `kind=decision` + ponteiro para o doc.

### P1 — `jarvis_rehydrate` fora do catálogo do celular
No host, `rehydrate` está em `_META_TOOLS`/hidden catalog (`mcp_server.py:805`)
e é chamável via `tools_call` (verificado: `isError: False`). No celular, o
meta-tool `mcp search rehydrate` não o vê (o catalogo do celular cobre apenas
coord/knowledge). **Não é bug**: é economia de contexto (RCR-Router). Mas o
protocolo de retomada da missão pede `jarvis_rehydrate` — no celular use
`~/bin/ta-state` (equivalente local).

### P2 — 10 coleções órfãs `test_*_memories`
`spaces.json` declara 4 spaces (default, pessoal, qwen4b, moe); há 10 coleções
`test_*_memories` com 0-1 ponto de spaces já inexistentes. Payloads exportados
para `ai-mesh/docs/qdrant-orfaos-manifesto.json`. **Nada apagado** ( produção
é somente leitura).

### P2 — Compactação degenerada no host
259 compactions no `opencode.db`, 27 com resumo <300 chars (5 com 0), piorando
em nov/2026 (17). Guard portado para `memory.js` (`57c91765`) avisa na
re-injeção, mas **não substitui** o resumo gravado pelo core.

### P1 — RAG: ranking ruim, índice correto (medido 19/11)
Teste de 5 perguntas com resposta conhecida (`rag_retrieval_test.py`): apenas
**1/5** retornou o documento esperado no top-8. Documentos indexados
(`check_rag_indexed.py` 4/4) e boosts funcionais (`test_boost.py`: CYCLE-9 →
100005, 1º). Isolamento final por frase (`rag_phrasing_probe.py`):
"CYCLE-9" sozinho ranqueia `CYCLE-9-REPORT.md` em **1º**; "CYCLE-9 Harbor"
e "CYCLE-9-REPORT.md" o removem do top-10. Portanto o defeito é
**diluição do embedding denso por tokens adicionais na query**, não recall
da fusão nem boosts. **CORRIGIDO** em `de1cbf66`: `strong_query_identifier()` detecta IDs fortes e
usa apenas o ID como dense query (sparse/boosts intactos). Verificado com
`HybridSearch` direto: 4/4 frases no top-4 (antes 1/4 no top-10);
`test_rag_identifier.py` 3/3.

### P1 — Vault: a camada "durável" não estava durável (medido 19/11)
O repo do vault (`~/.local/state/jarvis/vault`) **não tem remote** e tinha
**276 notas untracked + 1 modificada** desde 2026-10-13, contra 570 notas
no disco. Causa medida, em três escritores independentes:
1. `_handle_vault_write` (MCP, o caminho que os agentes usam) gravava e
   retornava "Note saved" **sem commitar** — só `summarize()` fazia
   `git add -A` + commit.
2. `cli/dev.py` `vault_write` era pior: escrevia direto em
   `vault_dir/"<name>.md"` **sem `vault_cipher`** (nota em texto puro num
   vault cifrado), **sem validar nome** (traversal) e **sem commit**.
3. `scripts/agent-checkpoint.sh` commitava só `basename` do handoff que ele
   mesmo escrevia, então nota de qualquer outra via ficava de fora para
   sempre.
**Corrigido em `f6013355`**: `MemoryVault.write_note()` centraliza
validação, cifra e commit por caminho; MCP e dev.py delegam; o checkpoint
faz `add -A` **dentro do repo do vault** (separado do monorepo). As 276
notas foram commitadas como estavam (`36d5f49` no vault), auditoria de
segredo antes (nenhum padrão de chave/PEM nas 276).

### P2 — Duas consolidações com fronteiras diferentes (documentado)
`core/consolidate.py` é **detector read-only** (merge/supersede/heat, sem
mutar); `EpisodicMemory.consolidate_memories` é o **aplicador** que marca
`superseded`/`superseded_by` (nunca apaga) e é o que o timer 03:00 roda com
`--apply`. Não são duplicatas: um diagnostica, o outro aplica. Ficam como
estão; o que faltava era o aplicador enxergar a coleção inteira.

### P1 — Consolidação noturna via um terço da memória (corrigido 19/11)
`consolidate_memories` fazia **um** scroll de `limit=1000` e ignorava o
parâmetro `max_points`: com 3.105 pontos em `memories`, dois terços nunca
eram vistos e o timer revisitava sempre o mesmo prefixo por id. Corrigido em
`ac26129b` (scroll paginado até `max_points`, `scanned` no resultado). O
docstring do `recall` prometia dedup ">95% similar" que o código não fazia
(dedup exato normalizado); agora diz a verdade e aponta a consolidação.

## 4. O que NÃO é problema (verificado)
- `stable_id`: SHA-256 63 bits, não CRC32 (CRC32 foi substituído no P0-1).
- `_stable_id` da memória ignora timestamp de propósito ⇒ upsert idempotente.
- 570 notas do vault: 570 hashes únicos (nomes com caixa diferente ≠ duplicata).
- Vault cifra com Fernet opcional; `pessoal_*` coleções são produção, intocáveis.

## 5. Próximos passos (Fase 3)
1. ~~Teste de recuperação RAG com perguntas de resposta conhecida~~ fechado:
   `RAG-EVAL.md` (15 perguntas, recall@8 0,93, MRR 0,762; `b907a442`).
2. ~~Reindexação incremental~~ verificado: `index_file` compara
   `source_sha256`/`content_hash` e `rag-prune` remove o que sumiu.
3. ~~Payload canônico no índice~~ corrigido (`8834e98c`): o indexador agora
   preenche os campos que os payload indexes declaram. **Backfill** dos
   275.724 pontos antigos continua pendente (reindexar = escrita em
   produção; exige autorização).
4. Decidir (com dono) se decisões validadas viram `remember_fact(kind=decision)`
   (hoje a memória é só de falhas: 352 `failure`/`fix`, 0 decisão).
5. Vault: decidir destino do remote (hoje local-only ⇒ um disco perdido
   apaga tudo; o commit resolve rollback, não backup).
