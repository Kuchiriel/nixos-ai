# Recon knowledge substrate (@general subagent)

- **sessão:** `ses_f3f3c6ab0ffe0IgsdAzv2PCdrc`
- **quando:** 2026-09-20 21:40 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 13 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai, reconstruct the KNOWLEDGE SUBSTRATE of the jarvis AI system as it exists TODAY (repo is source of truth, not docs). Code lives in modules/ai/jarvis/src/jarvis/. Trace end-to-end: document ingestion (doc_sanitize.py, doc_sources.py, knowledge_schema.py, scripts/ingest_books.py), chunking, embedding (which model/service/port), Qdrant integration (collections, schema, which module writes/reads), retrieval path (eval_rag.py, rag tool in MCP), episodic memory (core/memory.py: store/recall/lessons API, backend), lessons injection (where in agent.py loop), vault/self-knowledge (files, search). For EACH stage report: source file + key functions, inputs/outputs, persistence, is it tested (which test file), can it fail silently, is there observability/telemetry. Return a compact structured map (component | file | in→out | persistence | tests | silent-failure risk). Do NOT modify anything. Research only.

---

## · ?

Rebuilding the live knowledge map — tracing ingestion to retrieval in the repo.

---

## · ?

First five core files show the shape — now pulling the wiring for embeddings, storage, and recall.

---

## · ?

Indexing and memory paths are clear — now checking agent wiring, retrieval tools, and observability.

---

## · ?

# JARVIS Knowledge Substrate — as-built TODAY (repo = truth)

> `scripts/ingest_books.py` **does not exist** on disk (`modules/ai/jarvis/scripts/` absent). Live books path is `core/audiobook.py::index_book/sweep_books`, auto-called from `mcp_server._handle_rag_index`. The `scripts/ingest_books.py` string appears only in a docstring.

**Services (from `core/config.py` + `modules/ai/models.nix`):**
Embedding = `nomic-embed-text-v2-moe Q8_0` (768d, ctx 2048) via llama-server `--embeddings` on **:8081** (`/v1/embeddings`). Reranker = `bge-reranker-v2-m3 Q4_K_M` on **:8082** (`/rerank`). LLM router **:8080**. Qdrant **:6333**. All vector traffic via `providers/llm.py::LLMClient.embed()` → `providers/llm_llama_cpp.py::LlamaCppBackend.embed()` (with `_truncate_for_embedding`, circuit-breaker) and `providers/vector_store.py::QdrantStore`.

## Structured map

| Component | File + key fns | In → Out | Persistence | Tests | Silent-failure risk + observability |
|---|---|---|---|---|---|
| Acquisition (selective, no bulk download) | `core/doc_sources.py`: `AcquisitionSpec.validate/dest_path`, `verify_local_file`, `discover_nixos_docs` | spec(url+sha256+cap) → validated spec / local availability dict | `$STATE/sanitize/sources/{wikipedia,python,nixos}/` dirs only (no downloads here) | none found (no `test_doc_sources`) | Low — pure validation, returns `errs`/`{ok:False}` explicitly. No telemetry. |
| Sanitize (gate before any index) | `core/doc_sanitize.py`: `sanitize_document(path)`, `sanitize_text(txt)`, `detect_format/extract/normalize_text/validate_normalized/link_terms` | raw file → `SanitizedDoc(status=ok\|quarantine, text, reason, provenance)` | `$STATE/sanitize/manifests.jsonl` (all) + `quarantine/<sha>.json` (no body); intermediate stages NOT persisted | `test_doc_sanitize.py` | **Medium** — quarantine returns `None` upstream with same signature as "skipped"; only trace is manifest JSONL. No metric counter. Obs: manifest + `output_sha256/output_chars`. |
| Code chunk+index (WRITE code_index) | `core/rag.py::HybridIndexer.index_file/index_directory`, `extract_facts/build_rich_content/sparse_terms/sparse_vector`, `iter_indexable_files` | file → N chunks (1200 chars; code exts bypass sanitizer via `code-direct-read`, others via `sanitize_document`) → `LLMClient.embed(rich)` → upsert | Qdrant `code_index` (named `dense`+`bm25`); payload: `path,chunk_id,chunk_index,filename,ext,facts,content(≤1200ch),source_sha256,content_hash,sanitizer_version,ingested_at,embedding_model`; in-mem `_indexed_hashes[path]=mtime` skip | `test_rag.py`, `test_rag_diversify.py`, `test_knowledge_schema.py` | **High** — `return None` on quarantine/OSError/embed-fail/mtime-skip (indistinguishable); per-chunk `continue` on embed fail; `except→halve chunk→continue`. Obs: `core/logging.py::Logger.emit` JSONL only, no per-file counters. |
| Books ingest (WRITE books) | `core/audiobook.py`: `index_book(book,chunk_chars=1200)`, `sweep_books(limit=3)`, `search_books`, `extract_text/chunk_text/get_content_chapters` | `~/Books/*.pdf` + `~/Books/harness/*.md` → `sanitize_text` → chapter-split → 1200ch chunks → embed → upsert | Qdrant `books` (payload: `book,chapter,title,chunk_index,content,document_id,chunk_id,source_sha256,content_hash,…`); progress log `BOOKS_INGEST_LOG=…/session-2026-09-18/logs/books-batch.jsonl`; id `stable_id("book",sha,ch,i)` | `test_book_rag.py`, `test_book_tools.py` | **High** — `sweep_books` skips on log/exception (`except OSError: pass`); `index_book` returns `{ok:False}` dict, caller in `_handle_rag_index` only appends text. Obs: batch JSONL log only. |
| Schema/bootstrap (3 collections) | `core/knowledge_schema.py`: `ensure_collection(store,name)`, `vector_config`, `build_payload`, `wipe_collections`; `COLLECTIONS={code_index,memories,books}` | — → Qdrant collections `dense(768,Cosine)+sparse bm25/idf` + keyword/datetime payload indexes | Qdrant server-side; `SCHEMA_VERSION=2.0.0`; idempotent (no wipe without `backup_verified=True`) | `test_knowledge_schema.py` | Low — bootstrap raises explicit `RuntimeError` on 15s index timeout; fake stores skip verification. Obs: `store.info()` payload_schema check. |
| Qdrant transport | `providers/vector_store.py::QdrantStore`: `ensure_collection/upsert/search/search_hybrid/prefetch+RRF/count/delete_points` | (dense vec + `{indices,values}` sparse) → fused hits | Qdrant `:6333` (server data, outside repo) | covered indirectly via `test_rag/memory/book` with fakes | Medium — `search_hybrid` dense-dominant (5:1) + `ext_filter`; connection errors propagate as `VectorStoreError` (good) except where callers swallow. |
| Retrieval code (READ) | `core/rag.py::HybridSearch.search`, `_rerank_candidates`, `apply_legacy_boosts`, `diversify_by_source`; `mcp_server._handle_rag_search/_handle_rag_index` (tool `jarvis_rag_search`, collections `code\|memories\|books`) | query → embed → `search_hybrid(top_k×4)` → legacy boosts (filename sovereignty +100k, word/path, test/sh penalty) → rerank top-5 (350ch, ~1.5s) → diversify(0.95) → `HybridHit[path,score,payload]` | none (read-only; audit P1-4: no ensure on read, 404 → "run rag_index") | `test_rag.py`, `test_rag_diversify.py`, `test_reranker.py`, `test_mcp_tools_e2e.py`, `test_eval_rag.py` | **High** — `embed→None` returns `[]`→"No results found"; `_rerank_candidates` has **explicit silent fallback** (`except Exception: return candidates`); diversify/boosts deterministic. Obs: `core/eval_rag.py::evaluate` (Precision/Recall/NDCG@k, `RAG_QUERIES` 11 cases, `jarvis eval-rag --seed`), `core/benchmark.py` (latency only). |
| Eval retrieval quality | `core/eval_rag.py`: `evaluate(search_fn)`, `_ndcg_at_k`, `_norm` | `search_fn(query,top_k)` → `EvalResult(precision,recall,ndcg,error)` | none (in-mem); ground truth = 11 hardcoded `(query,[paths])` | `test_eval_rag.py` | Low — `except→res.error` truncated 120ch, never raises. Obs: IS the observability for retrieval. |
| Episodic memory (WRITE+READ memories) | `core/memory.py::EpisodicMemory`: `remember(event)`, `remember_lesson(task/error/fix)`, `remember_fact`, `recall(query,top_k,kinds)`, `lessons(query)`, `recent/forget_task/count/clear` | event text → embed → upsert `memories`; query → hybrid search (top_k×3) → dedup → hits / `STATE(lesson…)` string | Qdrant `memories` (payload `kind,text,task,error_pattern,fix,ts,iso`); id `stable_id("mem",text)` (upsert-overwrite); `remember_lesson` supersedes same task via `forget_task` | `test_memory.py` | **High** — `remember` returns `None` on empty/embed-fail; `recall/recent/count/forget_task` swallow to `[]/0`; `lessons` returns `""` on miss. Obs: none beyond `Logger`; `count()` exists but no dashboard. |
| Lessons injection (agent loop) | `core/agent.py` (~L1125-1134, in system-prompt build before loop): `self.memory.lessons(prompt, top_k=3)` → appends `AVOID (past errors):…` | prompt → memory query → system prompt augmentation (cap 500 chars in `lessons()`) | none (runtime prompt only) | `test_agent.py` (partial), `test_memory.py` | **High (by design)** — whole block wrapped in `try/except: pass`; injection failure invisible, agent just runs without lessons. No log/metric on hit/miss. |
| Vault / long-term synthesis | `core/vault.py::MemoryVault`: `summarize(since_days=7)`, `_collect_events/_format_events`, `list_notes`, `_month_file`, `_git` | `memories.recent` (7d window) → LLM `chat(_SUMMARY_PROMPT)` → append `vault/YYYY-MM.md` + `git add/commit` + `remember_fact(summary)` | `vault_dir` (`~/.local/state/jarvis/vault`, `JARVIS_VAULT_DIR`) markdown + own `.git`; search path = `recall` (summary re-embedded as fact) + `list_notes` | `test_vault.py`, `test_mcp_vault_search.py` | **Medium** — `_git()` explicitly "falha silenciosa" (returns bool, unchecked); `summarize` returns `{written:False, reason: llm_error/no_events}` (good); telegram notify swallowed. Obs: return dict + committed md file. |
| Vault MCP tools (separate Obsidian vault!) | `mcp_server.py`: `jarvis_vault_{list,write,sync_obsidian,sync_hackmd,search_obsidian,status}` → `~/vaults/projects/nixos-ai` via rg/git, **not** `MemoryVault` | note name/content → md files under `~/vaults/…` | `~/vaults/projects/nixos-ai/*.md` + HackMD sync | `test_mcp_vault_search.py`, `test_handoff.py` | Medium — two "vaults" with same name, different stores (memory-vault vs obsidian-vault); search_obsidian is rg-based, no semantic link to Qdrant. |

## Cross-cutting: observability / telemetry

- `core/logging.py::Logger.emit/read_events/compute_metrics` — JSONL per-module logs; no central metrics exporter.
- `core/doctor.py`, `core/health_monitor.py`, `cli/main.py::jarvis doctor/status` — service health (Qdrant/embedding/LLM reachability), not per-stage knowledge metrics.
- `sanitize/manifests.jsonl` + `books-batch.jsonl` — only ingestion audit trails; nothing counts quarantine-rate, embed-fail-rate, recall-hit-rate in production path.
- Net: **every read path degrades to empty string / "No results found" and the agent continues** (`agent.py`, `search`, `recall`, `lessons`, `_rerank`). Only `eval_rag --seed` + benchmark logs give quality signal, manually invoked.

---

