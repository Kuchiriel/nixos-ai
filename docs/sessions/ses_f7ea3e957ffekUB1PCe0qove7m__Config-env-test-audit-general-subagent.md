# Config env test audit (@general subagent)

- **sessão:** `ses_f7ea3e957ffekUB1PCe0qove7m`
- **quando:** 2026-09-08 14:11 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit three areas: (A) CONFIG/ENV: all os.environ/getenv in modules/ai/jarvis/src/jarvis/ + Environment= in home-manager/modules/services/*.nix — build a variable table (variable, writer, reader, required?) and flag global mutation, shadowing, typos, dead vars, service-only vs shell-only. Note config precedence (default/env/CLI/Nix/config-file/runtime — who wins). (B) NIX REPRODUCIBILITY: check flake/modules for imperative deps — manual model paths, ~/.config writes, /tmp reliance, manual downloads, generated shell files; classify required-persistent/cache/runtime-state/declarative-violation. (C) TEST INTEGRITY: in modules/ai/jarvis/tests/ — count tests, find order-dependence risks (shared tmp paths, fixed ports, global env, Qdrant leftovers), explain sandbox-vs-local count divergence (which tests need live Qdrant/llama.cpp/systemd/audio), verify the 5 known infra failures' documented cause. Compact output, max 90 lines, file:line evidence. Do NOT fix.

---

## · ?

Auditing config, reproducibility, and tests — read-only sweep in progress.

---

## · ?

Initial hits mapped — now digging into precedence, services, and test isolation.

---

## · ?

Core variables charted — now checking mutation points and known failure docs.

---

## · ?

READ-ONLY AUDIT — nixos-ai (no edits)

(A) CONFIG/ENV — readers in `core/config.py:15-30`, `keys.py:76-83`, `paths.py:47`
| Variable | Writer (Nix/shell/runtime) | Reader | Req? |
|---|---|---|---|
| JARVIS_LLM_BASE_URL/MODEL/TIMEOUT/DISABLE_THINKING/TOOL_CALLING, EMBED/RERANK/QDRANT_URL, STATE/VAULT_DIR, EMBED_MODEL/DIM, QDRANT_COLLECTION_*, MCP_NIXOS_BIN, RICH_CONTENT/INDEX_EXCLUDE | default in `config.py:37-99`; env (shell/keys-wrapper); Nix service `Environment=` | `config.py:37-99` via `get_config():106` | no (defaults 127.0.0.1:8080/8081/8082/6333) |
| TAVILY_API_KEY / HMD_TOKEN / GROQ/GEMINI/OPENROUTER / JARVIS_TELEGRAM_TOKEN+CHAT_ID (+aliases TELEGRAM_BOT_TOKEN/CHAT_ID, GOOGLE_API_KEY) | `keys-wrapper.sh→/etc/litellm.env`, `EnvironmentFile=-/etc/*.env`, WebUI `api.py:290,453` | `keys.py:20-41,76-83`; direct `api.py:248,276`, `websearch.py:4` | only at use (`keys.require():86`); else `""` |
| JARVIS_PROJECT_ROOT | `paths.set_project_root():75` (only legit); shell export | `paths.find_repo_root():47` | no (walk-up→`~/projects/nixos-ai:62`) |
| JARVIS_STT_MODEL/TTS_LANG/KOKORO_*/VOICE_DIR/BOOKS_DIR/STATUS_FILE/BASE_DIR/AGENT_MAX_TURNS/TOOL_OUTPUT/PRISMML_BIN/RVC_* / LANG/LC_ALL/USER/LOGNAME/WAYLAND/DISPLAY | service `jarvis-wakeword.nix:707-725`; shell; CLI `--model` | `voice.py:35-42,80,114`, `audiobook.py:35`, `feedback.py:32`, `regression.py:30`, `agent.py:217,231,346`, `llm_prismml.py:257`, `voice_clone.py:63-82`, `lang.py:16`, `vision.py:32` | no (defaults) |
Flags: GLOBAL MUTATION `api.py:286,288,290` (`os.environ[...] strobes Config` — frozen dataclass `config.py:33` already instantiated → stale until re-`get_config()`; `api.py:293 cache_clear` dead — `get_config` has no cache); import-time `voice_clone.py:249-250` (`CUDA_VISIBLE_DEVICES=""` on `JARVIS_RVC_CPU_ONLY=1`, process-global side effect; +`paths.py:75` intended). SHADOW: `api.py:276` reads `TELEGRAM_BOT_TOKEN` ≠ `config.py:66 JARVIS_TELEGRAM_TOKEN` (aliased only in `keys.py:31`); `api.py:248` direct TAVILY bypasses `keys.get("tavily")`; `JARVIS_VOICE_DIR` vs `MODEL_DIR_DEFAULT` (`voice.py:114`). DEAD/SUSPECT: `JARVIS_SKIP_VERIFY` (`heal.py:325`), `JARVIS_BASE_DIR` (`regression.py:30` vs canonical `paths.py`), `JARVIS_PRISMML_BIN` opt-only, `CUDA_VISIBLE/LD_LIBRARY_PATH` injected (`voice_clone.py:98,146`). SERVICE-ONLY (not in shell): `wakeword.nix:707-725` PATH/DBUS/DISPLAY=:0/WAYLAND=wayland-1/TTS_LANG/STT/RVC_*; SHELL-ONLY: `keys-wrapper.sh`, `/etc/litellm.env`. MISMATCH: hardcoded `DISPLAY=:0/WAYLAND=wayland-1` vs dynamic `vision.py:32`.
Precedence: `paths.py:39-42` task-ctx>`JARVIS_PROJECT_ROOT` valid-dir>walk `.git/flake.nix` (10lv)>fallback; `keys.py:76-83` env>legacy file; `voice_clone.py:60` arg>env>auto-detect `~/models`; `config.py` default<env; CLI (`main.py:777-888 --top-k/--model/--offline`) is per-command local, does NOT rebind global `Config`; WebUI runtime `os.environ` wins in-process but ephemeral; Nix `Environment=` wins for systemd unit only.

(B) NIX REPRO — `modules/ai/models.nix:27,104-176` fetchurl+sha256 declarative GOOD (single truth per AGENTS.md).
Required-persistent (OK, Nix-sourced): `wakeword.nix:55-82,690-694` `modelsLink` store→`~/.local/share/{kokoro,openwakeword,jarvis/voice}` via activation `run link-models.sh` (imperative runner, declarative content); `voice.py:40-42` kokoro defaults; `~/.local/state`, `~/Books` (`audiobook.py:35`, `config.py:59`).
Runtime-state (ephemeral OK): `/tmp/jarvis-status.json` (`wakeword.nix:128,322,503`, `feedback.py:32`, `voice_clone` docs), `/tmp/jarvis-wakeword-status:265`, `/tmp/jarvis_cmd_*.wav:331`, `SCREENSHOT_DIR=/tmp` (`vision.py:26`).
Declarative-violation: `wakeword.nix:720-724`+`voice_clone.py:9-12,81-82` `JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv`, `RVC_APP_DIR=/tmp/opencode/applio` (manual venv+checkout, GC-unsafe, self-doc “some no reboot”); `JARVIS_VOICE_CLONE_MODEL/INDEX=~/models/*.pth/*.index` (`wakeword.nix:723-724`, `voice_clone.py:33-40` glob) — manual, untracked; `api.py:436-482` writes `/etc/litellm.env` at runtime + `chmod 644` (world-readable secret, should be 600) + `export KEY=` prefix inconsistent with `keys.py:62-70` parser (tolerated). No `curl/wget` left (`wakeword.nix:74` removed) — clean.

(C) TESTS — `modules/ai/jarvis/tests/`: 1020 `def test_` in 70 files.
Order risks: fixed shared paths `test_mcp_tools_e2e.py:151,164` `/tmp/jarvis_mcp_*.txt` (parallel/order collision; most others use `tmp_path` — safe); no fixed-port bind (8080/81/82/6333 only as default-assert `test_config.py:10-11` or `pytest.skip` guards `test_integration.py:22,29,53`); global env mostly `monkeypatch.setenv/delenv` (auto-undo, e.g. `test_jarvis_assistant.py:53-185`) EXCEPT `api.py:286-290` + `voice_clone.py:250` process-global; Qdrant leftovers: `test_rag/memory/vault.py:3` all `pytestmark=integration` but use fakes/pure fns — live run shares collection names `code_index/memories/books` (`config.py:74-76`) with no cleanup (only `FakeStore.created/deleted` tracked `test_memory.py:14-27`); `nightwatch_*` isolation now via `use_project_root` contextvar (`paths.py:80`), old `REPO_ROOT` monkeypatch removed.
Divergence: `conftest.py:33-44` sandbox (`NIX_SANDBOX` or no `git`) drops 9 files by NAME (`harness/longrun/nightwatch_*/platform/p3/p5`); `test_mcp_tools_e2e.py:25-29` additionally `skipif NIX_BUILD_TOP|/homeless-shelter`; live-gated `pytest.skip` on 8080/6333 (`test_integration.py:22,53`), faster-whisper-mocked (`test_voice.py:24-30`), systemctl-mocked (`test_gaming.py:174-350`, `test_heal.py:35`). Hence sandbox 834 passed/0 failed vs local ~998+ (`FORENSIC-2026-09-08.md:243-244`).
5 infra failures: docs verify count+partial cause only — `DEEP-AUDIT-2026-09.md:184` “987 passed/5 failed (pré-existentes infra: nightwatch_real_e2e, platform_e2e)”, `FORENSIC-2026-09-08.md:222,244` “998+/5 infra (mesmas)”; other 3 unnamed in evidence — inferred from markers: live-Qdrant/llama.cpp (`test_integration/rag/memory/mcp_tools_e2e`), systemd (`test_heal/gaming`), audio/hw (`test_voice`, STT/Kokoro/RVC). `test_rag.py:1` docstring “sem serviços” contradicts its own `pytestmark=integration` — mislabeled.

---

