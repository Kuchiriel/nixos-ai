# Bypass audit research (@general subagent)

- **sessão:** `ses_f7ea66decffe26hREcDcHaX7GK`
- **quando:** 2026-09-08 14:08 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 7 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only research, NO edits), audit BYPASSES: production code paths that skip canonical services/policies. Focus on modules/ai/jarvis/src/jarvis/. Look for: (1) direct HTTP calls to llama.cpp/LLM bypassing LLMClient (grep for requests.post, httpx, urllib, LLM URL env vars like JARVIS_LLM_URL, LLAMA_CPP_URL); (2) voice code calling backends directly; (3) tools using subprocess/shell directly vs a canonical runner; (4) REPL/CLI duplicating logic instead of calling library; (5) MCP handlers reimplementing instead of delegating to canonical implementations; (6) WebUI/control-plane mutating state directly; (7) config reads bypassing config.py (os.environ/getenv for canonical settings). For EACH finding: file:line, code snippet, classification candidate (VALID/NECESSARY/LEGACY/BUG) with one-line justification. Max 80 lines output. Do NOT fix anything.

---

## · ?

Auditing bypasses in read-only mode — mapping direct calls that skip canonical services.

---

## · ?

Found initial bypass candidates — pulling code snippets to classify each one.

---

## · ?

Core patterns are clear — checking the remaining edge cases to finalize classifications.

---

## · ?

BYPASS AUDIT — `modules/ai/jarvis/src/jarvis/` (read-only, no fixes):

**1. Direct HTTP to LLM (bypass `providers/llm.py:LLMClient`):**
- `core/vision.py:303` `r=requests.post(f"{api_url}/v1/chat/completions",json=payload,timeout=180)` — **BUG**: hand-rolled chat call, skips breaker/retry/telemetry/fallback in `LLMClient`; `api_url` from `get_config().llm_base_url` but not via client.
- `cli/launcher.sh:73,88` `curl -s ... http://localhost:8080/slots|health` — **LEGACY**: shell health probe duplicating `core/health_monitor.py`+`doctor.py`.
- `providers/reranker.py:51` `requests.post(f"{self._base}/rerank",...)` — **VALID**: reranker has no `LLMClient` path; own canonical provider.
- `providers/telegram.py:45` `requests.post(url,json=kwargs...)` — **VALID**: external Telegram Bot API, `http_service.py` not mandatory.
- `core/hackmd.py:72` / `core/websearch.py:42` `requests.post(API_BASE|TAVILY_ENDPOINT...)` — **VALID**: external APIs, no canonical HTTP runner for these.
- `providers/llm_llama_cpp.py:233` `httpx.AsyncClient` — **VALID**: this *is* canonical `LLMClient` backend impl.
- `core/provider_registry.py:71` `base_url="http://127.0.0.1:8080/v1"` hardcoded default — **BUG**: duplicates `core/config.py:40` `JARVIS_LLM_BASE_URL`.

**2. Voice calling backends directly:**
- `core/voice.py:150,414` `from kokoro import KModel,KPipeline` + `:511` `subprocess.run(mpg123...)` + `:606` `_stt_proc=subprocess.run(_stt_cmd...)` — **VALID**: `voice.py` *is* canonical voice layer; subprocess isolates CTranslate2/torch.
- `core/watchdog.py:86-88` `from jarvis.core.voice import speak as tts_speak; tts_speak(message,play=True)` — **NECESSARY**: in-process TTS avoids systemd `PATH` issues per comment; bypasses notification-manager policy.
- `core/audiobook.py:644` `from jarvis.core.voice import speak` — **VALID**: correct delegation.
- `core/voice_clone.py:96,147` `subprocess.run(RVC probe/infer, env=custom)` — **NECESSARY**: needs custom `LD_LIBRARY_PATH/CUDA_VISIBLE_DEVICES`; `security.run_shell` can't express env.

**3. `subprocess` vs canonical `core/security.py:122 run_shell`:**
- `core/gaming.py:91,106,139,149,198...` `subprocess.run(...)` ×10; `core/vision.py:55,87,96,126,147,165`; `core/devtools.py:580,621,666,700,975,1195,1218`; `core/heal.py:104,239`; `core/evidence.py:118,258,271,285`; `mcp_server.py:474` — **BUG**: raw `subprocess` bypasses `is_safe_command` allowlist + `shlex` no-`shell` policy.
- `control_plane/systemd_adapter.py:155,219,228` `subprocess.run(systemctl...)` + `control_plane/notifications.py:59,99` `notify-send/pkill` — **NECESSARY**: privileged/systemd scope outside `run_shell` allowlist.
- `core/audiobook.py:533` `subprocess.Popen(daemon...)` — **NECESSARY**: detached playback, `run_shell` is blocking-only.

**4. CLI/REPL duplicating library:**
- `cli/dev.py:1111` `subprocess.run(["nix","eval","--json",expr])`, `:1116` `nix flake check`, `:1124` `nix search` — **BUG**: reimplements `core/devtools.py`/`core/nixos.py` instead of calling.
- `cli/main.py:298,314,322` `subprocess.run(top|journalctl|systemctl)` — **LEGACY**: duplicates `core/doctor.py`+`core/heal.py`.
- `cli/dev.py:941,971` `with _LLMClient(config=...) as client` — **VALID**: fixed, delegates (comment at `:930-934` notes prior `requests.post` removed).

**5. MCP reimplementing vs delegating:**
- `mcp_server.py:464-478` `_vault_read_from_obsidian: OBSIDIAN_VAULT=~/vaults/projects; subprocess.run(["rg",...])` + `:487` hardcoded vault paths — **BUG**: reimplements search, bypasses canonical `core/vault.py:MemoryVault`.
- `mcp_server.py:816,833` `from jarvis.core.vault import MemoryVault` — **VALID**: correct delegation elsewhere.
- `mcp_server.py:720` `subprocess.Popen(mcp-nixos stdio bridge)` — **VALID**: no canonical runner for JSON-RPC stdio bridge.

**6. WebUI/control-plane direct mutation:**
- `webui/api.py:286-290` `os.environ["JARVIS_LLM_DISABLE_THINKING"|"JARVIS_LLM_TIMEOUT"|"TAVILY_API_KEY"]=...` — **BUG**: mutates env, bypasses `config.py` setter + `control_plane/state.py:get_state_store`.
- `webui/api.py:302-304,341-346` `plane._systemd=get_systemd_adapter(); plane._systemd.start/stop/restart` — **BUG**: touches private `_systemd`, bypasses `plane.py` lazy-init + `commands.py:Risk` approval.

**7. Config reads bypassing `core/config.py`:**
- `core/agent.py:217,231` `MAX_TURNS=int(os.environ.get("JARVIS_AGENT_MAX_TURNS","8"))` (import-time) — **BUG**: frozen at import, ignores `get_config()` + WebUI updates.
- `core/voice_clone.py:25` local `_cfg(name,default)=os.environ.get` — **BUG**: shadow config system.
- `core/voice.py:35,40-42,80,114` `JARVIS_STT_MODEL/KOKORO_*/TTS_LANG/VOICE_DIR`; `core/queue.py:33` `JARVIS_STATE_DIR`; `core/feedback.py:32`; `core/vision.py:26`; `cli/dev.py:498`; `core/agent.py:346` `os.environ.get('USER')` — **LEGACY**: pre-`config.py` defaults; migrate to `get_config()` fields.
- `webui/api.py:248,276` `os.environ.get("TAVILY_API_KEY"|"TELEGRAM_BOT_TOKEN")` vs `core/keys.py:80` canonical loader — **LEGACY**: duplicates secret resolution.

---

