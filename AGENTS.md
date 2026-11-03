# AGENTS.md — JARVIS operational context (nixos-ai)

> Read by every agent at startup. **Target: <150 lines / ~2000 tokens.**
> House rule: only what **changes behavior** and is **not
> inferable from the code** lives here. History, measurements and
> "why" go to `docs/` and enter via link.
> Basis: ETH Zurich (arXiv 2602.11988) measured that an inflated
> context file **costs +19-23%** and loses success rate; plus the
> *"too obedient"* effect (agent obeys an irrelevant instruction and
> does more work solving less). Hence: no directory trees, no
> style prose, no lists.

## PROHIBITIONS (read this first — largest blast radius)

1. **NEVER delete data.** Zero `rm`, `delete_collection`, `drop_collection`
   on material you didn't create in the last minutes. Use
   `core.safe_archive.archive_then_delete()`: copy → **read back** →
   check count and hash → only then remove. Qdrant once accepted a
   write (HTTP 200) and didn't persist; whoever trusted the status lost 6 points.
   Always start with `dry_run=True`. Accept **explicit IDs**, never
   substring filters (filters match text that merely *mentions* the term).
2. **Production collections** — `code_index`, `memories`, `books`, `vault`
   and the per-space ones (`pessoal_*`, `moe_*`, `qwen4b_*`). `memories` is the
   agent's memory. **Don't write, don't rename, don't remove.**
3. **Tests only touch `jarvis_test_*`**, always derived:
   `dataclasses.replace(Config(), qdrant_collection_code="jarvis_test_x")`.
   The `modules/ai/jarvis/tests/test_test_isolation.py` guard fails the build on violation — it
   exists because someone wiped 1263 points from `code_index` running a test.
4. **`./rebuild-host.sh` only with the owner authorizing** (activates config and
   restarts services). Direct `nixos-rebuild`: never. `/nix/store`: never
   edit. Restarting the LLM mid-session: never.
5. **Never claim "it's running"/"it's up" without checking now.**
   `pgrep` + log + evidence. Committed code ≠ live code: long-lived
   processes carry the old `.py` in memory — check
   `ps -o lstart=` against `git log --date`.
6. **Never measure with another process on the machine.** Sweep/bench refuses
   to measure if another `llama-server` is alive (contention once cost an
   entire investigation into a nonexistent "bimodal").

## Commands

```bash
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short
git add -A && git ls-files -o --exclude-standard   # flake only sees tracked
./rebuild-host.sh        # HOST — only with the owner authorizing
nix flake check
```

## JARVIS CLI = same env as the MCP (30/10)

- `scripts/jarvis-cli.sh` and the MCP share `modules/ai/jarvis/jarvis-env.sh`
  (keys from `/etc/litellm.env`, PYTHONPATH = src + official store env +
  `/home/nixos/.local/jarvis-mcp-site`, profile python). **Never diverge the
  two envs again** — without that the CLI loses `requests`, the LLM breaker
  opens and `rag-index` hangs without error.
- MCP handlers read **fixed** keys: `rag_index`→`path`, `vault_write`→`name`
  (+`content`), `rag_search`→`query`/`collection`/`limit`, `remember`→`text`,
  `recall`/`lessons`→`query`. Wrong key = **argument ignored** (the CLI
  indexed the wrong tree for 6 months due to a bug).
- **Embedding server (8081) has n_ctx=512 TOKENS per item**: 1200-char chunk
  ≈ 550 tokens → HTTP 400 `exceed_context_size`. `CHUNK_CHARS=800`, and
  `embed()` shrinks on its own if the server refuses. Batch ≤64 items/POST and
  **no retry** (Retry read=3 × timeout = 8min wait = "hang").
- The official MCP env is **discovered by reading `~/.config/opencode/opencode.json`**
  (symlink to the store) → follows rebuilds without re-typing the Nix.

## Checkpoint and pains (30/10)

- **1st tool of the session = `jarvis_rehydrate(task="...")`** (02/11): 1 call
  returns guardrails + queue + HANDOFF + memories + lessons + RAG + roster.
  Without that the agent repeats diagnostics already paid for (the RAG was
  used only to *record*, never to *rescue*). Rule injected by the `memory.js`
  plugin (system prompt + compaction), does not depend on agent memory.
  Research: `docs/REHYDRATACAO-E-COORDENACAO.md` (14 papers in `~/Books`).
- `scripts/agent-checkpoint.sh` = the 4 layers in 1 command (queue+commit,
  rag-index, memory, vault HANDOFF+commit), generic for any repo.
- `scripts/agent-pains.sh` = captures tool errors **on its own**: the live
  opencode store is the **SQLite `~/.local/share/opencode/opencode.db`** (the
  `storage/` JSON only has old sessions). `agents-watcher.sh` runs the
  `scan-apply` every 10 cycles and suggests a checkpoint after 45min of work.
- **Frequency calibrated by activity (01/11, owner's request)**: the watcher
  reads `part` from `opencode.db` (updated on every tool call) — an agent with
  a new part ≤`AGENTS_DB_ALIVE`s (600) is ALIVE: no wake, no RE-ENTER, no
  deadlock (CPU idle = false positive of a long command). Read-only, `mode=ro`.
- **Checkpoint without redundancy (01/11)**: `CHECKPOINT-SUGERIDO` compares the
  current snapshot (commits of all repos at the root) with the snapshot stored
  at the last suggestion — no new commit = era already sealed, no repeat. The
  suggestion guarantees a checkpoint only when there is new work to seal.
- Error masked by a pipe (`cmd | tail`) does **not** reach the scanner → when
  debugging, run without a pipe (or with `set -o pipefail`).

## Multi-agent coordination (02/11 — opencode API, without stealing focus)

- **Roster = single source**: `scripts/agent-roster.py` (claim/release/list/
  prune/task/windows/resolve/events) in `~/projects/.agents/roster.json`
  (`$AGENTS_ROSTER` override). `claim` rejects a duplicate name (live window)
  and **overlapping file globs** (Anthropic: explicit boundary) — 2
  claims on the same file duplicate work.
- **Delivery = opencode API** (`opencode serve` on `:4599`, Basic auth via
  `~/.config/opencode/server.env`): `POST /session/:id/message`
  (`noReply:true` = NOTE: enters the session, the agent does NOT run, zero
  token) / `prompt_async` (REQUEST: the agent runs) / `/abort` (cancels the
  turn). **Never** park text in the human's input box: it blocks typing and
  does not enter the queue → useless (real error on 02/11).
- `scripts/agent-msg.sh`: `--to <nome>` (request), `--note` (notification),
  `--broadcast` (explicit fan-out, rare), `--cancel <id>`, `--reply-to`,
  `--id` (idempotency), `--pending`, `--list`. Without a roster, `--to other`
  **sends nothing** (broadcast only with `--broadcast`).
- `scripts/agents-watcher.sh`: wake **via API** (no focus/wtype) and
  **lane-aware** (a commit on repo X only wakes the owner of repo X; queue/hooks
  = global; no roster = legacy global). `RE-ENTER` only exists in the wtype
  fallback — never submit what the human is typing.
- Evidence: `scripts/agent-msg.sh` → `~/projects/AGENTS-MSG.log`.

## Model identity (self-identification — 02/11)

You cannot introspect your own weights. A model does not know its size, its
quantisation, whether it runs on the local GPU or behind an API, and it must
never guess: a wrong identity silently corrupts every decision that depends
on it (context budget, tool latency expectations, language support, VRAM
budget).

**The harness is the only reliable source of identity.** Three tiers, in
order of authority:

1. **opencode (this stack):** the `memory.js` plugin injects an `## IDENTITY`
   block at the top of the system prompt — `model: <provider>/<id>`, plus the
   session id. It comes from the hook input (`{sessionID, model}`), never
   from the conversation. **If you see that block, that is you.** Use it
   verbatim when asked who you are, what your context budget is, or whether
   you are local.
2. **JARVIS runtime (CLI / agent / voice):** the runtime knows the active
   tier from the model registry (`modules/ai/models.nix` is the single source
   of truth). Ask it: `scripts/jarvis-cli.sh status` (active tier, port,
   profile) — or the `status`/`doctor` command. A router tier (`bonsai`,
   `qwen-fast`) is a *profile*, not a model id: the registry maps it to a
   concrete model.
3. **No source at all:** say so plainly — "I don't know my runtime identity
   from here" — and name what would answer it. Never infer identity from the
   tone of the conversation, from the tools you can see, or from what "feels"
   like your context size.

Language rule that follows from identity: **everything an LLM reads is
English** (small local models do not read pt-BR). If your identity block says
you are a small local model, assume English-only inputs and short answers.

## Boundaries

- **Always:** run tests before committing; check `git ls-files` for
   session-created files; commit in EN with a verb (`feat:`/`fix:`/
   `chore:`/`docs:`); every new rule enters **only after** an agent
   really errs (grows organically, not speculatively);
   research the latest papers on the current subject/difficulty BEFORE
   implementing (owner directive 20/10 — `~/Books/papers` + RAG `books`,
   arXiv direct, HF cards).
- **Ask:** changing the host `configuration.nix`; llama-server flags;
   new dependencies; mutating live memory (`consolidate --apply`).
- **Never:** direct `nixos-rebuild`; edit `/nix/store`; `git add .` without
   seeing what's in it; auto-commit with `git add -A`.

## Opencode & rtk (plugins)

- rtk plugin (`~/.config/opencode/plugins/rtk.ts`, declarative in
  `home-manager/files/opencode/plugins/rtk.ts`) rewrites commands so
  rtk saves context. Opt-out: include `norrtk` (or `--no-rtk`) on the
  line; paths starting with `./` or `/` bypass rtk.
- Policy details (including when NOT to use rtk) live in the root AGENTS.md
  (`~/projects/AGENTS.md` §Tooling) — nixos-ai doesn't duplicate.

## Rules you can't infer from the code

- `modules/ai/models.nix` is the **single source of truth** for models,
  profiles and flags. Profiles are consumed by `services/llama-cpp.nix`.
  Sampling (temperature/top_p/top_k/...) also lives there
  (`routing.models.<id>.sampling`, per model — Prism 0.5 does NOT apply to Qwen);
  Python reads via registry, nothing hardcoded.
- **Models: never delete, never download without checking.** Inventory and rules in
  [`docs/models/MODEL-SAFETY.md`](docs/models/MODEL-SAFETY.md) (27B incident 25/09). Bonsai 8B lives in the
  nix store (GC brings it back with a rebuild), not in `~/models`. Check 6GB
  VRAM before any download.
- 6GB VRAM: **1 LLM at a time.** For models that don't fit, GPU experts
  **hurt** (fetch comes over PCIe, 6-7 GB/s, vs 41-83 GB/s from
  RAM). Dense models that fit in VRAM run ~3.2× faster.
- `-t` = **P-cores**. This CPU is hybrid (6P+4E) and `lscpu` reports "8".
  Measured: `-t 6` = 16.4 t/s · `-t 8` = 14.1 · `-t 10` = 10.4 · `-t 12` = 7.9.
- `ubatch` changes the `ik_llama.cpp` offload decision (threshold
  `32 × total_experts/active_experts`); keep 512 aligned with the service.
- Embeddings server has a **512-token max context**: above that it
  returns 400/500. `providers/embedding.py` chunks + mean-pools.
- **Binary matters:** prism = ternary (and MoE); ik = MoE; stock loads
  `Q2_0` as silent garbage. See [`docs/models/BINARIES.md`](docs/models/BINARIES.md).
- This machine's hardware and measurements: `docs/auditoria/SO-LLM-E-ENTROPIA-*.md`.

## Index (read only when the task asks)

| Document | When to consult |
|---|---|
| [`docs/SISTEMA-ESTADO-E-BENCHMARKS.md`](docs/SISTEMA-ESTADO-E-BENCHMARKS.md) | tier status, H1/H2/H3, history |
| [`docs/architecture/SYSTEM-MAP.md`](docs/architecture/SYSTEM-MAP.md) | system map and layers |
| [`docs/models/BINARIES.md`](docs/models/BINARIES.md) | which binary for which model |
| [`docs/auditoria/SO-LLM-E-ENTROPIA-2026-09-25.md`](docs/auditoria/SO-LLM-E-ENTROPIA-2026-09-25.md) | OS, VRAM/RAM, PCIe, measurements |
| [`docs/PROMPT-AGENTE-EXTERNO.md`](docs/PROMPT-AGENTE-EXTERNO.md) | ready-made prompt for an external agent |
| **[`docs/HANDOFF-2026-10-12.md`](docs/HANDOFF-2026-10-12.md)** | **12/10 session state + exact next step** |
| [`scripts/LOOP-v2.md`](scripts/LOOP-v2.md) | overnight loop method |
| [`docs/harbor/INDEX.md`](docs/harbor/INDEX.md) | Harbor calibration scoreboard + files |
| `scripts/overnight-24-09/` | dated bench evidence |
| `.agents/*.md` | detail per topic (load only on trigger match) |

## Model-agnostic (detection → adaptation — read before touching prompts/tools)

- `cli/dev.py:_detect_profile` — registry tier beats param-count; tiny →
  `native_tools=False` (text only, no `tools` overhead); override
  `cfg.llm_native_tools`. Local REPL proof: bonsai reads exact (29/09).
- `core/agent.py:_strict_default` — speed/fast tiers get constrained
  grammar; rest free text. Outside strict, ```bash fences become
  `execute_shell` (F-cell; dev.py accepted fences long ago).
- `core/agent.py:_try_api_cascade` — proven STUCK → 1× API
  (CASCADE_MAP; Groq last resort). Bot has keys via litellm.env.
- Missing template (xLAM) isn't cheaply detectable: assumes tool-capable
  by size and breaks (400/500). Template suspected → text mode.

## Agent rules (trigger → file)
- [`.agents/dados-e-memoria.md`](.agents/dados-e-memoria.md) — RAG, memory, vault, spaces, encryption.
  Triggers: RAG, memory, vault, qdrant, collection, embedding, recall.
- [`.agents/loop-e-bench.md`](.agents/loop-e-bench.md) — overnight, harness, sweep, bench, cmoe, t/s, overnight.
  Triggers: loop, harness, bench, sweep, cmoe, t/s, overnight.
- [`.agents/harbor-e-harness.md`](.agents/harbor-e-harness.md) — external Harbor calibration, trials, adapter.
  Triggers: harbor, calibration, trial, verifier, A-cell, B-cell.
- [`.agents/memoria-do-projeto.md`](.agents/memoria-do-projeto.md) — decisions and already-paid traps.
  Triggers: broke before, before touching, trap, why.
- [`.agents/mcp-catalog.md`](.agents/mcp-catalog.md) — who exposes what (jarvis, nixos, tavily, context7).
  Triggers: mcp, tavily, context7, browser, nix search, vault, github.

## Frontmatter

Tags: #status/active #type/rules #project/nixos-ai
- When patching files, the old_text must be an EXACT substring of the file content. Read the file first, then use the exact text.
- Always run validation checks on generated code before returning it.
- After generating code, verify it has no syntax errors before returning. Use python -c 'compile()' to check.
