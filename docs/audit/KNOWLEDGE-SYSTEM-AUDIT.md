# KNOWLEDGE-SYSTEM-AUDIT — Memory, RAG, Qdrant, Vault (2026-11-19)

> Fase 3 da missão contínua. Contratos extraídos do código que RODA no host
> (refs `arquivo:linha` do HEAD `3c0c4f20`) e de medições somente leitura no
> Qdrant de produção. Substitui o diagnóstico de 18/09
> (`docs/architecture/KNOWLEDGE_SYSTEM_ARCHITECTURE_AUDIT.md`) onde ele já
> não vale; o histórico fica preservado.

## 1. Contratos reais (estado medido)

| Camada | Implementação | Persistência | Identidade | Filtro de leitura |
|---|---|---|---|---|
| RAG (código/docs) | `core/rag.py` `HybridIndexer` | Qdrant `code_index` (275.724 pts) + `books` (11.379) | `stable_id("doc", source_sha256, i)` — 63 bits | híbrido dense+bm25, boosts |
| RAG (sessões) | `scripts/index_opencode_sessions.py` | Qdrant `sessions` (775) | `session_id` | híbrido |
| Memória episódica | `core/memory.py` `EpisodicMemory` | Qdrant `memories` (3.034) | `stable_id("mem", text)` — conteúdo, não ts | `recall`/`lessons`, dedup por texto, `superseded` |
| Vault | `core/vault.py` + `vault_cipher.py` | `~/.local/state/jarvis/vault` (570 .md) + Qdrant `vault` (102) | nome do arquivo + git | `vault_list/search` |
| Schema declarado | `core/knowledge_schema.py` | — (não importado por ninguém) | — | — |

Descoberta de arquivos: `rag.iter_indexable_files` com `.ragignore` +
`Config.index_exclude_dirs`. Sanitização: `doc_sanitize.sanitize_document`
(documentos) e `sanitize_text` (conteúdo explícito); código-fonte tem
leitura direta (`code-direct-read`) porque o normalizador colapsaria
indentação.

## 2. Problemas comprovados

### P1-1 — Versões antigas ficam no índice (CORRIGIDO com ferramenta)
O point id deriva do sha do conteúdo: cada edição grava ids novos e as
versões anteriores continuam recuperáveis. Medido em produção hoje:

| Coleção | Pontos | `current` | `stale` | `missing` | `no_identity` | Removível |
|---|---:|---:|---:|---:|---:|---:|
| `code_index` | 275.724 | 176.992 | 32.519 | 66.213 | 0 | 98.732 (35,8%) |
| `books` | 11.379 | 8.112 | 35 | 168 | 3.064 | 203 |

Exemplo pontual: `core/rag.py` tinha 7 versões (231 pontos) para 39 chunks
atuais; `core/memory.py`, 81 pontos para 16. O retrieval não distingue a
versão vigente — código velho pode vencer o top-k.

Correção: `core/rag_prune.py` + `jarvis rag-prune --collection code|books`
(default **dry-run**), com manifesto em `$JARVIS_STATE_DIR/rag-prune/`
antes de remover. `no_identity` **não** é removível: a coleção `books` não
guarda `path` por desenho (payload `book_id/chapter/text`), e tratá-la como
lixo apagaria 3.064 pontos legítimos. Indexação também ganhou prune opt-in
(`JARVIS_RAG_PRUNE_ON_INDEX=1`). O `--apply` em produção **não foi
executado**: exige autorização (§10.1).

### P1-2 — Consolidação noturna apagava memória (CORRIGIDO)
`EpisodicMemory.consolidate_memories` fazia `delete_points` nos perdedores
do cluster, e o timer `jarvis-consolidate` roda `consolidate --apply` todo
dia às 03:00. Contradizia o contrato documentado ("marca `superseded_by`,
nunca deleta", HANDOFF 25/09). Além disso o keeper era escolhido por
`payload["timestamp"]`, chave inexistente (o payload usa `ts`), então todo
cluster caía em `(0, len(text))` e o keeper virava o texto **maior**.

Correção: keeper = maior `ts`; perdedores recebem `superseded`,
`superseded_by`, `superseded_ts` via `set_payload` (o `recall` já filtra a
flag; limpar a flag reverte). O timer roda do source
(`PYTHONPATH=.../src`), então a correção vale no próximo 03:00 sem rebuild.

### P1-3 — Quarentena de documento grande (ABERTO, precisa de decisão)
`index_file` corta em chunks de 1.200 chars e embeda em lote
(`embed_batch`); o limite de contexto do nomic é 2.048 tokens. Chunk maior
que o ctx do embedder cai no fallback de metade e, se falhar de novo, é
**pulado em silêncio** (`continue`), sem entrada em `skipped`. Efeito:
documento grande pode ficar parcialmente indexado sem ninguém saber.
Próximo passo: registrar o motivo no `skipped` e devolver contagem
ok/quarentena/pulados no `index_directory` (P2 de observabilidade).

### P2-1 — `knowledge_schema.py` é um segundo schema não aplicado
Define `SCHEMA_VERSION = "2.0.0"`, payload canônico (`knowledge_domain`,
`source_type`, `authority`, `status`, ...) e payload indexes. Nenhum
módulo de produção o importa (`grep` sem consumidores fora do próprio
teste). O RAG grava outro payload (`path`, `document_id`, `chunk_id`,
`source_sha256`, `ext`, `sanitizer_version`, ...). Resultado: duas
verdades, uma delas morta. Decisão pendente: virar o schema executável
(ensure/indexes no bootstrap) ou rebaixar o arquivo a documento de
desenho com aviso no topo.

### P2-2 — `core/consolidate.py` sem consumidor
Implementa detect/apply por cosseno + heat, marca `superseded` (design
mais seguro), tem 145 linhas de teste e **nenhum** importador fora dos
testes. Agora que `memory.consolidate_memories` adotou o mesmo contrato de
marcação, os dois caminhos são redundantes. Decisão registrada: manter
como biblioteca candidata a canônica (heat/`superseded_by`), não deletar
nesta sessão; convergência entra no roadmap.

### P2-3 — `max_points` ignorado
`consolidate_memories(..., max_points=1000)` recebe o parâmetro e sempre
faz `scroll` com `limit: 1000` fixo. Cosmético hoje; vira bug se alguém
pedir menos para reduzir custo.

### P3-1 — Dedup de recall é por prefixo de texto
`recall` compara `text.strip().lower()[:500]`. Dois fatos que só diferem
depois do caractere 500 passam como distintos; dois textos iguais com
caixa diferente colapsam (desejado). Sem ação agora.

## 3. O que já estava corrigido desde 18/09 (verificado, não presumido)
- Bypass do sanitizer por `content=`: fechado com `sanitize_text`.
- `memory.clear()` destrutivo: exige `confirm=True`.
- `vault_write` path traversal: `PurePath(name).name` + rejeição de `/`,
  `\`, `.` e `..`.
- `ensure_collection` em leitura no MCP: removido; 404 vira erro com dica.
- IDs crc32: point ids usam `stable_id` (sha256 63 bits); crc32 restou só
  nos índices do sparse (limite u32 do Qdrant, degradação branda).

## 4. Fluxo entre as camadas (contrato explícito)
```
arquivo ──sanitize──> chunks ──embed──> Qdrant code_index/books
evento  ──remember──> Qdrant memories ──consolidate(marca)──> superseded
memories ──vault summarize──> vault/<YYYY-MM>.md ──git──> RAG vault/code_index
```
Sem ciclo de realimentação infinita: o resumo do vault vira `.md`
indexável, mas não é resumido de novo (o `summarize` lê `memories`, não o
vault). Proveniência existe no payload do RAG (`path`, `source_sha256`,
`ingested_at`, `sanitizer_version`) e falta no ponto de memória (só
`ts`/`kind`).

## 5. Comandos de verificação
```bash
# dry-run (não apaga), coleção de código ou livros
jarvis rag-prune --collection code
# aplicar (grava manifesto antes) — exige autorização do dono
jarvis rag-prune --collection code --apply
# testes do contrato
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_rag_prune.py \
  modules/ai/jarvis/tests/test_memory.py -q
```

## 6. Pendências desta fase
1. Autorização para `rag-prune --apply` em `code_index` (98.732 pontos
   removíveis) e `books` (203). Sem ela, o índice segue com 35,8% de
   conteúdo obsoleto.
2. Decidir o destino de `knowledge_schema.py` (executável ou documento).
3. Propagar motivo de chunk pulado para `skipped` (P1-3/P2 de
   observabilidade).
4. Índice de sessões (`sessions`, 775 pts) não tem prune: mesma classe de
   problema, payload diferente (`session_id`).
