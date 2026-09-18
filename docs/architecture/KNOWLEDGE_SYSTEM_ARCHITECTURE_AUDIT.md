# KNOWLEDGE_SYSTEM_ARCHITECTURE_AUDIT

> Auditoria independente e READ-ONLY (18/09, paralela à reconstrução).
> Contratos reais extraídos do código executado em runtime — não do README.
> Referências `arquivo:linha` verificadas no estado atual (HEAD de8892b).
> **Não toquei no pipeline ativo**; este é diagnóstico estrutural.

---

## 1. Architecture map (caminho real)

```
FILESYSTEM → doc discovery → identity → sanitizer → normalize → chunk → embed → Qdrant → retrieval → RAG → MCP
AGENT/SESSION → events → episodic memory → recall/lessons
FILESYSTEM ⇄ Git ⇄ manifest ⇄ knowledge index ⇄ Qdrant
```

## 2. Runtime call graph (tabela de contratos)

| Etapa | Implementação real | Entrada | Saída | Persistência | Chamado por | Chama |
|---|---|---|---|---|---|---|
| Doc discovery | `rag.py:iter_indexable_files` (:306) | root/excludes | yields path | — | `HybridIndexer.index_directory` (:416) | os.walk |
| Identity (code) | `rag.py:418` `abs(dense_key(f"{path}_chunk_{i}"))` | path+chunk | point_id (crc32) | Qdrant | `index_file` | — |
| Sanitizer | `doc_sanitize.sanitize_document` | path | `SanitizedDoc(status,text,provenance,failures)` | manifest.jsonl | `rag.index_file:375`, `audiobook.index_book` | extract/normalize/validate |
| Chunking | `rag.py:374` window fixo 1200 chars | text | chunks | — | `index_file` | — |
| Embedding | `LLMClient.embed` → nomic 8081 | text | dense 768 | — | index_file, query | server |
| Sparse | `rag.py:201,214` sparse_terms/sparse_vector | text | {indices,values} | — | upsert, search | dense_key crc32 |
| Qdrant write | `QdrantStore.upsert` (:93) | points | — | Qdrant | rag/audiobook/memory | REST |
| Retrieval | `HybridSearch.search` (:458) | query | HybridHit[] | — | MCP `_handle_rag_search` | Qdrant search_hybrid |
| Rerank | `rag.py:502` Reranker (bge-reranker :8082) | query+cands | ranked | — | search | reranker |
| RAG→MCP | `mcp_server._handle_rag_search:918` | {query,collection,limit} | str | — | stdio | HybridSearch |
| Episodic | `memory.remember:101` | MemoryEvent | point_id | Qdrant memories | MCP remember | embed+upsert |
| Recall | `memory.recall:130` | query | hits (dedup) | — | MCP recall | search_hybrid |
| Lessons | `memory.lessons:179` | query | "PAST LESSONS" | — | MCP lessons | recall |
| Book RAG | `audiobook.index_book` | book_name | count | Qdrant books | cli | sanitizer+embed+upsert |

## 3. Sanitizer contract (real)

- **Onde**: `doc_sanitize.py`; chamado por `rag.index_file:375` e `audiobook.index_book` (2 únicos pontos de entrada documental).
- **Entrada**: path (restringido por `_safe_path`). **Saída**: `SanitizedDoc{status: ok|quarantine, text, provenance, failures, warnings}`.
- **Invariantes**: vazio-válido ≠ extração-falha; perda catastrófica (>5%) → quarantine; UTF-8 check; SCANNED (sem text-layer + sem tesseract) → `EXTRACTION_FAILURE`/quarantine.
- **Determinístico**: SIM (sem LLM no caminho; hashes+versões no manifest).
- **Bypass**: nenhum — os únicos `upsert` documentais (rag:432, audiobook:981) passam por `sanitize_document` antes. `memory.py:113` embebe evento direto (memória episódica — NÃO é documento, correto).
- **Duplicado?** Não há 2º sanitizer. `sanitize_secrets` (devtools) é TOOL de limpeza de segredo do agente, NÃO pré-RAG (não confundir).
- **Risco**: `index_file` recebe `content=` explícito (via `index_directory` não; mas o parâmetro existe) → se algum caller passar `content` sem path, **pula o sanitizer** (o sanitizer só roda no branch `content is None`).

## 4. Document identity contract

| ID | Derivação real | Estável a rename/move? | Idempotente? | Risco |
|---|---|---|---|---|
| doc point_id | `abs(crc32(path_chunk_i))` rag:418 | NÃO (path na hash) | overwrite por colisão | rename → dupe |
| book chunk_id | `abs(crc32(stem\|ch\|i))` audiobook:46 | NÃO (stem na hash) | overwrite por colisão | rename → dupe |
| memory point_id | `crc32(ts:text)` memory:_stable_id | — | NÃO (ts na hash) | re-remember → dupe |
| sparse index | `crc32(term)` dense_key | — | SIM | colisão 32-bit |

- **Todas usam crc32 (32-bit)** → colisões prováveis em escala (birthday ~77k pontos p/ 50%).
- `document_id`/`canonical_path`/`source_sha256` existem só no schema novo (`knowledge_schema.build_payload`), NÃO na maioria dos pontos reais (payloads atuais usam `path`/`filename`/`book`).
- **Duplicata** é detectada só no RETRIEVAL (memory.recall dedup por texto :150), nunca na escrita.

## 5. Provenance contract

- **Real (antigo)**: payload `path`/`filename`/`ext`/`facts` (rag:402-409) — NÃO tem source_sha256/timestamp/versão de pipeline.
- **Novo (knowledge_schema.build_payload §13)**: `source_sha256, content_hash, source_modified_at, ingested_at, sanitizer_version, extractor, ocr_used, authority, status, repo, git_commit`.
- **Gap**: o código antigo (rag/memory/audiobook) ainda NÃO usa `build_payload` — os pontos reais NÃO têm a cadeia nova. A reconstrução (outro agente) deve preencher isso; documentado como risco P1.

## 6. RAG contract

- `HybridIndexer` (:340): dense 768 + sparse bm25(idf), payload path/facts/filename/ext/content.
- Chunking: **janela fixa 1200 chars** (rag:374) — NÃO structure-aware (§22 mission quer section/table/code).
- `HybridSearch` (:450): prefetch dense+sparse, RRF weights [5.0,1.0] dense-dominante, re-rank V4.0.5 boosts, reranker opcional (:488).

## 7. Episodic memory contract

- `EpisodicMemory`: remember/recall/lessons/recent/count/clear.
- `clear()` (:230) **deleta a coleção INTEIRA** (memories) — risco P1 se chamado por engano.
- `recent()` (:204): scroll + sort só da página retornada (não global) — pode perder eventos recentes.
- recall dedup por texto (:150), não na escrita.

## 8. Lessons contract

- `lessons()` (:179): recall kinds=(lesson), formata "PAST LESSONS", cap max_chars 500.
- Sem store próprio — é um FILTRO sobre memória episódica (kind=lesson). Coerente, mas "lessons" não é domínio separado no Qdrant (vive em memories com payload kind). Aceitável; documentar.

## 9. MCP contract (tools de knowledge)

| MCP tool | Handler | Service | Nota |
|---|---|---|---|
| jarvis_rag_search | `_handle_rag_search:918` | HybridSearch | **chama ensure_collection na LEITURA** (mutation hidden) |
| jarvis_rag_index | `_handle_rag_index:954` | HybridIndexer | cria coleção + indexa |
| jarvis_remember | `_handle_remember:836` | EpisodicMemory | — |
| jarvis_recall | `_handle_recall:852` | EpisodicMemory | — |
| jarvis_lessons | `_handle_lessons:872` | EpisodicMemory | — |
| jarvis_vault_list/write | :886/:899 | MemoryVault | write direto em `vault_dir/<name>.md` (path concat → validação de traversal ausente) |

- **Bypass**: MCP acessa serviços canônicos (não Qdrant direto), exceto `rag_search` que ainda faz `ensure_collection`/`QdrantStore(cfg)` inline. Sem bypass de dados, mas com mutação de schema na leitura.
- **vault_write** (`:912`) concatena `name` a `vault_dir` sem sanitizar → path traversal potencial (P1).

## 10. Qdrant contract

- `QdrantStore` (vector_store.py): `ensure_collection` (dense nomeado 768 + sparse bm25 idf), `upsert`/`delete_points`/`search`/`search_hybrid`/`count`/`delete_collection`.
- **Hardcoded**: DENSE_VECTOR_NAME="dense", SPARSE_VECTOR_NAME="bm25", dim 768 default. Config: `qdrant_url`/`collection_*` (env-overridable).
- **Schema duplicado**: `knowledge_schema.vector_config` (novo) vs `QdrantStore.ensure_collection` (:70, hardcoded) — 2 definições do mesmo schema; a reconstrução deve convergir.
- `_handle_rag_search` cria coleção se ausente (mutação em leitura) — e usa dim do config.

## 11. Embedding contract

- Modelo: `nomic-embed-text-v2-moe.Q8_0` (models.nix:129), servidor `llama-cpp-embeddings` :8081, pooling mean, `-c 4096`.
- Config: `embed_base_url`, `embed_model`, `embed_dim=768`. `LLMClient.embed` → mesmo servidor para INDEX e QUERY (consistente — sem split index/query, bom).
- Batch: `-b 2048 -ub 1024`; rag_index falha "batch size too small" é tratado como hint no MCP.

## 12. Retrieval contract

- `search(query, top_k, dense_limit, sparse_limit, use_rerank)`. Query→embed→prefetch→RRF→boosts→(reranker)→HybridHit.
- Filtros: só `ext_filter` (rag search). **Sem filtro por domínio/collection além do nome** (o MCP troca collection via dataclasses.replace).
- `HybridHit.path` (campo real) — MCP usa `r.path` corretamente.

## 13. Failure matrix

| Falha | Onde | Detectada | Propagada | Recovery | Teste |
|---|---|---|---|---|---|
| Arquivo ilegível | index_file:377 OSError | except | return None (skip silencioso) | reindex | ? |
| PDF inválido | sanitize extract | status quarantine | skip+manifest | re-run | test_doc_sanitize |
| OCR falhando | sanitize (sem tesseract) | quarantine | skip | n/a | test scanned |
| Sanitizer rejection | validate | failures | quarantine | re-run | test |
| Embedding fail | rag:394/401 except | continue | chunk silencioso pulado | reindex | — |
| Qdrant unavailable | QdrantStore._request | raise VectorStoreError | MCP→"ERROR:" str | retry | — |
| Schema mismatch | upsert 400 | raise | MCP→"ERROR:" | recreate | — |
| Duplicate doc | (não detectado na escrita) | — | dupes no store | dedup retrieval | — |
| Metadata malformado | — | — | — | — | — |
| MCP failure | handler except | "ERROR: ..." str | texto (não raise) | — | — |
| Retrieval vazio | search | returns [] | MCP "No results" | — | — |

**Falha silenciosa chave**: `index_file` e `index_directory` retornam None/int sem distinguir "sanitizado-ok" de "quarentena" de "embedding-skip" — o caller não sabe quantos pontos entraram.

## 14. Idempotency analysis

| Operação | Mesmo input 2x | Implementação real | Risco |
|---|---|---|---|
| discovery | — | determinístico | — |
| sanitization | sim | deterministic | — |
| chunking | sim | determinístico (fixo) | — |
| embedding | sim (mesmo servidor) | — | — |
| upsert code | **NÃO** (path na hash, rename muda) | overwrite por colisão de id | dupes |
| upsert memory | **NÃO** (ts na hash) | novo point | dupes (dedup só no recall) |
| ingestion dir | **NÃO cross-run** (mtime dict in-process `_indexed_hashes:347`) | re-indexa tudo a cada run | custo, dupes |

## 15. Test reality matrix

| Feature | Teste | Mocked/Real | Prova |
|---|---|---|---|
| sanitize md/html/epub/pdf/scanned | test_doc_sanitize (22) | real files, mocks só store | contrato §28 |
| knowledge_schema bootstrap | test_knowledge_schema (9) | FakeStore | schema/indexes/wipe-guard |
| rag index sanitized | test_doc_sanitize index_file | FakeStore+LLM | sanitize→index |
| memory | test_llm etc. | mock | recall/remember |
| **E2E real** | `/tmp/e2e_bootstrap.py` (fora do repo!) | REAL Qdrant | bootstrap+search |
| **pilot reindex** | `/tmp/reindex_pilot.py` (fora!) | REAL | sanitize→index→retrieve |
| harness E2E | test_harness_e2e (integration) | real | — |

**Gap**: E2E real está em `/tmp` (não versionado) — não roda no `nix flake check`. Nenhum teste CI valida a integração Qdrant real.

## 16. Duplicated implementations

| A | B | Diferença | Quem usa | Convergir? |
|---|---|---|---|---|
| `QdrantStore.ensure_collection` (hardcoded) | `knowledge_schema.vector_config/ensure_collection` | schema 2ª definição | rag/memory vs novo | SIM |
| `build_payload` (novo) | payloads antigos (path/filename) | campos de proveniência | — vs rag/memory | SIM |
| `dense_key` (vector_store) | `sparse_vector` (rag) | ambos crc32 sparse | compartilhado | já convergem |

## 17. Configuration map

| Setting | Fonte | Default | Override |
|---|---|---|---|
| qdrant_url | Config | :6333 | env |
| embed_base_url/model/dim | Config | :8081/nomic/768 | env |
| collection code/memories/books | Config | code_index/memories/books | env |
| embed dim | Config | 768 | env (Risco: trocar dim sem recriar coleção → 400) |
| rerank_base_url | Config | :8082 | env |
| index_exclude_dirs | Config | muitos | env |

## 18. Observability gaps

- ingestão: `index_file` retorna last_payload ou None — sem contagem ok/quarentena/skip distinta.
- `index_directory` retorna int (total) sem quebrar por status.
- memory/recall: retorna hits, sem log de escrita.
- Nenhum evento de "ponto inserido"/"documento aceito/rejeitado" estruturado (só audit.jsonl do agent p/ shell).

## 19. Self-knowledge gaps

- Não há índice "o que está no Qdrant" consultável (count existe, mas sem lista de fontes/domínios).
- PROVENANCE.md (Books) e corpus.jsonl (inventário) existem mas NÃO são fonte consultada pelo runtime — o sistema não responde "onde está X" além do Qdrant.

## 20. Prioritized risks

### P0 — pode corromper dados / ingestão incorreta
1. **Identity crc32 32-bit + path-based** (rag:418, audiobook:46, memory:_stable_id) — colisões e dupes por rename. Migrar p/ `sha256(source_path + content_hash)` estável.
2. **`sanitize_document` só roda se `content is None`** (rag:375) — caller que passar `content=` bypassa sanitizer.
3. **`memory.clear()` deleta a collection inteira** (memory.py:230).

### P1 — pode produzir resultados incorretos
4. `_handle_rag_search` chama `ensure_collection` na LEITURA (mutação de schema em busca).
5. `vault_write` concatena nome sem sanitizar → path traversal.
6. Providência nova (`build_payload`) não aplicada aos pontos reais (rag/memory/audiobook) — cadeia incompleta.
7. `embed_dim` env-override sem recriar coleção → 400 silencioso.
8. Chunking janela fixa (não structure-aware) — perde tabelas/código como unidades.

### P2 — arquitetura/manutenção
9. Schema Qdrant duplicado (store hardcoded vs knowledge_schema).
10. E2E real em /tmp (não versionado) — sem cobertura CI da integração.
11. `recent()` ordena só página de scroll.
12. Obseservability: index_file/recall não distinguem ok/quarentena/skip.

### P3 — futuro
13. Reranker opcional não testado em matriz de retrieval.
14. Acquisição Wikipedia/Python (doc_sources) sem ingestão real.

## Critical contracts
- Sanitizer: `SanitizedDoc{status,text,provenance}` — única porta de documento (rag:375, audiobook).
- Embedding: nomic-embed-v2-moe :8081, 768, pooling mean — mesmo p/ index e query.
- Qdrant: dense nomeado `dense` 768 + sparse `bm25` idf; 3 collections (code/memories/books).
- Identidade: crc32 (DEVE migrar p/ hash de conteúdo).

## Potential data-corruption risks
- Colisão crc32 em ids (rename→dupe; memory→dupe).
- `memory.clear()` destrutivo por engano.
- Bypass sanitizer via `content=` explícito.

## Potential retrieval risks
- `ensure_collection` em leitura (mutação de schema).
- Dense-dominante RRF (5:1) pode afogar termos exatos (código/símbolos) que precisam do sparse.
- Filtro por domínio ausente no retrieval (só troca de collection via MCP).

## Potential sanitizer bypasses
- `content=` passado por caller de `index_file` (não usado hoje por index_directory, mas o contrato permite).

## Potential MCP bypasses
- `rag_search` faz QdrantStore inline + ensure_collection (não via service único).
- `vault_write` sem sanitização de path (traversal).

## Architecture duplications
- 2 definições de schema Qdrant (store vs knowledge_schema).
- 2 formatos de payload (antigo path/filename vs novo build_payload).

## Missing tests
- E2E Qdrant real versionado (não em /tmp).
- Teste de idempotência de ingestão cross-run.
- Teste de bypass sanitizer (content=).
- Teste de colisão de id / rename→dupe.
- Teste de `memory.clear()` (guard).
- Teste de path traversal em vault_write.

## Recommended next actions (para DEPOIS da reconstrução, não agora)
1. Migrar identidade de crc32 → `sha256(canonical_path + content_hash)`; estabilizar memory_id (sem timestamp).
2. Fazer sanitize obrigatório mesmo com `content=` (ou remover o param).
3. Unificar schema: `knowledge_schema` como fonte única; store delega.
4. Aplicar `build_payload` a todos os pontos (proveniência completa).
5. Guard em `memory.clear()`; sanitizar `vault_write`.
6. Estruturar observabilidade: contagem ok/quarentena/skip por ingestão.
7. Versionar os E2E reais em `tests/` como integration.# 21. ADDENDUM — SOURCE-OF-TRUTH / STATIC DEBT MAP (auditoria estática)

> Contribuição auxiliar (18/09) — análise de configuração dinâmica, sem tocar
> runtime/pipeline. Alimenta a consolidação §17-24 da missão pós-ingestão.
> Prioridade por princípio §24: runtime config > generated > docs > indexes.

## Context budget — VIOLAÇÃO (P1, 2 valores divergentes)

| Local | Valor |
|---|---|
| context_budget.py:257 (default) | 32000 |
| context_budget.py:283 (auto-detect sentinel) | 32000 |
| model_policy.py:29,83,92 | 32000 |
| hwdetect.py:253 | min(32768, ...) |
| hwprofile.py:115,286 | 32768 |
| provider_registry.py:49,74 | 32768 |
| llm.py:635 (fallback) | 32768 |
| **router real (bonsai)** | **49152** |

- model_policy.py:51 já documenta o BUG: "default 32000 mesmo com ctx=49152 no registry".
- Fonte de verdade deveria ser models.nix/registry; 8 pontos hardcoded, 2 valores.
- Mutation test §18 deve provar 1-mudança→todos-os-consumidores; hoje falha (drift).

## Embedding dimension — 3 definições (mesmo valor, mas não-derivadas)

| Local | Valor |
|---|---|
| config.py:71 | 768 (default, env-override) |
| vector_store.py:23 DEFAULT_DIM | 768 |
| knowledge_schema.py:38 EMBED_DIM | 768 |
- Trocar o modelo de embedding (dimensão muda) exige editar 3 lugares + recriar coleção. P1: env-override sem recriar → 400 silencioso.

## Chunk size — 2 hardcodes

| Local | Valor |
|---|---|
| rag.py:401 chunk_size | 1200 (janela fixa) |
| audiobook.py:939 chunk_chars | 1200 (target) |
- Sem fonte única; rag é janela fixa (não structure-aware), audiobook é alvo.

## Collection names — enum MCP ≠ config

- mcp_server.py:294 enum: [code, memories, books] — mas o código do código é code_index (config.py:74). O label MCP "code" ≠ collection real "code_index" (handler mapeia, mas a enum mente o nome físico). P3 (nomenclatura).

## Static inventories (risco §21/§32)

- scripts/corpus_inventory.py + corpus.jsonl (360 entradas) — útil como ponte, mas é SNAPSHOT não auto-regenerado (regenerar via script). Não é fonte de verdade do runtime.
- ~/Books/PROVENANCE.md (v2, 73/73) — derivável do fs; serve como provenance, não como config.
- Não duplicar: preferir git ls-files / os.walk em runtime a inventários estaticamente commitados.

## Recomendado (para a consolidação do outro agente, NÃO agora)
1. Criar fonte única de config (ex: models.nix/registry) e fazer context budget/embed_dim/chunk derivados.
2. Mutation test por valor crítico: mudar → validar consumidores.
3. Remover os 2 valores divergentes (32000/32768) → derivar do registry.
4. Alinhar enum MCP p/ code_index ou abstrair nome lógico.