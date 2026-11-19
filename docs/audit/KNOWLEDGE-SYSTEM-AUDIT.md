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
**1/5** retornou o documento esperado no top-8. Os其他 4 documentos estavam
**indexados** (`code_index/points/scroll` com filtro por path confirmou todos),
então o defeito é de **ranking**, não de cobertura. Exemplo: "veredito do
CYCLE-9 Harbor BLOCKED" devolveu CYCLE-8 e HARBOR-INTEGRATION, não o
`CYCLE-9-REPORT.md`. Correção exigida: avaliar boosts por nome de arquivo e
reranker antes de confiar no RAG para decisões.

## 4. O que NÃO é problema (verificado)
- `stable_id`: SHA-256 63 bits, não CRC32 (CRC32 foi substituído no P0-1).
- `_stable_id` da memória ignora timestamp de propósito ⇒ upsert idempotente.
- 570 notas do vault: 570 hashes únicos (nomes com caixa diferente ≠ duplicata).
- Vault cifra com Fernet opcional; `pessoal_*` coleções são produção, intocáveis.

## 5. Próximos passos (Fase 3)
1. Teste de recuperação RAG com perguntas de resposta conhecida nos doc reais
   (ex.: "qual o veredito do CYCLE-9?" → `docs/audit/CYCLE-9-REPORT.md`).
2. Verificar se `rag.py` reindexa quando o git muda (incremental) — procurar
   `content_hash` no caminho de indexação.
3. Decidir (com dono) se decisões validadas viram `remember_fact(kind=decision)`.
