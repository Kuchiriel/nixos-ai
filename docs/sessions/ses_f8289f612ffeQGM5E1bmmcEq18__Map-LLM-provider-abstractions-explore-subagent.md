# Map LLM provider abstractions (@explore subagent)

- **sessão:** `ses_f8289f612ffeQGM5E1bmmcEq18`
- **quando:** 2026-09-07 20:01 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 10 (exportadas: 1)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Explore the JARVIS codebase at /home/nixos/projects/nixos-ai/modules/ai/jarvis/src. Be thorough. Focus on the LLM provider abstraction layer, which is suspected of being bypassed by the REPL path.

Read these files:
- jarvis/providers/llm.py (500 lines) - contains class LLMClient at line 163
- jarvis/providers/llm_backend.py
- jarvis/providers/llm_factory.py
- jarvis/providers/llm_llama_cpp.py
- jarvis/providers/llm_prismml.py
- jarvis/providers/interfaces.py
- jarvis/providers/http_service.py
- jarvis/core/model_policy.py
- jarvis/core/provider_registry.py

Report precisely:
1. What is class LLMClient's full public API (methods, signatures, params)? What backends does it support?
2. What is LLMFactory / how does one obtain an LLMClient?
3. Who in the codebase actually uses LLMClient/LLMFactory (grep imports in src and tests)? Does the REPL path (cli/main.py, core/agent.py) use it? Where is the REPL's LLM HTTP call actually made?
4. Is there duplicated provider/backend logic across files? Are there two fallback mechanisms? Any privacy/security policy bypass (e.g., a local→remote fallback that ignores privacy classification)?
5. Report jarvis/core/model_policy.py and provider_registry.py purposes.

Return a structured report with file:line references. Do NOT modify anything.

---

