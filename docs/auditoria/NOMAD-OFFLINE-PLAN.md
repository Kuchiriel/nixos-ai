# N.O.M.A.D — Offline Survival / Offline Information Capability for the JARVIS Stack

- status: **PLAN ONLY** — no product code changed, no commit, no download beyond <300 MB research budget
- date: 2026-11-07 · author: opencode-nomad-research · repo: `nixos-ai`
- inputs: research notes in `~/Books/papers/` (`project-nomad-offline-knowledge-server.md`, `survivalrag-offline-survival-knowledge-base.md`, `arxiv-2602.13229-pocket-rag-on-device-first-aid.md`, `arxiv-2511.01289-firstaidqa-synthetic-first-aid-dataset.md`, `arxiv-2602.00030-raptor-ai-disaster-ooda.md`, `arxiv-2604.21406-humdial-full-duplex.md`)
- IO measurements for §5: measured on this host, 2026-11-07 (raw numbers in §5.1)

---

## 1. What N.O.M.A.D is, and what we adopt

**Project N.O.M.A.D** (*Node for Offline Media, Archives, and Data*) — https://github.com/Crosstalk-Solutions/project-nomad — is an **offline-first knowledge & education server** by Crosstalk Solutions (Chris Sherwood), **Apache-2.0**, 42.5k stars. It is a **Docker Compose control plane** that installs and manages other open-source projects so the box works with the cable pulled: **Kiwix** (offline Wikipedia ZIM + survival guides), **Ollama + Qdrant** (local AI chat with document RAG), **Kolibri** (Khan Academy), **ProtoMaps/PMTiles** (offline maps), **CyberChef** (data tools), **FlatNotes** (notes). Management app = AdonisJS 6 + React/Inertia + TypeScript (~60k LOC, `admin/`), multi-stage Dockerfile, zero telemetry, no authentication by design. It has **no paper and no benchmark** — its claims are vendor claims.

> **Citation correction (important).** The owner cited arXiv **2604.21406** as *"Efficient Knowledge Storage and Retrieval for Long-Term Planning in Offline Scenarios"*. **That paper does not exist.** arXiv API returns **0 hits** for that title, for `ti:"Efficient Knowledge Storage"`, `ti:"Offline Scenarios"` and `all:"Long-Term Planning in Offline Scenarios"`. **2604.21406 is in fact** *"Full-Duplex Interaction in Spoken Dialogue Systems: A Comprehensive Study from the ICASSP 2026 HumDial Challenge"* — a **full-duplex speech benchmark** (100+ h dual-channel human recordings, Apache-2.0, HF test zip **1.8 GB**). It is highly relevant to our **voice duplex** work but is *not* an offline-knowledge system. The nearest *real* offline/survival papers are **2602.13229** (Pocket RAG), **2511.01289** (FirstAidQA), **2602.00030** (RAPTOR-AI).

### 1.1 Adopt / skip table (measured sizes)

| Artifact | Real size | Verdict |
|---|---|---|
| NOMAD repo clone | **29 MB** (20 MB worktree + 8.5 MB `.git`), 664 files, ~60k LOC TS | **SKIP the code** — 100 % redundant with our stack (we already run Qdrant :6333, llama.cpp embeddings :8081, reranker :8082, hybrid RAG, voice, terminal harness). Adopt the *catalogue metadata* only. |
| NOMAD `collections/*.json` | **110 KB**, 7 files | **ADOPT** — curated, versioned, provenance-labelled survival taxonomy; Apache-2.0 code + **public-domain** content (CDC / NIH-NHLBI / MedlinePlus-NLM / FDA / NCCIH). `home_remedies.json` (28.4 KB, 20 remedies) + `natural_remedies.json` (24.2 KB, 18 remedies) already carry `uses`/`how`/`evidence`/`cautions`/`sourceUrl`. |
| Kiwix ZIM "Water Treatment Library" | **20.0 MB** | **ADOPT** — downloaded to `/tmp/opencode/nomad-sample/zims/water_en.zim` and verified. |
| Kiwix ZIM "A Library of Knots" / "NHS Medicines A to Z" | **27 MB / 16 MB** | optional; skip (low voice value). |
| Kiwix ZIM full catalogue | **62 resources, 87.0 GB** | **DO NOT DOWNLOAD** — would go to `/home/nixos/Books/offline/` (or the relocated AI tree in §5). |
| Wikipedia ZIM `top-mini` / `top-nopic` / `all-mini` / `all-nopic` | **331 MB / 2,239 MB / 12,531 MB / ~50,000 MB** | **DO NOT DOWNLOAD** — `all-nopic` alone is ~50 GB and would eat the 385 GB free on `/`. |
| Kiwix ZIM "Ready.gov" | **2,429 MB** | candidate, phase 2 — official US preparedness content. |
| survivalRAG (bdkoeh) | **346.21 MB / 727 files** | **SKIP the download** (over budget) — **GPL-3.0** and pre-computed `nomic-embed-text` v1.5 vectors are incompatible with our `nomic-embed-text-v2-moe` query space. **Re-derive from the original public-domain sources instead.** One 12.1 MB chunk file was sampled to fix the schema. |
| FirstAidQA | **2.26 MB**, 5,500 QA pairs, CC BY 4.0 | **ADOPT as eval/regression corpus only** — no citations ⇒ cannot be the voice's safety-critical source. |
| HumDial-FDBench HF test zip | **1,818 MB** | **DO NOT DOWNLOAD** (over budget) — use the *protocol*, not the audio (§4.4). |
| Pocket RAG / RAPTOR-AI papers | 1.1 MB / 8.7 MB | **ADOPT the papers** (already in `~/Books/papers/`) — architecture references only; no code repo discoverable. |

---

## 2. Offline corpus → RAG ingestion

### 2.1 Collection
- New production collection: **`offline_survival`** (Qdrant, dim **768**, `cfg.embed_dim`), declared as `JARVIS_QDRANT_COLLECTION_OFFLINE` in `core/config.py` alongside `code_index` / `memories` / `books` / `vault`. **Do not** reuse `books` (that collection is the audiobook pipeline) and **do not** touch `memories` (protected by `nixos-ai/AGENTS.md`).
- `HybridSearch.search()` currently defaults to `[qdrant_collection_code, "books"]` (`core/rag.py:866`) — the offline collection must be searched **explicitly** (`collection="offline_survival"`), never as a default third member, so ordinary code queries do not get diluted by survival text.

### 2.2 Chunking and embedding (hard constraints already measured on this box)
- Embedding server :8081 has **n_ctx = 512 tokens**. `providers/embedding.py` uses **`CHUNK_CHARS = 800`, `OVERLAP_CHARS = 150`** (800 chars ≈ 380 tokens, safe margin). `rag.py` uses `chunk_size = 1200` for *code* (rich-content wrapper differs) — **the offline corpus must use 800**, not 1200, because the survival text is prose with accented PT-BR/en hyphenation (worse chars/token than ASCII). Batch ≤ **64 items/POST** and **no retry** (retry×timeout = the "silent hang" trap in `nixos-ai/AGENTS.md`). Chunk boundary: prefer paragraph/sentence breaks (`embedding.split_for_embedding` already does `\n\n` → `\n` → `". "`).
- **Re-embed everything locally.** survivalRAG's shipped vectors must not be reused (different embedding space); NOMAD's `TARGET_TOKENS_PER_CHUNK=1500` would 400 on our :8081.

### 2.3 Pipeline (mirrors `audiobook.py:index_book` — the pattern that already works)
1. Source of truth = one manifest (`~/Books/offline/corpus.json`) → generated markdown/txt files (**single-source + codegen discipline copied from NOMAD's `collections/*.json` → `gen:curated-data`**), so the shipped corpus can never drift from the source.
2. Extract → `doc_sanitize.sanitize_text` (**quarantine, not garbage**, same gate as `audiobook.py`) → chunk 800/150.
3. `llm.embed(rich)` where `rich = f"{source_id} — {section}\n{chunk}"` (the prefix carries provenance into the vector, as `audiobook.py` does).
4. `store.upsert("offline_survival", [...])` with payload: `source_id`, `source_title`, `section`, `page`, `url`, `license`, `content`, `document_id`, `chunk_id`, `source_sha256`, `content_hash`, `sanitizer_version`, `embedding_model`, `ingested_at`, `stability` (`text`).
5. Sparse side: `sparse_vector(sparse_terms(rich))` — **must be populated**: in survival text the exact term ("water purification", "filtro de água") matters more than semantic similarity (Pocket RAG: lexical filter + semantic rerank beats dense-only).

### 2.4 Corpus phases
- **Phase A (now, <5 MB total):** NOMAD `home_remedies.json` + `natural_remedies.json` (52.6 KB, public domain, with `cautions` + `sourceUrl`) + FirstAidQA (2.26 MB, eval-only) + Water Treatment ZIM (20 MB, if ZIM→text extraction lands). Enough to prove the whole loop end-to-end.
- **Phase B (owner approval, ~2.5 GB):** Kiwix "Ready.gov" ZIM (2,429 MB) + "Post Disaster Resource Library" (644 MB) + "Canadian Prepper: Bug Out Roll" (879 MB) — public-domain / CC sources with **provenance**. **Phase C (skip unless asked):** Wikipedia `top-mini` (331 MB) for general encyclopedic fallback.

## 3. Voice duplex client — answering "no internet" questions

### 3.1 The gap
`scripts/duplex-voice.py` exposes a **meta-tool** `do(action, input)`; the dispatcher (`duplex-voice.py:1520-1614`) routes by **substring matching on the action string**. `rag_search` already exists and works, but: (a) there is **no offline corpus** behind it, so "no internet" questions have nothing to hit; (b) the router can send a survival question to `web_search` (it only redirects to `rag_search` when the input mentions paper/arxiv/livro/código/script/document — **survival questions match none of those**); (c) there is **no "I don't have this offline"** answer path.

### 3.2 Proposed tool: `offline_search`
```
name: offline_search
params: { query: str, top_k: int = 5 }
returns (to the LLM, ≤ 800 chars like the other routes):
  "<one-sentence extractive answer> — Fonte: <source_id> §<section> p.<page> [<path>]"
  or "SEM FONTE OFFLINE para: <query>"
```
Rules baked into the handler (not the prompt):
1. **Extractive, not generative** — the tool returns the retrieved passage (trimmed to 1–2 sentences, ≤ 300 chars) plus provenance; the LLM only verbalizes. Rationale: our 4B-MTP is in the same SLM class as Pocket RAG's Qwen3-0.6B/Gemma3-1B — the accuracy in that regime comes from retrieval + citation, not model recall.
2. **Voice-friendly length** — answer ≤ ~40 spoken words. Our voice loop already burns 10–22 s in the LLM call, and Pocket RAG's whole TTFT on *faster* hardware is 3.7 s ⇒ the offline turn is **the slowest turn of the conversation**; the client must be patient, not the tool verbose.
3. **`cautions` is mandatory** — if the retrieved record has a `cautions` field (NOMAD remedy schema), append it even if the question did not ask. A contraindication dropped for brevity is a safety failure.
4. **No-hit is a first-class answer** — "SEM FONTE OFFLINE" (not a hallucination). Per HumDial-FDBench's *Rejection* category, withholding is correct behaviour.
5. **Never leaves the box** — the offline route has no network fallback. If it misses, it says so.
6. **Write-back** — a miss is recorded via `jarvis_remember`/`lessons` (asynchronous thread, like `remember` at `duplex-voice.py:1545-1555`) so corpus gaps become visible ("experience-driven" in the RAPTOR-AI sense, reusing the existing harness).

### 3.3 Routing (harness fix > prompt fix — the rule already applied at `duplex-voice.py:1558-1568`)
Add to the dispatcher, **before** the `web`/`rag` branch:
- `offline` / `sem internet` / `sem rede` → `offline_search`.
- survival/emergency lexicon (água/purificar/fogo/enchente/terremoto/bomba/primeiros socorros/bleeding/burn/water/flood/earthquake/emergency/shelter/survival) → `offline_search` **first**; only if it returns a miss may the caller fall back to `web_search` (and only when the owner has declared internet is up).
- Prompt line added to the meta-tool help: `do(action='offline_search', input='busca') → conhecimento offline (sem internet)`.
- **Deterministic test:** every one of the 5,500 FirstAidQA questions, spoken or typed, must route to `offline_search` (not `web_search`). That is a **routing metric**, cheap and offline — the one metric we can measure without a 6 GB VRAM experiment.
- **Text-only eval derived from HumDial-FDBench (no 1.8 GB download):** its 9 scenarios × 600 test items define a taxonomy of **interruption intents**; "Negation/Dissatisfaction", "Topic Switch", "Speech Directed to Others" are the cases our dispatcher can fail. Build a **text-only** regression set: prompt the voice LLM with an interrupted utterance + the tool list, assert which tool it picked. No audio, no GPU, no download.

---

## 4. Terminal harness (`modules/ai/jarvis/src/jarvis/cli/dev.py`)

### 4.1 New tool in the same registry
- **Schema** next to `rag_search` (`dev.py:2000`): `{"name": "offline_search", "parameters": {query: str, top_k?: int}}`.
- **Handler** next to the `rag_search` branch (`dev.py:1472`), same `HybridSearch` + `QdrantStore` + `LLMClient` stack, but with `collection="offline_survival"`, `top_k=5`, and the same output shaping (`[score] source_id §section` + excerpt). **Reuse, do not duplicate**: the retrieval core is `core/rag.py`; the offline tool is a *thin wrapper with a different collection + a stricter output contract*.

### 4.2 Also expose via `core/devtools.py`
`devtools.DEV_TOOLS` already carries `semantic_search`, `code_search`, `read_file`, … (`devtools.py:1341-1510`). Add `offline_search` there so the **voice client's dynamic route** (`duplex-voice.py:1576-1600` → `handle_dev_tool`) reaches it without a second implementation, and so `jarvis dev` and the MCP share one code path.

### 4.3 CLI surface
`jarvis rag-search --collection offline_survival "como purificar água"` — the MCP `rag_search` already accepts `collection` (`nixos-ai/AGENTS.md`), so no new MCP tool is strictly needed; the offline route is a **collection + output contract**, not a new transport.

---

## 5. Storage plan (PROPOSAL ONLY — nothing executed)

### 5.1 Measured IO reality (this host, 2026-11-07)

**Devices** (`lsblk -o NAME,SIZE,MODEL,MOUNTPOINT,ROTA,TRAN` + `/proc/mounts`):
| Mount | Device | Model | PCIe link | FS |
|---|---|---|---|---|
| `/` (and `/nix/store`) | `nvme1n1p2` | **SM2P41C8-512GC1** (Samsung) | **16.0 GT/s = PCIe 4.0 x4** | btrfs (`compress=zstd:3`, `subvol=/root`) |
| `/home` | `nvme0n1p1` | **IM2P33F3 NVMe ADATA 512GB** | **8.0 GT/s = PCIe 3.0 x4** | btrfs (`subvol=/home`) |
| `/tmp` | — | — | — | btrfs `subvol=/tmp` **on nvme1n1 (the FAST device)** |

**Read throughput** (`dd if=<file> of=/dev/null bs=8M count=N iflag=direct`, repeated runs):

| Path | File | Size | **qd1** | **qd4 aggregate** |
|---|---|---|---|---|
| `/home` (ADATA, PCIe 3.0) | `models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` | 21.2 GB | **1.9 GB/s** (1.6–1.9) | **1.57 GiB/s** (1604/1611 MiB/s, 2 runs) |
| `/home` (ADATA) | `.local/share/opencode/opencode.db` | 1.17 GB | **438–448 MB/s** | — |
| `/` (Samsung, PCIe 4.0) | `…NVIDIA-Linux-x86_64-615.78.08.run` | 530 MB | **4.1–4.2 GB/s** | **3.14–3.29 GiB/s** (3220/3368 MiB/s, 2 runs) |
| `/` (Samsung) | `…bge-reranker-v2-m3-Q4_K_M.gguf` | 438 MB | 3.8 GB/s | — |

**Random 4 K O_DIRECT reads** (2000 random offsets, single-thread): `/home` **4,748 IOPS** · `/` **5,870 IOPS** (+24 %).

**Verdict — the owner's belief HOLDS, and is confirmed by the hardware.** The fast NVMe bus (PCIe 4.0 x4, `/`) is **~2.2× faster sequentially** than the `/home` ADATA drive (PCIe 3.0 x4) for the same workload class, and **+24 % on random 4 K reads**. `/home` is a *slower-generation* drive, not just a different partition. And **the AI models (140 GB in `/home/nixos/models`) sit on the slower device** — the opposite of the desired layout.

Caveats (state honestly):
- The host was **busy** during these runs (load 5.4–6.4, 4–5 concurrent opencode sessions) ⇒ absolute numbers are pessimistic; the *ratio* is the reliable figure. `fio` is **not installed**; `dd` + Python `os.pread` were used instead.
- **qd4 does NOT beat qd1 on either device** (HOME 1.57 vs 1.9 GB/s; ROOT 3.2 vs 4.2 GB/s). Parallel streams *reduce* aggregate throughput here — consistent with btrfs compression + a host-side CPU bottleneck. ⇒ **the fast device wins by raw speed, not by queue depth**; a "spread the AI load across both disks" strategy is *not* supported by the data.
- `opencode.db` reads at only ~440 MB/s on `/home` (vs 1.9 GB/s for the GGUF on the same filesystem) — a **fragmented, actively-written SQLite file**, not a sequential-stream limit. This is the file that would benefit most from relocation (random-ish page access + WAL churn).### 5.2 Proposed relocation (NOT executed)

| Tree | Current | Size | Target | Why |
|---|---|---|---|---|
| `~/models` | `/home` (slow) | **140 GB** | `/opt/ai/models` (fast, `/`) | 2.2× faster model load + mmap page faults; **frees 140 GB of `/home`** (currently 71 % full, 143 GB free) |
| `~/.cache/huggingface` | `/home` | **13 GB** | `/opt/ai/cache/huggingface` | HF blobs are read-then-deleted; fast device |
| `~/.local/share/opencode` | `/home` | **9.1 GB** (`opencode-stable.db` 6.4 GB + `opencode.db` 1.1 GB + `log` 948 MB + `snapshot` 603 MB) | `/opt/ai/opencode-data` | the DB read at 440 MB/s is the worst offender |
| Qdrant storage | `/var/lib/private/qdrant/storage` — **already on the FAST device** (`/`, via `/var/lib/qdrant → private/qdrant`) | **793 MB** | **no move needed** ✅ | already optimal |
| `/tmp/opencode` | **already on the fast device** (`/`, `subvol=/tmp`) | 9.2 GB | **no move needed** ✅ | already optimal |
| `~/Books` | `/home` | 1.3 GB | keep | plain storage, fits the owner's split |
| `~/projects` | `/home` | 50 GB | keep | git repos, plain storage (AGENTS.md: independent git repos) |

**Exact commands (proposal):**
```bash
# 0) pre-flight
df -h / /home; sudo btrfs subvolume create /opt/ai     # same FS as / (fast)

# 1) models  (140 GB, the big one) — stop the llama servers first
sudo systemctl stop jarvis.target                     # NO restart of llama-server mid-session
sudo rsync -aHAX --info=progress2 /home/nixos/models/ /opt/ai/models/
sudo mv /home/nixos/models /home/nixos/models.old      # keep 1 reboot as the revert
sudo ln -s /opt/ai/models /home/nixos/models           # symlink ⇒ zero config edits
# verify BEFORE deleting models.old:
diff <(sudo find /home/nixos/models.old -type f | wc -l) <(sudo find /opt/ai/models -type f | wc -l)

# 2) HF cache
sudo mkdir -p /opt/ai/cache/huggingface
sudo rsync -aHAX /home/nixos/.cache/huggingface/ /opt/ai/cache/huggingface/
# re-point via HF_HOME (no code change; HF reads the env var)

# 3) opencode data dir — the wrapper honours XDG_DATA_HOME + OPENCODE_DB
sudo rsync -aHAX /home/nixos/.local/share/opencode/ /opt/ai/opencode-data/
export XDG_DATA_HOME=/opt/ai            # ⇒ opencode resolves $XDG_DATA_HOME/opencode/
export OPENCODE_DB=opencode-stable.db   # preserve the nixpkgs legacy-DB workaround
```
**What references these paths (checked):**
- `modules/ai/models.nix` — ~12 `modelFile = "/home/nixos/models/…"` + 2 `"/home/nixos/models/loras/…"` entries; `layaModelDir = "/home/nixos/models/laya-ft"` (line 1352). `modules/ai/package.nix:9` — `aiModels ? { layaModelDir = "/home/nixos/models/laya-ft"; }`.
- `modules/services/llama-cpp.nix:159` — `ReadWritePaths = [ "/home/nixos/models" … ]`; `modules/services/whisper-server.nix:136` — `ReadWritePaths = ["/home/nixos/models" "/tmp/opencode"]`.
- `core/laya_classifier.py:30` — `LAYA_MODEL_DIR` env, default `/home/nixos/models/laya-ft`.
- `home-manager/home.nix:263-267` — `~/.local/share/opencode/auth.json` (the **data dir** ⇒ moves with `XDG_DATA_HOME`); `home-manager/modules/session-snapshot.nix` — comment references `~/.local/share/opencode/opencode.db`.
- `~/.config/opencode/opencode.json` is a **symlink into `/nix/store`** (managed by `home-manager/home.nix`) ⇒ **never edit it directly**; edit the generator.

⇒ **A symlink at `/home/nixos/models` keeps every one of those paths valid with zero code edits.** That is the single decision that makes this plan low-risk.

**Risks & downtime:**
- **Downtime:** the `rsync` of 140 GB at ~1.5 GB/s write ≈ **90–160 s** of I/O; the move needs the llama servers stopped (they mmap the GGUF) ⇒ **one voice/LLM outage of a few minutes**. `/home` gains 140 GB free (→ ~283 GB free); `/` loses 140 GB (385 GB → ~245 GB free). Both stay comfortable.
- **The `rebuild-host.sh` trap**: the flake only sees the **git index** ⇒ `git add -A` + `git ls-files` before any build. A rebuild during the move would fail on a missing `/home/nixos/models`.- **Never edit `/nix/store`** (AGENTS.md) — the `/nix` subvolume is on the fast device and is **not** part of this proposal. **Repos are independent git repos** — moving `~/models` (not a repo) touches no repo; `~/Books` and `~/projects` **stay put**.
- **Revert:** `sudo systemctl stop jarvis.target; sudo rm /home/nixos/models; sudo mv /home/nixos/models.old /home/nixos/models; sudo systemctl start jarvis.target` — the `.old` copy is retained for one reboot cycle. For the opencode data dir: unset `XDG_DATA_HOME`/`OPENCODE_DB`, `rsync -aHAX /opt/ai/opencode-data/ ~/.local/share/opencode/`. **Measure before/after**: `df -h` both, plus re-run the `dd` table above to confirm the model file now reads at ~4 GB/s.

---

## 6. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Disk fill on `/`** — moving 140 GB of models to a device with 385 GB free (→245 GB) while `/home` is at 71 % (143 GB free) | M | the swap frees `/home`; re-check `df` before and after; the full Kiwix catalogue (87 GB) + Wikipedia all-nopic (50 GB) must **not** be added blindly |
| **Corpus correctness / hallucinated first aid** | **H** | extractive answers with per-chunk provenance; `cautions` always spoken; no-hit is an explicit answer; **the corpus must be public-domain / CC** — survivalRAG is GPL-3.0 and must be re-derived, not vendored |
| **Embedding mismatch** (survivalRAG v1.5 vectors vs our v2-moe) | H | re-embed everything locally at 800 chars; never import foreign vectors |
| **RAM** — 31 GB total, currently 14 GB used; the 07/11 checkpoint recorded a **memory-thrash + OOM event** (load 33, swap 8.9 GB, LLM killed 19×) | **H** | the offline turn adds retrieval + a generation that is already the slowest in the stack; run the corpus indexer **as a background job at low priority**, never concurrent with a voice session; close opencode sessions before a heavy ingest |
| **VRAM 6 GB, one heavy job at a time** | H | the offline path uses the *existing* LLM on :8080 — it adds **no** model. Ingesting a 20 MB corpus is CPU/IO-bound, not GPU-bound. Never start a second llama-server for offline queries |
| **:8081 embedding ceiling (512 tokens)** | M | 800-char chunks; ≤64 items/POST; no retry (silent-hang trap) |
| **Voice latency** — offline turn ≈ retrieval (0.3–1 s) + generation (10–22 s) | M | short extractive answers; the client already tolerates slow turns; never route offline queries to `web_search` (which would be *slower* and fail outright when the internet is down) |
| **Routing regression** — adding a new branch to the `do(action=…)` dispatcher | M | the 5,500-question FirstAidQA routing regression set; the existing dispatcher is substring-based, so add the offline branch **before** the `web`/`rag` branch and keep the fallback explicit |
| **🔴 P0 bug found: `_target_extension` mis-parses dotted acronyms** — `rag.py:456` does `re.search(r'\.([a-zA-Z][a-zA-Z0-9]{0,3})\b', query)` and turns any dotted capitalised token into a **file-extension filter**. Measured: `"N.O.M.A.D offline survival Kiwix"` → ext `.o`; `"S.O.S. protocol"` → `.o`; `"C.A.T. bandage"` → `.a` ⇒ **zero results**. `search()` then passes that as `ext_filter` to Qdrant ⇒ the query is silently filtered out. A survival corpus is *full* of dotted designations (FM 3-11.4, ATTP 3-97.11, TC 4-02.1) ⇒ this would break the flagship use case | **H** | **must be fixed before the offline route ships**: require the dot to be preceded by a word char **and** the extension to be a known one (or drop the heuristic when the query has no known extension), or apply the filter only when the query looks like a filename. Until then, offline queries must avoid dotted tokens — which is why the eval set (§3.3) must include them |
| **Licence contamination** — GPL-3.0 survivalRAG, CC-BY book seeds (FirstAidQA), non-redistributable creator packs | H | keep the offline corpus in Apache/MIT-compatible + public-domain/CC sources; record `license` in every chunk payload; do not vendor GPL data into the product repo |
| **`/nix/store` must never be edited** | — | the proposal touches only `/opt/ai` (new subvolume) + `~/.local` + `~/.cache`; the nix store is untouched |

---

## 7. What was NOT done (explicit)

- **No multi-GB download.** Not fetched: Wikipedia ZIMs (331 MB / 2,239 MB / 12,531 MB / ~50 GB), the full Kiwix catalogue (87 GB), Ready.gov (2,429 MB), the HumDial test zip (1,818 MB), survivalRAG (346 MB), any model weights (llama3.1:8b 4.9 GB, nomic-embed-text 274 MB — we already have nomic-embed-text-v2-moe).
- **No product code modified.** No change to `rag.py`, `config.py`, `dev.py`, `devtools.py`, `duplex-voice.py`, `audiobook.py`, `models.nix`. **No relocation executed** — `/opt/ai` was **not** created; nothing was moved, rsynced or symlinked. **No new dependency**, no `pip install`, no `nixos-rebuild`, no service restart.
- **No commit.** `docs/auditoria/NOMAD-OFFLINE-PLAN.md` is a new untracked file. (`modules/ai/jarvis/src/jarvis/coord_http.py` was modified in `git status` at session start — **another agent's** work; not touched, not staged. It has since been committed by its owner.) Research artefacts live **outside** the product repos: `/tmp/opencode/nomad-sample/` (49 MB) and `~/Books/papers/` (6 new notes + 4 PDFs).
