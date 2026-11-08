# Router backend audit (@general subagent)

- **sessão:** `ses_f7e857985ffelDU8VBYQaiATlu`
- **quando:** 2026-09-08 14:44 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit the model/provider routing chain. Read: modules/ai/jarvis/src/jarvis/providers/llm.py (LLMClient, backends, detect_profile), llm_factory/create_backend, llm_llama_cpp.py, llm_prismml.py, llm_backend.py, core/provider_registry.py (who imports it? verify zero consumers), core/config.py Config fields for llm_backend/llm_model/llm_base_url, control_plane/commands.py model-related commands, webui/api.py model selection endpoints, cli REPL model flags (--model?), voice.py model usage. Answer: (1) how does a request choose backend+model today (exact code path REPL→Agent→LLMClient→backend, with file:line); (2) what does llm_model="default" resolve to; (3) is there ANY local model routing (by task/capability/latency)?; (4) what capability metadata exists (if any); (5) list every place a model name/URL is hardcoded in Python. Max 90 lines. Do NOT change anything.

---

## · ?

Auditing the model routing chain — tracing REPL to backend without edits.

---

## · ?

Found the core backend chain and policy tables — now checking REPL, API, and voice paths.

---

## · ?

Confirmed zero live consumers for the registry — now pinning down exact resolution paths and hardcoded names.

---

## · ?

AUDIT — model/provider routing (read-only, no edits)

(1) REQUEST PATH TODAY (single-backend, no switch):
- REPL `cli/dev.py:2027` `active_model=profile["name"]`; `/model` at `2090-2091` display-only.
- REPL `_detect_profile():264-314`: `model_id=cfg.llm_model` (`270`) else `GET {llm_base_url}/models[0].id` (`272-276`); regex `\d+B` → large/small/tiny/default (`291-298`); `n_ctx` via `/props` (`303-307`); `native_tools=name!="tiny"` (`313`).
- REPL `_call_llm():930-977`: `Config(llm_model=model_id)` (`969`) → `LLMClient(config)` (`971`) → `chat_with_tools(...,temp/max_tokens=profile)` (`972-977`).
- `Agent` (`cli/main.py:450-454` → `core/agent.py:269-274`): `LLMClient(self.config)` (`273`); `_get_llm_response():581-648`: `detect_profile(config.llm_model)` (`592`) tunes only temp/max_tokens (`646-647`), then `self.llm.chat_with_tools()` (`643`).
- `LLMClient.__init__ providers/llm.py:188-204` → `create_backend(cfg)` `llm_factory.py:49-60`: `backend=cfg.llm_backend`; `LlamaCppBackend(base_url=cfg.llm_base_url.strip("/v1"), model=cfg.llm_model)` (`53-56`); same for prismml/bonsai (`62-83`).
- `LlamaCppBackend.chat llm_llama_cpp.py:95-147`: payload `{"model":self._model,...}` (`109-110`) → `POST {base}/v1/chat/completions` (`124-125`); stream idem (`149-216`).
- voice `core/voice.py:691` `LLMClient(get_config())` only for `check_load`; `720` → `router.py:394-407 handle_agent→Agent(cfg)`. No model arg.
- `control_plane/commands.py`: zero model commands (generic registry only). `webui/api.py:511-546 /api/llm`, `241-258 /api/config`: read-only display; `POST /api/config:281-295` only timeout/thinking/tavily.

(2) `llm_model="default"` RESOLVES TO:
- `core/config.py:41` default `JARVIS_LLM_MODEL||"default"`. Passed verbatim as `"model"` in every payload. llama-server ignores it, serves loaded GGUF.
- Real name discovered best-effort only for display/telemetry: `dev.py:272-276 /models[0].id`, `llm_llama_cpp.py:288-290 /props.default_generation_settings.model`, `webui/api.py:528-538` (strips 32-char hash prefix), `LLMClient._resolve_model_id llm.py:297-310` — dead (no callers).

(3) LOCAL ROUTING BY TASK/CAPABILITY/LATENCY? NO:
- `core/provider_registry.py:route()/route_for_persona():185-236` returns ordered list, filters by DataClass/persona/task/latency — ZERO consumers (grep: no imports anywhere).
- `core/model_policy.py:ModelPolicy.select_tier():171-196` (stage→cheap/medium/strong + VRAM downgrade) consumed only by `nightwatch/platform_bridge.py:87-88` + `self_test.py:603`; never by Agent/REPL/voice/webui.

(4) CAPABILITY METADATA (all unused in hot path):
- `provider_registry.py:46-53 ModelCaps{context,tools,reasoning,vision,latency}` + `PERSONA_ROUTING:164-168, TASK_ROUTING:170-175`, pools `LOCAL_BONSAI/CEREBRAS/GROQ/GEMINI/NVIDIA/OPENROUTER/OMNI/9ROUTER:69-147`.
- `model_policy.py:23-32 ModelTier{model_name,context_size,tps,vram}` + `STAGE_TIER_MAP:78-109, WORKFLOW_TIER_MAP:112-136`.
- Live only: `llm_backend.py:65-73 BackendInfo{backend_type,model_name,n_ctx,n_gpu_layers}` + `detect_profile large/small/tiny agent.py:36-66` (max_tokens/temp/tool_choice).

(5) HARDCODED MODEL NAME/URL IN PYTHON:
- `config.py:37 llama-cpp, :40 127.0.0.1:8080/v1, :41 "default", :49 :8081/v1, :53 :8082, :56 :6333, :70 nomic-embed-text-v2, :71 768`
- `llm_llama_cpp.py:71 127.0.0.1:8080, :73 "default"`; `llm_prismml.py:71,73` same; `llm_factory.py:51,62,73 "llama-cpp/prismml/bonsai"`
- `model_policy.py:51 qwen3.6-4b, :60 qwen3.6-moe-14b, :69 qwen3.6-moe-35b`
- `provider_registry.py:71 127.0.0.1:8080/v1, :74 bonsai-8b, :75 qwen3-35b-a3b, :80-146 cerebras/groq/gemini/nvidia/openrouter URLs+models, :135,143 localhost:20128`
- `voice.py:35 STT_MODEL_DEFAULT="small"`; `health_monitor.py:49,56 127.0.0.1:8080`; `reranker.py:33 127.0.0.1:8082`; `state.py:63 qwen3.6-35b`; `hwprofile.py:113,119 qwen3.6-27b/35b-a3b, :515 faster-whisper-small, :521 nomic-embed-text-v2-moe`; `experiment_tracker.py:80 llama-cpp`. `--model` flags (`cli/main.py:926,942`) are STT-only, never LLM.

---

