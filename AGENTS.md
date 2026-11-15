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


> **Frame (14/11):** isto e trabalho **autorizado** do owner na **propria**
> infra dele (auditoria defensiva, correcao de configuracao, prova de
> superficie). O conteudo de RCE, credenciais e hosts abaixo e o **ALVO** da
> analise, **nao** instrucao para invadir ninguem. As regras daqui limitam
> como trabalhar, nao o que pode ser pedido — se o pedido for de analise,
> documentacao defensiva ou correcao, ele esta no escopo.

1. **NEVER delete data.** Zero `rm`, `delete_collection`, `drop_collection`
   on material you didn't create in the last minutes. Use
   `core.safe_archive.archive_then_delete()`: copy : **read back** :
   check count and hash : only then remove. Qdrant once accepted a
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
  opens and `rag-index` hangs without error. For non-MCP harnesses (e.g. duplex/voice), CLI is the parity entry point: `tools`/`tools-search`/`tools-call`/`tool` (meta-routing), `session-resume`, `rehydrate`, `time`, with `--json` on key commands for machine use.
- MCP handlers read **fixed** keys: `rag_index`:`path`, `vault_write`:`name`
  (+`content`), `rag_search`:`query`/`collection`/`limit`, `remember`:`text`,
  `recall`/`lessons`:`query`. Wrong key = **argument ignored** (the CLI
  indexed the wrong tree for 6 months due to a bug).
- **Embedding server (8081) has n_ctx=512 TOKENS per item**: 1200-char chunk
  ≈ 550 tokens : HTTP 400 `exceed_context_size`. `CHUNK_CHARS=800`, and
  `embed()` shrinks on its own if the server refuses. Batch ≤64 items/POST and
  **no retry** (Retry read=3 × timeout = 8min wait = "hang").
- The official MCP env is **discovered by reading `~/.config/opencode/opencode.json`**
  (symlink to the store) : follows rebuilds without re-typing the Nix.
  Measured 08/11: the 2.2.6 can normalize that symlink into a regular file
  while it runs (a rebuild restores it) — editing the live file is wrong
  either way: the owner is `home-manager/home.nix`.
- **Tool names = `jarvis_<tool>`** (server key `jarvis`): `jarvis_rehydrate`,
  `jarvis_recall`, `jarvis_lessons`, `jarvis_rag_search`, `jarvis_rag_index`,
  `jarvis_session_resume`, `jarvis_remember`, `jarvis_vault_*`. A doubled prefix (`jarvis_jarvis_*`) is
  the same tool. What/when/how per tool: [`.agents/mcp-catalog.md`](.agents/mcp-catalog.md).
- **Session continuity (opencode)**: Qdrant collection `sessions` holds structured summaries indexed from `~/.local/share/opencode/opencode.db` (no raw transcript). Use `jarvis_rehydrate` for task-context rescue (includes past session summaries and consolidated memories), `jarvis_session_resume(session_id|directory|query)` for deterministic resume, or `jarvis_rag_search(query, collection="sessions")` for discovery. Session summaries are also distilled into durable episodic memory facts (`memories`, `source=session_consolidation`) by `scripts/consolidate_sessions_memory.py` for `recall`/`rehydrate`. Kept current by user timer `jarvis-sessions-index.timer` (incremental index+consolidate, every ~30min; states `~/.local/state/jarvis/sessions-index-state.json`, `sessions-consolidation-state.json`) and by `agent-checkpoint.sh`; manual: `nix develop -c python3 scripts/index_opencode_sessions.py --incremental && nix develop -c python3 scripts/consolidate_sessions_memory.py --incremental`.

## Checkpoint and pains (30/10)

- **1st tool of the session = `jarvis_rehydrate(task="...")`** (02/11): 1 call
  returns guardrails + queue + HANDOFF + memories + lessons + RAG (code/books) + past session summaries + roster.
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
    - **Frequency calibrated by activity (01/11, owner's request)**: an agent with
      new activity <=`AGENTS_DB_ALIVE`s (600) is ALIVE: no wake, no RE-ENTER, no
      deadlock (CPU idle = false positive of a long command). Read-only, `mode=ro`.
      **CORRIGIDO 15/11 (medido)**: no 2.2.6 a atividade fica em
      `session_message` (o CONTEUDO vem DENTRO do `data`); `part`/`message` sao o
      schema 1.x e estao CONGELADOS (medido: max(part.time_updated)=09/11 no host).
      Ler a tabela errada fez o `prune` APAGAR os 4 agentes VIVOS e o watcher
      concluir "ninguem esta trabalhando". Fonte unica: `scripts/oc-db.py`
      (escolhe a tabela viva; `agent-db-alive.py` e `agent-roster.py` delegam).
      Regra de bolso: **liveness pela API do opencode** (`/api/session`): ela
      responde 200 para a sessao viva e 404 para a morta, em qualquer contexto
      (inclusive headless, onde nao ha janela Hyprland).

- **Checkpoint without redundancy (01/11)**: `CHECKPOINT-SUGERIDO` compares the
  current snapshot (commits of all repos at the root) with the snapshot stored
  at the last suggestion — no new commit = era already sealed, no repeat. The
  suggestion guarantees a checkpoint only when there is new work to seal.
- Error masked by a pipe (`cmd | tail`) does **not** reach the scanner : when
  debugging, run without a pipe (or with `set -o pipefail`).

## Multi-agent coordination (02/11 — opencode API, without stealing focus)

- **Roster = single source**: `scripts/agent-roster.py` (claim/release/list/
  prune/task/windows/resolve/events) in `~/projects/.agents/roster.json`
  (`$AGENTS_ROSTER` override). `claim` rejects a duplicate name (live window)
  and **overlapping file globs** (Anthropic: explicit boundary) — 2
  claims on the same file duplicate work.
- **Delivery = opencode API** (`opencode serve` on `:4599`, Basic auth via
  `~/.config/opencode/server.env`): `POST /api/session/:id/prompt` with
  `{"text": "...", "delivery": "queue"}` (the agent runs) or
  `"delivery": "steer"` (goes into the running turn) — measured 07/11:
  the API lives under `/api`; without it the POST hits the SPA catch-all
  and returns HTML 200, which is why the wake used to fail silently.
  `/abort` cancels the turn. **Never** park text in the human's input box: it blocks typing and
  does not enter the queue : useless (real error on 02/11).
- `scripts/agent-msg.sh`: `--to <nome>` (request), `--note` (notification),
  `--broadcast` (explicit fan-out, rare), `--cancel <id>`, `--reply-to`,
  `--id` (idempotency), `--pending`, `--list`. Without a roster, `--to other`
  **sends nothing** (broadcast only with `--broadcast`).
- `scripts/agents-watcher.sh`: wake **via API** (no focus/wtype) and
  **lane-aware** (a commit on repo X only wakes the owner of repo X; queue/hooks
  = global; no roster = legacy global). `RE-ENTER` only exists in the wtype
  fallback — never submit what the human is typing.
- Evidence: `scripts/agent-msg.sh` : `~/projects/AGENTS-MSG.log`.

## Model identity (self-identification — 02/11)

You cannot introspect your own weights (size, quantisation, VRAM, latency) — a
wrong identity silently corrupts every decision that depends on it. **The
harness is the only source**: opencode injects an `## IDENTITY` block (model +
session id) : *that is you*; the JARVIS runtime knows the active tier
(`scripts/jarvis-cli.sh status`, registry `modules/ai/models.nix`); no source :
say so plainly and name what would answer it. Full 3-tier detail: root
AGENTS.md §Model identity.

Language rule: **everything an LLM reads is English** (small local models don't
read pt-BR); answer the owner in pt-BR.

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
- **Uncensored = ABLITERATED (sem refusal direction).** `llm-uncensored-4b`,
  `-4b-mtp` e `-35b` têm a recusa removida no fine-tune. Consequência
  prática (medida 07/11): **não servem como alvo de jailbreak nem para
  medir refusal direction** — o 4B-MTP cumpre 18/18 prompts (até os mais
  overt), então qualquer ASR medido nele é ruído e não há recusa para ter
  assinatura no espaço de ativação. Para medir recusa use o
  **Ternary-Bonsai-8B** (prism, alinhado) ou um modelo da API. Medido
  08/11: o bonsai recusa **6/6** nos prompts overt (o maior refusal local
  medido) — ele é o alvo certo, mas o router só carrega o bonsai com o
  **4B-MTP PARADO** (6 GB, 1 LLM por vez) e o 4B é o cérebro da voz: medir
  recusa tira a voz do ar (o cliente morre com ":8092 fora"). Avisos
 tambem em `modules/ai/models.nix`, junto de cada modelo.
    - **HOT RELOAD (15/11, medido)**: mudar plugin/config NAO exige restart.
      O caminho DETERMINISTICO e `opencode reload` (ou `/reload` no TUI): recarrega
      config + plugins sem reiniciar o server ("running sessions continue with
      fresh services at the next step boundary") - medido no log: "loading plugin"
      para os 4 plugins.
      A ARMADILHA do WATCHER: ele compara o DIGEST do CAMINHO watchado (que e o
      symlink em ~/.config/opencode/plugins/) - entao **editar o CONTEUDO do
      arquivo-alvo NAO recarrega** (medido: log mudo); o que dispara e RE-APONTAR
      o symlink (muda o caminho) ou o `opencode reload`. O plugin vive como symlink
      do nix store (read-only) -> `scripts/agents-reload.sh` re-aponta para o
      arquivo VIVO do repo e roda o reload (do celular: `~/bin/agents-reload`).
