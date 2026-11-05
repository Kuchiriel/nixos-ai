# Action plan — 2026-11-02 (owner: "you decide the order")

> Merged plan for the missions: (1) doubled MCP prefix, (2) LLM-facing text in
> English, (3) naming conventions, (4) the Codacus video → best LLM/flags/forks
> for our hardware, (5) FluidVoice → duplex cascade/voice, (6) looping
> transformers / NVIDIA "Dory". Lane owner for 1–3: `coord-naming`
> (`nixos-ai/harness-naming`); 4–6 are being researched in parallel.
> **Everything an LLM reads is English** (owner directive).

## What the hardware actually allows (the constraint that decides everything)

| Resource | Reality | Consequence |
|---|---|---|
| VRAM | RTX 4050 Laptop, **6141 MiB** — and **5.3 GB is already in use** by the running services (embeddings 446 MiB + the 4B-MTP llama-server 4834 MiB) | only ~0.5 GB free right now; a new model must either displace the running ones or live in RAM |
| RAM | 31 GB total, ~9–11 GB available | the video's own conclusion: at 6 GB VRAM, "go with the big one that leans on your RAM" (MoE experts ≈ 20 GB for Qwen3.6-35B-A3B) |
| CPU | hybrid 6 P + 4 E cores | threads = **half the cores** (`-t 6`) — corroborated by the video (libgomp barrier spin at `-t 12`: 64,8% of samples) and by our own measurement (`-t 6` = 16,4 t/s vs `-t 12` = 7,9 t/s) |
| Models in production | 4B-MTP+LoRA (default, :8092), 35B-A3B (MoE), embeddings :8081, reranker :8082, router :8080 | any new model is a **tier**, not a replacement, until measured |

## Phase 0 — DONE today (no risk, no downloads)

1. **Doubled prefix killed.** Root cause: opencode exposes every MCP tool as
   `<server-key>_<tool>`; our server was `jarvis` and the tools were also
   `jarvis_*`. The 37 tools now register with canonical names → exposed
   `jarvis_rehydrate` (verified in `opencode.db`); legacy names accepted for
   one deprecation cycle. Suite: 1842 passed (1 pre-existing failure).
2. **All LLM-facing text translated to English**: injected harness rule +
   pinned guards + compaction memory (plugin `memory.js`), the rehydrate tool
   output, the `opencode-coordination` skill, root + nixos-ai `AGENTS.md`.
3. **Naming conventions + rename map** (`docs/NAMING-CONVENTIONS.md`):
   measured inventory of the 60+ repos, the market rules we already match
   (src-layout, ADR, 12-factor/NixOps, Conventional Commits) and the ones we
   break (DNS-1123 repo names, pt-BR doc names, `docs/audit` vs
   `docs/auditoria`, model-id vs profile-alias mixing).
4. **Video digested** (`~/Books/videos/tek-IY9BRWc/DIGEST.md`, EN, timestamps
   + verbatim quotes).

## Phase 1 — Benchmark what we already have (cheapest, highest information)

*No downloads.* The video's flags are mostly **already in upstream llama.cpp**
(`--moe-cache-mib` = PR ggml-org/llama.cpp#29887; `--fit-target`; `-ctk/-ctv
q8_0`), so the question is not "which fork" but "do our builds have them and
what do they buy on this card".

1. Feature-check our three llama.cpp builds (upstream `llama.cpp`,
   `ik_llama.cpp`, `prism-llama.cpp`): does each expose `--moe-cache-mib`,
   `--fit-target`, `-ctk/-ctv`, `-ot attn_v_exps=CPU`?
2. Measure Qwen3.6-35B-A3B (already downloaded) on the 6 GB card with the
   video's ladder: `--fit-target 512` · `--moe-cache-mib 2048` · `-ub 1024` vs
   512 · `-ctk/-ctv q8_0` vs f16 · `-t 6` vs `-t 10` · `--load-mode mmap`.
   Metrics: **TTFT, prefill t/s, decode t/s, VRAM/RAM peak** (same harness
   as the existing benchmarks — reuse, don't invent).
3. Same metrics for the current default (4B-MTP) → answer the question the
   video raises for us: is the 35B MoE better as the **default**, or only as a
   "thinking" tier, given that voice needs low TTFT?
4. Only then decide about downloading anything new (the video's 6 GB pick is
   the model we already have; the 16 GB pick — Qwen3.8-27B GSQ RCO, IQ3_S
   ~12 GB — is *out of reach* on 6 GB VRAM and would be RAM-only).

**Gate:** if the 35B MoE gives ≥ the video's numbers (17 t/s class) at
TTFT ≤ 150 ms with `-t 6`, it becomes the candidate for the duplex/voice tier
behind the 4B; if not, the 4B-MTP stays and we stop.

## Phase 2 — Dory / looping transformers (feasibility before enthusiasm)

Research questions (papers + model card): what is the architecture (recurrent
depth vs looped layers), what is the **measured** TTFT/prefill on consumer
hardware, what quantizations exist, what is the memory profile (weights vs
activation cache), and does it need an exotic kernel (the fork that matters
may be the one with the looped-mamba/SSM kernel, not llama.cpp).

**Hard gate for our box:** 6 GB VRAM with ~5 GB already occupied, 31 GB RAM.
A looping-transformer model wins for us only if it (a) fits in < 6 GB VRAM or
runs acceptably from RAM with low TTFT, (b) is available in a GGUF/llama.cpp-
compatible build (or has a fork that is cheap to build), and (c) beats the
4B-MTP on the **voice** metric (TTFT + streaming), not on a leaderboard.
Paper claims of "beats 27B" are irrelevant if the latency is 400 ms.

## Phase 3 — FluidVoice (extract, do not adopt wholesale)

Our duplex cascade already exists (`DuplexCascade/` reference implementation,
paper note `~/Books/papers/duplexcascade-2603.09180.md`, streaming ASR +
micro-turn LoRA + the Laya integration still to be tested). FluidVoice is
worth downloading **only if** it ships something measurable we lack: better
barge-in/turn-taking, streaming ASR, or duplex audio transport. Plan: read
its architecture, list 3 candidate deltas, implement at most one, measure
with the existing `duplex-eval.py` harness. No wholesale fork — our stack has
working pieces (Qwen 4B MTP + LoRA micro-turn + whisper-streaming).

## Phase 4 — Renames (batch, after the code moves, so diffs stay readable)

Execute `docs/NAMING-CONVENTIONS.md` §4 in small batches (one logical change
per commit, `git mv` only, link targets verified, old names kept as aliases):
1. root repos that break DNS-1123 (`Wurm Ultimate`, `AI_SYSTEM`, `LLM`,
   `OTServer_UPGRADE`, PascalCase ones) — archived/low-risk first;
2. `docs/auditoria` → `docs/audit` + the pt-BR doc file names;
3. model ids vs profiles in `modules/ai/models.nix` (the source of truth):
   `qwen3.5-4b-mtp-lora` + profile `default`, `qwen3.6-35b-a3b` + profile
   `duplex`; keep `bonsai`/`qwen-fast` as aliases.

## Phase 5 — English sweep of the remaining LLM-facing surfaces

The other lane: JARVIS core prompts, personas, tool descriptions, the `make`
tool's pt-BR error strings, voice-mode prompts. Same rule, same checklist
(`grep -r` for Portuguese in prompts/descriptions/outputs).

## Cross-cutting rules for every phase

- **Papers first** (owner directive 20/10): Dory and FluidVoice are research
  subjects — read the papers/model cards before touching code.
- **One heavy job at a time**; the GPU has 6 GB and the RAM is shared.
- **Measure, don't trust** (AGENTS.md): the 4B model showed that a plausible
  benchmark can be an artifact (the opencode-summary imitation loop).
- **Every change keeps the old name working** for one cycle; no breaking
  renames in the same commit as a behaviour change.
- **Checkpoint per era** (queue + RAG + memory + vault) so any agent can
  resume from the state, not from the chat.
