# Model duplication map (@general subagent)

- **sessão:** `ses_f7e85797affe8qZjesFWBRfZ1x`
- **quando:** 2026-09-08 14:44 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 8 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), map EVERY place that duplicates or references model metadata outside modules/ai/models.nix. Search for: model filenames (*.gguf), "Qwen", "bonsai", "Bonsai", "8080"/"8081"/"8082", "llama-cpp"/"prismml"/"bonsai" backend names, "default" model strings, ctx sizes, n-gpu-layers/ngl values, in: modules/ai/jarvis/src/jarvis/**/*.py, home-manager/, scripts/, hosts/, docs/benchmarks/, webui/, .env files. For each: file:line + what it duplicates (filename? port? backend? profile?) + whether it MUST stay (runtime derivation) or is stale duplication. Also list test files covering LLM/backend/routing (names + what they assert). Max 90 lines. Do NOT change anything.

---

## · ?

Mapping model metadata duplicates — read-only sweep across configs, code, and docs.

---

## · ?

Initial sweep shows broad duplication — now narrowing to your requested scopes for precise file:line mapping.

---

## · ?

Core duplication points located — now verifying runtime derivations vs stale copies to finalize the verdicts.

---

## · ?

Read-only map — `modules/ai/models.nix` is truth (filenames+`profiles`: `bonsai` ngl=99/ctx32768, `fast` ngl=25/ctx4096, `vm` ctx131072; ports default in `modules/services/llama-cpp.nix:29,77,84` = 8080/8081/8082).

**`modules/ai/jarvis/src/jarvis/**/*.py`**
- `core/config.py:37,40-41` backend `llama-cpp`, `JARVIS_LLM_BASE_URL=:8080/v1`, `MODEL=default` — MUST stay (env derivation, no hardcode).
- `core/config.py:49,53,70` embed `:8081`, rerank `:8082`, `nomic-embed-text-v2` — MUST stay (service refs).
- `providers/llm_llama_cpp.py:71,73` + `llm_prismml.py:71,73` defaults `8080`/`default` — MUST stay (ctor fallback).
- `providers/llm_prismml.py:15` doc `Bonsai-8B-Q2_0.gguf` placeholder — MUST stay (example path, not store pin).
- `providers/llm_factory.py:36,51,62-75,95-106` enum `llama-cpp/prismml/bonsai` dispatch — MUST stay.
- `providers/llm_backend.py:68,70` `backend_type/n_ctx` interface — MUST stay.
- `providers/llm.py:212-213,539-542` comment 8081≠8080 + `n_ctx` fallback 32768 — MUST stay (matches `bonsai` ctx).
- `providers/reranker.py:33` default `:8082` — MUST stay.
- `providers/llm.py:309-310`, `cli/dev.py:270` `cfg.llm_model` passthrough — MUST stay.
- `core/doctor.py:62,259-260` port comment + `8080/8081` fallback parse — MUST stay (health derivation).
- `core/tool_patterns.py:1,11` Qwen `<tool_call>` format — MUST stay (behavior, not metadata).
- `core/hwdetect.py:352` generic `-ngl` builder — MUST stay.
- `benchmarks/experiment_tracker.py:16-17,80,92` hardcoded `model Qwen3.6-35B`, `backend llama-cpp`, `n_ctx` — STALE (should read profile).
- `control_plane/systemd_adapter.py:44` `(Qwen)` label; `cli/launcher.sh:73,88,211-212` `:8080/:8081` probes — label STALE, probes MUST stay.

**`home-manager/`**
- `home.nix:247,252` Bonsai comment + `8080/v1` — MUST stay.
- `home.nix:256,258-259` `Qwen3 35B Local` + `bonsai-8b` entry — STALE label (host `profile=bonsai`, no Qwen served).
- `home.nix:398` aider `8080/v1` — MUST stay. `home.nix:434` `*.gguf` ignore — MUST stay.
- `modules/vscode-roo.nix:201,209-215` `:8081` + `Qwen3 Local 35B/maxInputTokens 196608` — port MUST stay, model+196K STALE (no profile has 196K; max `vm` 131072).
- `modules/ai/pi.nix:19,23,57-61,94` `:8080` URLs MUST stay; `Qwen2.5-Coder/7B-vs-32B` comments STALE (pre-Qwen3.6/Bonsai).
- `modules/agents-md.nix:21,73` `Qwen3.6-35B-A3B/32K` — STALE (now Bonsai).

**`hosts/`**
- `hosts/nitro-v15/configuration.nix:156` `profile="bonsai"` — MUST stay (canonical consumer).
- `hosts/nixos-lab/configuration.nix:149` Qwen3.6 comment — STALE comment; `:153-158` enables MUST stay.
- Both `:233/:202` firewall `[22 8080 8081 4000]` — MUST stay.

**`scripts/`**
- `bench-one.sh:7,75,81` `quick-bench.sh:8` `proper-benchmark.sh:7-8` `mlock-benchmark.sh:7-8` `systematic-benchmark.sh:7` `thermal-curve.sh:6-7` `a-b-compare.sh:6` `bench-final.py:6` `benchmark-official.py:35-36` `ncmoe-sweep.py:23-24` pinned `/nix/store/...Qwen3.6...gguf` (+mmproj) + `-ngl 45/--n-cpu-moe 35/99/-c 4096/8192` — STALE (bypasses `models.nix`; ngl45 OOM per `models.nix:414`, `bonsai-vs-qwen §5`).
- `benchmark-official.py:37/ncmoe-sweep.py:25` `PORT=18080` — MUST stay (avoids systemd clash); MODEL lines still STALE.
- `jarvis-cli.sh:222-224` `safe-nixos-apply.sh:25` `roo-nightwatch-setup.sh:66` curl `:8080/:8081/:8082` — MUST stay.
- `moe-profiler.py:238` `model=Qwen3.6` STALE label; `:300` default URL MUST stay. `archive/*duplicate*.sh` — STALE, deletable.

**`docs/benchmarks/`** — all HISTORICAL (keep as logs, stale if read as live config):
- `bonsai-vs-qwen-2026-09-05.md:12,14,26,83` `Ternary-Bonsai-8B-Q2_0_g64.gguf/-ngl99/-c32768/:8080` — current-true log.
- `results/20260826-*/basics,ncmoe35,ehs25` + `ncmoe-sweep.md:5` + `gpu-moe-fix-2026-08-28.md:9,22` + `README.md:70,88` Qwen3.6/ngl45/ctx4-8K — superseded by Bonsai era.

**`webui/`** — `webui/api.py:252-254,520-522,528,535,362` cfg passthrough + `.gguf` stem-strip + Bonsai comment — MUST stay (derived). `frontend/src/routes/{llm,config,+page}.svelte` + `lib/stores/jarvis.ts:27` display `llm.model` — MUST stay.

**.env** — zero `**/.env*` in repo; refs (`home.nix:24,169,183-187,430-431`, `litellm-cascade.nix:23`, `hosts/*/configuration.nix`) point to `/etc/litellm.env`, `/etc/jarvis-{telegram,secrets}/*` (out-of-repo) — MUST stay, no model duplication found.

**Tests LLM/backend/routing**
- `test_llm_backend.py` — factory llama-cpp/prismml/bonsai, unknown-backend error, `n_ctx=32768`, telemetry.
- `test_llm.py` — thinking toggle, breaker chat-8080≠embed-8081 isolation, `/props` n_ctx autodetect.
- `test_router.py/test_rules.py/test_read_route.py/test_benchmark.py` — intent routing/fastpaths (router mocks, not model-specific).
- `test_config.py` — `JARVIS_LLM_BASE_URL` env override. `test_p7_context_budget.py` — n_ctx autodetect.
- `test_reranker.py` — rerank ordering. `test_circuit_breaker.py:314` bonsai-down injection.
- `test_heal.py:50` allowlist `llama-cpp-server/embeddings`. `test_gaming.py:197,387` stop-list asserts.
- `test_solar_probe.py:314-391` manual harness template (`JARVIS_LLM_MODEL/BASE_URL :8080`).

---

