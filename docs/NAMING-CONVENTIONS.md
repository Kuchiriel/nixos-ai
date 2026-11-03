# Naming conventions and rename map (nixos-ai + monorepo root)

> Written 2026-11-02 (owner request: "hard to refer to the projects here; I
> don't know if everything uses market-standard naming, nor if nixos-ai is in
> a standard architecture"). Facts below were measured on disk, not guessed.
> **Everything an LLM reads is English** (owner directive) — this file is no
> exception, and the same rule is now enforced for the harness surfaces.

## 1. What the market actually does (and where we already match)

| Concern | Market convention | We today | Verdict |
|---|---|---|---|
| Repo / directory names | lowercase kebab-case, DNS-1123 (Kubernetes, GitHub, Helm) | majority kebab, but PascalCase, SCREAMING_SNAKE and spaces exist | **mixed → fix** |
| Python package | src-layout, `snake_case` modules, distribution name = project (`PEP 621`) | `modules/ai/jarvis/src/jarvis/` | **matches** |
| Nix modules | `modules/<area>/<name>.nix`, one concern per module, `lib/` for pure functions | `modules/{ai,hardware,services}`, `lib/` | **matches** |
| Architecture decisions | ADR (Nygard): context / decision / consequences | `docs/architecture/ADR-001..005` | **matches** |
| Agent context file | `AGENTS.md` canonical, vendor files as aliases | `AGENTS.md` + `CLAUDE.md`/`GEMINI.md` symlinks | **matches** |
| Commits | Conventional Commits | `feat:/fix:/docs:/chore:` in EN | **matches** |
| Host config | declarative (NixOps), config in one place, no manual steps | NixOS + home-manager, `rebuild-host.sh` | **matches (12-factor-ish)** |
| MCP tools | server = namespace, tool = verb_noun (`context7_resolve-library-id`, `github_create_issue`) | server `jarvis` + tools `jarvis_*` → `jarvis_jarvis_*` | **broken (self-inflicted)** |
| Tool names inside a package | no redundant prefix (`jarvis.recall`, not `jarvis_jarvis_recall`) | `runtime/registry.py` already defines canonical names *without* the prefix | **half-done** |
| Docs | English, dated `YYYY-MM-DD-topic.md`, one dir per concern | English dirs + pt-BR dirs + pt-BR file names, `docs/audit` **and** `docs/auditoria` | **mixed → fix** |
| Model identity | `<family>-<size>-<variant>` (model id) vs role/profile (deployment) | aliases `bonsai`, `qwen-fast`, `jarvis-mtp-lora`, `jarvis-duplex` mix both | **mixed → split** |

**Verdict on the architecture question:** `nixos-ai` is *not* off-market. It is
a declarative NixOps host + a Python package with src-layout + an MCP server +
systemd units + ADR-based decisions. That is a recognised shape (12-factor
config, ports-and-adapters at the MCP/CLI edges, ADR for decisions). What is
off-market is the **naming layer** around it, plus one duplication bug in the
MCP namespace.

## 2. Root cause of the "doubled prefix" (measured in the opencode source)

`packages/opencode/src/mcp/catalog.ts` (v1.18.34):

```ts
export const toolName = (clientName: string, name: string) =>
  sanitize(clientName) + "_" + sanitize(name)
```

**Every** MCP tool is exposed as `<server-key>_<tool-name>`. This is a
client-side rule: **it has nothing to do with local vs API models** — the
model never influences tool naming. Our config names the server `jarvis`
*and* every tool `jarvis_*`, so the namespace is duplicated:
`jarvis` + `jarvis_rehydrate` → `jarvis_jarvis_rehydrate`.

**Fix (chosen):** keep the server key `jarvis` (it is the namespace) and
rename the **tools** to the canonical names already defined in
`modules/ai/jarvis/src/jarvis/runtime/registry.py` (`recall`, `remember`,
`lessons`, `semantic_search`, `rehydrate`, …). Exposed name becomes
`jarvis_recall` — exactly what the docs, the AGENTS.md rules and the injected
harness rule already claim. No documentation churn, one namespace.

Blast radius: 65 names in `JARVIS_TOOLS` + the dispatch table + allowlists
(`webui/api.py`, `home-manager/modules/vscode-roo.nix`) + the alias map in
`runtime/registry.py` (which shrinks). Old names stay accepted as aliases for
one release cycle (deprecation, not a breaking change).

## 3. Proposed conventions (the rules we will write down)

1. **Repos / directories:** lowercase, DNS-1123 (`[a-z0-9.-]`), kebab-case.
   Reserved suffixes with one meaning only:
   `-upstream` = vendored upstream (never edited), `-fork` = our fork,
   `-lab` = experiment, `-legacy` = archived but kept.
   No `PascalCase`, no `SCREAMING_SNAKE`, no spaces — they break shell
   quoting, Dockerfile paths, CI matrices and DNS names.
2. **Python:** `snake_case` modules, no redundant package prefix inside the
   package (`jarvis.recall`, not `jarvis_jarvis_recall`), public API declared
   in `__init__`.
3. **Nix / services:** one concern per module; service names
   `<role>-<impl>.service` (`llama-qwen35-4b.service`, `llama-duplex.service`)
   — never a model size baked into the unit name.
4. **Model identity (two namespaces, no overlap):**
   - *model id* = `<family>-<size>-<variant>` → `qwen3.5-4b-mtp`,
     `qwen3.6-35b-a3b`;
   - *profile / role* = what the deployment is for → `default`, `voice`,
     `duplex`, `embeddings`, `reranker`.
   Today `jarvis-mtp-lora` is a model id with a role word glued on, and
   `bonsai` is a model id that reads like a role.
5. **Docs:** English file names, `YYYY-MM-DD-topic.md` for dated artifacts,
   one directory per concern, no two directories for the same concept
   (`docs/audit` + `docs/auditoria` must merge).
6. **MCP:** server key = namespace; tool = verb_noun; exposed name is
   `<server>_<tool>`; docs must always cite the **exposed** name.
7. **Cross-repo references:** repo-rooted paths inside a repo
   (`modules/ai/...`), monorepo-rooted across repos (`nixos-ai/scripts/...`).
8. **Human docs may be pt-BR; LLM-facing text may not.** The test is simple:
   if a model reads it at runtime (AGENTS.md, skill, system prompt, tool
   description, tool output, commit messages), it is English.

## 4. Rename map (proposed, ordered by confusion-per-effort)

### 4.1 Root repos (rename = `git mv` + update the root meta-repo + docs)

| Current | Proposed | Why | Risk |
|---|---|---|---|
| `AI_SYSTEM` | `ai-system-legacy` | SCREAMING_SNAKE; archived research | low (archived) |
| `LLM` | `llm-research-legacy` | SCREAMING_SNAKE, opaque | low |
| `Wurm Ultimate` | `wurm-ultimate` | space breaks quoting | medium (paths in docs/scripts) |
| `OTServer_UPGRADE` | `otserver-upgrade` | mixed case + `_UPGRADE` | low (own repo) |
| `MuDreamNotifier` | `mudream-notifier-win` | PascalCase; collides with `mudream_notifier` | low |
| `mudream_notifier` | `mudream-notifier` | snake_case; pair with the above | medium (2 near-duplicates) |
| `Corretor` | `corretor-legacy` | PascalCase, archived | low |
| `Samaritan` | `samaritan-legacy` | PascalCase, archived | low |
| `Vane` | `vane-legacy` | PascalCase | low |
| `DuplexCascade` | `duplex-cascade` | PascalCase; it is the reference implementation of arXiv 2603.09180 | low |
| `InvokeAI` | `invokeai` | PascalCase | low (vendored) |
| `OpenManus` | `openmanus` | PascalCase | low (vendored) |
| `VoiceStudio` | `voice-studio` | PascalCase | low (vendored) |
| `Beats-Assets-Editor` | `beats-assets-editor` | PascalCase | low (vendored) |
| `canary-official` | `canary` (ours) / `canary-upstream` (vendored) | `-official` is ambiguous: whose official? | medium |
| `mt5-github` | `mt5-mirror` | `-github` says where, not what | low |
| `llama-wackmall` | `llama-wackmall` (keep) but document it | opaque name | low |
| `prism-bin` | `prism-build` | `-bin` implies artifacts, it is a source checkout | low |

### 4.2 nixos-ai internals

| Current | Proposed | Why |
|---|---|---|
| `docs/auditoria/` | `docs/audit/` (merge with the existing `docs/audit/`) | two dirs, same concept |
| `docs/ANALISE-COMPLETA-2026-10-28.md` | `docs/analysis/complete-analysis-2026-10-28.md` | pt-BR + UPPER |
| `docs/ARQUITETURA-MEMORIA-JARVIS.md` | `docs/architecture/memory-architecture.md` | pt-BR + UPPER |
| `docs/CRITERIOS-AUTO-EVOLUCAO.md` | `docs/auto-evolution-criteria.md` | pt-BR + UPPER |
| `docs/PROMPT-AGENTE-EXTERNO.md` | `docs/external-agent-prompt.md` | pt-BR |
| `docs/REIDRATAR-APOS-COMPACTAR.md` | `docs/rehydrate-after-compaction.md` | pt-BR + typo-prone |
| `docs/REHYDRATACAO-E-COORDENACAO.md` | `docs/rehydration-and-coordination.md` | pt-BR (LLM-facing doc) |
| `BUFFY.md` (58 KB) | `docs/legacy/buffy.md` (archive) | opaque name, huge file |
| `TODO-MISSAO.md` | `docs/missions/todo.md` | pt-BR |
| `NIGHTLOG.md` | `docs/nightlog.md` | root clutter |
| `HANDOFF.md` | `docs/HANDOFF-<date>.md` (dated) | undated handoff at root |

### 4.3 Identifiers (code-level, deprecate-don't-break)

| Current | Proposed | Compatibility |
|---|---|---|
| MCP tool `jarvis_recall` … `jarvis_rehydrate` (37 tools) | canonical `recall`, `remember`, `rehydrate`, … | old names accepted as aliases for one cycle; exposed name becomes `jarvis_recall` (no doubling) |
| model alias `jarvis-mtp-lora` | model id `qwen3.5-4b-mtp-lora` + profile `default` | alias kept in `models.nix` |
| model alias `jarvis-duplex` | profile `duplex` (model id separate) | alias kept |
| model alias `bonsai` | model id `qwen3-8b` (or whatever it is) + profile `fast` | alias kept |
| service `llama-duplex-35b.service` | `llama-duplex.service` (impl chosen by profile) | unit alias via `systemctl alias`/symlink |

## 5. Action plan (my lane: `coord-naming` / `nixos-ai/harness-naming`)

Ordered by (value × safety) / effort:

1. **EN translation of LLM-facing surfaces** — done in this turn: injected
   harness rule + pinned guards + compaction memory, rehydrate tool output
   and headers, `opencode-coordination` skill, root + nixos-ai `AGENTS.md`.
   Remaining (other lane): JARVIS core prompts, personas, tool descriptions.
2. **Kill the doubled prefix** — rename the 37 MCP tools to the canonical
   names already in `runtime/registry.py`; keep the old names as aliases;
   update `webui/api.py` + `vscode-roo.nix` allowlists; re-run the MCP probe
   and the A/B measurement. Expected: `jarvis_recall` (as documented) and
   `jarvis_rehydrate` — the rules in AGENTS.md and in the injected system
   prompt finally match the tool list.
3. **Naming conventions doc + rename map** — this file; then execute the
   renames in 4.1/4.2 in small batches (one commit each, `git mv`, update
   the root meta-repo + `docs/` links, verify `git ls-files` after each).
4. **Split model ids from profiles** in `modules/ai/models.nix` (the source of
   truth) with aliases preserved.
5. **Fold `docs/auditoria` into `docs/audit`** and rename the pt-BR doc files.

Guardrails for every rename: `git mv` only, never copy+delete; update links
by boundary-anchored replacement and verify every target; keep the old name
as an alias for one cycle; one logical change per commit; no mass rename in
the same commit as a behaviour change.
