"""Padrões regex para extração de tool_calls do Qwen.

Padrões compartilhados entre agent.py e dev.py para extração de
tool_calls vazados como texto (formato nativo do Qwen com llama.cpp).
"""

from __future__ import annotations

import re

# Tag nativa <tool_call>{...}</tool_call> que o Qwen2.5/3.6 usa para tool calls
TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

# JSON em code block ```json {...} ``` ou ``` {...} ```
CODEBLOCK_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

__all__ = ["TOOL_CALL_TAG_RE", "CODEBLOCK_JSON_RE"]
