# Duplication Analysis: agent.py vs dev.py

## Overview

`agent.py` (785 lines) and `dev.py` (1311 lines) both implement a tool-calling
agent loop with **6 areas of duplication**. In each case, dev.py has the better
version (bug fixes, cleaner API, more formats). agent.py has the worse version
(bugs that dev.py already fixed).

## Side-by-Side Comparison

### 1. Profile Detection

| | agent.py `detect_profile()` | dev.py `_detect_profile()` |
|---|---|---|
| **MoE handling** | `"3b" in m` matches "35b-a3b" → classifies as "tiny" | Regex `(?<![a-z])(\d+)b(?!\\w)` → correctly gets 35 |
| **Model discovery** | None (caller passes model_id) | Queries `/models` endpoint at startup |
| **Bug** | `"3b" in "qwen3.6-35b-a3b"` = True → "tiny" | None |
| **Fix** | Use dev.py's regex version | Already correct |

### 2. LLM HTTP Call

| | agent.py `Agent._chat()` | dev.py `_call_llm()` |
|---|---|---|
| **parallel_tool_calls** | Sends it → llama-server rejects HTTP 400 | Removed |
| **chat_template_kwargs** | Sends it unconditionally | Only sends when disable_thinking=True |
| **Error handling** | `resp.raise_for_status()` only | Structured debug output |
| **Session** | Uses `requests.Session` with retry | Uses `requests.post` directly |
| **Bug** | HTTP 400 from rejected fields | None |

### 3. Text Fallback Parsing

| | agent.py `extract_fallback_tool_call()` | dev.py `_parse_text_actions()` |
|---|---|---|
| **Formats** | 3: `<tool_call>`, `json codeblock`, raw JSON | 4: `<function>`, SEARCH/REPLACE+shell, JSON tags, raw JSON |
| **Dedup** | No | Yes (`_dedupe_actions`) |
| **Hermes format** | No | Yes (`<function=name><parameter=key>value`) |
| **Shell blocks** | No | Yes (extracts bash/sh/shell code blocks) |
| **Aider format** | No | Yes (SEARCH/REPLACE markers) |

### 4. Tool Call Normalization

| | agent.py `normalize_tool_calls()` | dev.py `_to_tool_calls()` |
|---|---|---|
| **ID generation** | `call_fallback-{i}` (resets each turn) | `call_{uuid4().hex[:8]}` (unique always) |
| **Bug** | Duplicate IDs cause HTTP 400 on history growth | None |

### 5. Message Management

| | agent.py | dev.py |
|---|---|---|
| **Token estimation** | None | `_estimate_tokens()` heuristic |
| **Trimming** | None | `_trim_messages()` with user boundary safety |
| **Compaction** | None | `_compact_session()` preserves system + summary + recent |
| **Auto-compact** | None | Built into `_run_agent_loop()` at 70% threshold |

### 6. Tool Execution

| | agent.py `Agent._execute_tool()` | dev.py `_execute_tool_call()` |
|---|---|---|
| **Target** | Shell commands with allowlist + approval | devtools (read_file, str_replace, etc.) |
| **Approval** | Terminal stdin or Telegram buttons | Rich Confirm prompt |
| **Audit** | JSONL audit trail | None (handled by devtools) |
| **MCP** | Supports MCP tools | No MCP |
| **These are DIFFERENT** | Different use cases, should stay separate |

## Consolidation Plan

### Create: `jarvis/core/agent_loop.py`

Extract these functions (using dev.py's better versions):

```python
# From dev.py (fixed MoE bug)
detect_profile(model_id: str) -> dict[str, Any]

# From dev.py (clean payload, no rejected fields)
build_chat_payload(model_id, messages, profile, *, tools, disable_thinking) -> dict

# From dev.py (4-format superset with dedup)
parse_text_actions(content: str) -> list[dict] | None

# From dev.py (UUID IDs)
normalize_tool_calls(raw_tool_calls: Any) -> list[dict]
actions_to_tool_calls(actions: list[dict] | None) -> list[dict] | None

# From dev.py (message management)
estimate_tokens(messages: list[dict]) -> int
trim_messages(messages: list[dict], max_messages=20) -> list[dict]
compact_session(messages: list[dict], max_tokens=6000) -> list[dict]
```

### Update: `agent.py`

Replace local implementations with imports from `agent_loop`:
- `from .agent_loop import detect_profile, normalize_tool_calls, parse_text_actions, actions_to_tool_calls`
- Remove: `detect_profile()`, `_extract_json_object()`, `extract_fallback_tool_call()`, `_normalize_tool_call()`, `normalize_tool_calls()`
- Update `Agent._chat()` to use `build_chat_payload()`
- Update `Agent._run_loop()` to use `parse_text_actions` + `actions_to_tool_calls`

### Update: `dev.py`

Replace local implementations with imports from `agent_loop`:
- `from jarvis.core.agent_loop import detect_profile, build_chat_payload, parse_text_actions, actions_to_tool_calls, estimate_tokens, trim_messages, compact_session`
- Remove: `_detect_profile()`, `_call_llm()` (inline version), `_parse_text_actions()`, `_to_tool_calls()`, `_estimate_tokens()`, `_trim_messages()`, `_compact_session()`
- Keep: `_get_tools()`, `_execute_tool_call()`, `_run_agent_loop()` (UI logic), REPL commands

### Lines Impact

| File | Before | After | Delta |
|------|--------|-------|-------|
| agent_loop.py | 0 | ~180 | +180 |
| agent.py | 785 | ~620 | -165 |
| dev.py | 1311 | ~1050 | -261 |
| **Net** | 2096 | ~1850 | **-246** |

## Bugs Fixed by Consolidation

1. **agent.py MoE misclassification** — "qwen3.6-35b-a3b" → "tiny" instead of "large"
2. **agent.py HTTP 400** — parallel_tool_calls/chat_template_kwargs rejected by llama-server
3. **agent.py duplicate tool_call IDs** — "fallback-0" reused across turns → HTTP 400
4. **agent.py limited text parsing** — only 3 formats vs dev.py's 4
5. **agent.py no message management** — no trimming, compaction, or token estimation
