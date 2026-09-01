"""Context Budget Manager — unified context management for all JARVIS systems.

Consolidates:
- jarvis/core/context_budget.py (truncation by priority)
- nightwatch/context_budget.py (tracking and analytics)

Responsibilities:
1. Estimate tokens per message (~4 chars/token)
2. Truncate tool outputs by priority when budget is low
3. Warn when context >80% of budget
4. Compress old history when needed
5. Track context usage metrics
6. Provide adaptive condensing recommendations
7. Query actual n_ctx from llama.cpp
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Heuristic: ~4 chars per token for models with GPT-like tokenizer
CHARS_PER_TOKEN = 4

# Tool outputs are the biggest consumer — truncate first
TOOL_OUTPUT_PRIORITY = {
    "execute_shell": 1,      # Most important — command result
    "read_file": 2,          # File content
    "code_search": 3,        # Search result
    "list_directory": 4,     # Directory listing
    "capture_screen": 5,     # Screenshot (metadata)
    "str_replace": 6,        # Edit confirmation
    "write_file": 7,         # Write confirmation
    "run_tests": 8,          # Test output
}

# Truncation limits by priority
TRUNCATE_LIMITS = {
    1: 4000,   # execute_shell: up to 4K chars
    2: 3000,   # read_file: up to 3K chars
    3: 2000,   # code_search: up to 2K chars
    4: 1000,   # list_directory: up to 1K chars
    5: 500,    # capture_screen: metadata only
    6: 500,    # str_replace: confirmation
    7: 500,    # write_file: confirmation
    8: 3000,   # run_tests: up to 3K chars
}

# State directory for logging
STATE_DIR = Path.home() / ".local/state/jarvis"
CONTEXT_LOG = STATE_DIR / "context_usage.jsonl"


def query_server_context_size() -> int:
    """Query llama.cpp /props endpoint for actual n_ctx.

    Returns 0 if server is unavailable.
    """
    import os
    try:
        import requests
        base_url = os.environ.get("LLAMA_CPP_URL", "http://127.0.0.1:8080")
        # /props is at root, not under /v1
        base = base_url.rstrip("/").replace("/v1", "")
        resp = requests.get(f"{base}/props", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        n_ctx = data.get("default_generation_settings", {}).get("n_ctx", 0)
        if n_ctx > 0:
            return n_ctx
    except Exception:  # noqa: BLE001
        pass
    return 0


@dataclass
class ContextSnapshot:
    """A single point-in-time measurement of context usage."""
    timestamp: float = field(default_factory=time.time)
    tokens_used: int = 0
    tokens_budget: int = 8192
    tool_calls_in_context: int = 0
    messages_in_context: int = 0
    files_read: int = 0
    files_written: int = 0
    compaction_event: bool = False
    tokens_before_compaction: int = 0
    tokens_after_compaction: int = 0
    latency_ms: int = 0
    phase: str = ""  # "discovery", "execution", "validation", "review"


@dataclass
class ContextBudget:
    """Unified context budget manager for all JARVIS systems.

    Usage:
        budget = ContextBudget(max_tokens=32000)
        for msg in messages:
            budget.add_message(msg)
        if budget.usage_percent > 80:
            budget.truncate_tool_outputs()
            budget.compress_history()
    """
    max_tokens: int = 32000
    reserved_tokens: int = 2000  # Reserved for system prompt + response
    warning_threshold: float = 0.80  # 80% of budget
    compaction_threshold: float = 0.85  # Compact at 85% (was 0.70 — too aggressive)

    # Truncation limits
    max_tool_output_tokens: int = 2000
    max_file_content_tokens: int = 8000

    # Accumulated state
    _total_tokens: int = field(default=0, init=False)
    _messages: list[dict[str, Any]] = field(default_factory=list, init=False)
    _tool_message_indices: list[int] = field(default_factory=list, init=False)

    # Analytics (from nightwatch version)
    snapshots: list[ContextSnapshot] = field(default_factory=list)
    total_tokens_processed: int = 0
    total_compactions: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    phase_tokens: dict[str, int] = field(default_factory=dict)
    phase_calls: dict[str, int] = field(default_factory=dict)

    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.reserved_tokens

    @property
    def used_tokens(self) -> int:
        return self._total_tokens

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.available_tokens - self._total_tokens)

    @property
    def usage_percent(self) -> float:
        if self.available_tokens <= 0:
            return 100.0
        return (self._total_tokens / self.available_tokens) * 100

    @property
    def needs_warning(self) -> bool:
        return self.usage_percent >= self.warning_threshold * 100

    @property
    def is_overflow(self) -> bool:
        return self._total_tokens > self.available_tokens

    def estimate_tokens(self, text: str) -> int:
        """Estimate tokens from text (~4 chars/token)."""
        return max(1, len(text) // CHARS_PER_TOKEN)

    def add_message(self, msg: dict[str, Any]) -> int:
        """Add a message and return estimated tokens."""
        content = msg.get("content", "")
        if isinstance(content, list):
            # multipart content
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        tokens = self.estimate_tokens(content)

        # Tool calls and arguments also consume tokens
        if "tool_calls" in msg and msg["tool_calls"]:
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                tokens += self.estimate_tokens(func.get("name", ""))
                tokens += self.estimate_tokens(func.get("arguments", ""))

        self._messages.append(msg)
        self._total_tokens += tokens
        self.total_tokens_processed += tokens

        # Mark tool messages for truncation
        if msg.get("role") == "tool":
            self._tool_message_indices.append(len(self._messages) - 1)

        return tokens

    def get_budget_warning(self) -> str | None:
        """Return warning message if budget is low."""
        if not self.needs_warning:
            return None
        pct = self.usage_percent
        remaining = self.remaining_tokens
        return (
            f"⚠️ Context budget: {pct:.0f}% used "
            f"({self._total_tokens}/{self.available_tokens} tokens). "
            f"~{remaining} tokens remaining. "
            f"Prioritize concise responses and minimize tool output."
        )

    def truncate_tool_outputs(self, aggressive: bool = False) -> int:
        """Truncate tool outputs by priority. Returns chars removed."""
        removed = 0
        for idx in reversed(self._tool_message_indices):
            if idx >= len(self._messages):
                continue
            msg = self._messages[idx]
            content = msg.get("content", "")
            if not content or len(content) < 500:
                continue

            # Determine priority by tool name
            tool_name = msg.get("name", "unknown")
            priority = TOOL_OUTPUT_PRIORITY.get(tool_name, 99)
            limit = TRUNCATE_LIMITS.get(priority, 1000)
            if aggressive:
                limit = limit // 2

            if len(content) > limit:
                truncated = content[:limit] + f"\n... [truncated from {len(content)} chars]"
                removed += len(content) - len(truncated)
                msg["content"] = truncated
                # Update token estimate
                old_tokens = self.estimate_tokens(content)
                new_tokens = self.estimate_tokens(truncated)
                self._total_tokens -= (old_tokens - new_tokens)

        return removed

    def compress_history(self, keep_last: int = 6) -> int:
        """Compress old messages, keeping last keep_last.

        Strategy: preserve high-signal content (errors, decisions, file paths,
        task state) while compressing verbose tool outputs and intermediate steps.
        Returns tokens saved.
        """
        if len(self._messages) <= keep_last + 2:
            return 0

        saved = 0
        # Keep: system[0] + user[1] + last keep_last
        compress_end = len(self._messages) - keep_last
        for i in range(2, compress_end):  # Skip system and first user
            msg = self._messages[i]
            content = msg.get("content", "")
            if not content or len(content) < 200:
                continue

            old_tokens = self.estimate_tokens(content)
            role = msg.get("role", "?")

            # Preserve high-signal content
            if role == "tool":
                # For tool outputs: keep first 200 chars + any error/file info
                lines = content.split("\n")
                preserved = []
                for line in lines[:5]:  # Keep first 5 lines
                    preserved.append(line)
                # Also preserve lines with error indicators
                for line in lines:
                    lower = line.lower()
                    if any(kw in lower for kw in ["error", "fail", "traceback", "exception",
                                                   "import", "def ", "class ", "file ",
                                                   ".py", ".nix", "test_"]):
                        if line not in preserved:
                            preserved.append(line)
                            if len(preserved) > 15:
                                break
                summary = "\n".join(preserved)
                if len(content) > len(summary) + 50:
                    summary += f"\n... [compressed from {len(content)} chars — preserved errors/paths]"
            elif role == "assistant":
                # For assistant messages: keep decision-making parts
                if "```" in content:
                    # Code blocks: keep the code, compress surrounding text
                    parts = content.split("```")
                    summary = "```\n".join(parts[1::2]) if len(parts) > 1 else content[:300]
                    summary = f"[Code preserved from compressed assistant message]\n{summary}"
                else:
                    summary = content[:300] + f"\n... [compressed from {len(content)} chars]"
            else:
                # Generic compression
                summary = f"[Earlier {role}: {len(content)} chars compressed]"

            msg["content"] = summary
            new_tokens = self.estimate_tokens(summary)
            saved += (old_tokens - new_tokens)

        self._total_tokens -= saved
        return saved

    # Analytics methods (from nightwatch version)

    def record_snapshot(
        self,
        tokens_used: int,
        tool_calls: int = 0,
        messages: int = 0,
        phase: str = "",
    ) -> ContextSnapshot:
        """Record a context usage snapshot."""
        snapshot = ContextSnapshot(
            tokens_used=tokens_used,
            tokens_budget=self.max_tokens,
            tool_calls_in_context=tool_calls,
            messages_in_context=messages,
            phase=phase,
        )
        self.snapshots.append(snapshot)

        if phase:
            self.phase_tokens[phase] = self.phase_tokens.get(phase, 0) + tokens_used
            self.phase_calls[phase] = self.phase_calls.get(phase, 0) + 1

        # Persist
        self._log_snapshot(snapshot)

        return snapshot

    def should_compact(self, current_tokens: int) -> bool:
        """Determine if compaction should happen."""
        if self.max_tokens <= 0:
            return False
        return current_tokens >= self.max_tokens * self.compaction_threshold

    def record_compaction(self, tokens_before: int, tokens_after: int) -> None:
        """Record a compaction event."""
        self.total_compactions += 1

        # Update the last snapshot
        if self.snapshots:
            last = self.snapshots[-1]
            last.compaction_event = True
            last.tokens_before_compaction = tokens_before
            last.tokens_after_compaction = tokens_after

        # Log event
        event = {
            "timestamp": time.time(),
            "event": "compaction",
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_before - tokens_after,
            "compaction_number": self.total_compactions,
        }
        self._log_event(event)

    def record_llm_call(self, tokens_used: int = 0) -> None:
        """Record an LLM call."""
        self.total_llm_calls += 1
        self.total_tokens_processed += tokens_used

    def record_tool_call(self) -> None:
        """Record a tool call."""
        self.total_tool_calls += 1

    def get_recommendation(self, current_tokens: int) -> dict[str, Any]:
        """Get a recommendation for context management."""
        usage_pct = current_tokens / self.max_tokens if self.max_tokens > 0 else 0

        recommendation = {
            "should_compact": self.should_compact(current_tokens),
            "usage_pct": usage_pct,
            "budget": self.max_tokens,
            "current_tokens": current_tokens,
        }

        if usage_pct > 0.9:
            recommendation["urgency"] = "critical"
            recommendation["action"] = "compact_aggressively"
        elif usage_pct > 0.8:
            recommendation["urgency"] = "high"
            recommendation["action"] = "compact"
        elif usage_pct > 0.6:
            recommendation["urgency"] = "medium"
            recommendation["action"] = "monitor"
        else:
            recommendation["urgency"] = "low"
            recommendation["action"] = "continue"

        # Suggest what to drop
        if usage_pct > 0.7:
            recommendation["suggest_drop"] = [
                "old_tool_outputs",
                "completed_task_history",
                "nonessential_files",
            ]
        else:
            recommendation["suggest_drop"] = []

        return recommendation

    def get_stats(self) -> dict[str, Any]:
        """Get aggregate context statistics."""
        base_stats = {
            "max_tokens": self.max_tokens,
            "used_tokens": self._total_tokens,
            "remaining_tokens": self.remaining_tokens,
            "usage_percent": round(self.usage_percent, 1),
            "total_messages": len(self._messages),
            "tool_messages": len(self._tool_message_indices),
            "needs_warning": self.needs_warning,
            "is_overflow": self.is_overflow,
        }

        # Add analytics if we have snapshots
        if self.snapshots:
            token_counts = [s.tokens_used for s in self.snapshots]
            base_stats.update({
                "snapshots": len(self.snapshots),
                "total_tokens_processed": self.total_tokens_processed,
                "total_compactions": self.total_compactions,
                "total_llm_calls": self.total_llm_calls,
                "total_tool_calls": self.total_tool_calls,
                "avg_tokens": sum(token_counts) // len(token_counts),
                "max_tokens_observed": max(token_counts),
                "min_tokens_observed": min(token_counts),
                "tokens_per_llm_call": (
                    self.total_tokens_processed // self.total_llm_calls
                    if self.total_llm_calls > 0 else 0
                ),
                "tokens_per_tool_call": (
                    self.total_tokens_processed // self.total_tool_calls
                    if self.total_tool_calls > 0 else 0
                ),
                "compactions_per_100_calls": (
                    self.total_compactions * 100 // (self.total_llm_calls + self.total_tool_calls)
                    if (self.total_llm_calls + self.total_tool_calls) > 0 else 0
                ),
                "phase_tokens": dict(self.phase_tokens),
                "phase_calls": dict(self.phase_calls),
            })
        else:
            base_stats.update({
                "snapshots": 0,
                "total_tokens_processed": self.total_tokens_processed,
                "total_compactions": self.total_compactions,
                "total_llm_calls": self.total_llm_calls,
                "total_tool_calls": self.total_tool_calls,
            })

        return base_stats

    def to_dict(self) -> dict:
        """Serialize for checkpoint."""
        return {
            "max_tokens": self.max_tokens,
            "reserved_tokens": self.reserved_tokens,
            "warning_threshold": self.warning_threshold,
            "compaction_threshold": self.compaction_threshold,
            "total_tokens_processed": self.total_tokens_processed,
            "total_compactions": self.total_compactions,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "phase_tokens": dict(self.phase_tokens),
            "phase_calls": dict(self.phase_calls),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ContextBudget:
        """Deserialize from checkpoint."""
        budget = cls(
            max_tokens=data.get("max_tokens", 32000),
            reserved_tokens=data.get("reserved_tokens", 2000),
            warning_threshold=data.get("warning_threshold", 0.80),
            compaction_threshold=data.get("compaction_threshold", 0.70),
            total_tokens_processed=data.get("total_tokens_processed", 0),
            total_compactions=data.get("total_compactions", 0),
            total_llm_calls=data.get("total_llm_calls", 0),
            total_tool_calls=data.get("total_tool_calls", 0),
        )
        budget.phase_tokens = data.get("phase_tokens", {})
        budget.phase_calls = data.get("phase_calls", {})
        return budget

    def _log_snapshot(self, snapshot: ContextSnapshot) -> None:
        """Log a snapshot to JSONL."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": snapshot.timestamp,
            "tokens": snapshot.tokens_used,
            "budget": snapshot.tokens_budget,
            "tool_calls": snapshot.tool_calls_in_context,
            "messages": snapshot.messages_in_context,
            "phase": snapshot.phase,
        }
        with open(CONTEXT_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _log_event(self, event: dict) -> None:
        """Log an event to JSONL."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONTEXT_LOG, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
