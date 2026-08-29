"""ContextBudget — Tracks context usage and informs condensing policy.

Instead of arbitrary condensing frequencies, we measure:
- Context size at each turn
- Condensing events and their impact
- Information preserved vs lost
- Tokens per tool call
- Latency before/after condensing

This enables adaptive policies:
- Condense when context > 80% of budget
- Condense more aggressively after N failed tool calls
- Preserve high-value context (recent errors, active task state)
- Drop low-value context (old tool outputs, completed task history)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"
CONTEXT_LOG = STATE_DIR / "context_usage.jsonl"


@dataclass
class ContextSnapshot:
    """A single point-in-time measurement of context usage."""
    timestamp: float = field(default_factory=time.time)
    tokens_used: int = 0
    tokens_budget: int = 8192  # default, updated from config
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
    """Tracks context budget across a session."""
    
    budget: int = 8192
    compaction_threshold: float = 0.8  # compact at 80%
    max_tool_output_tokens: int = 2000
    max_file_content_tokens: int = 8000
    
    # Accumulated state
    snapshots: list[ContextSnapshot] = field(default_factory=list)
    total_tokens_processed: int = 0
    total_compactions: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    
    # Per-phase tracking
    phase_tokens: dict[str, int] = field(default_factory=dict)
    phase_calls: dict[str, int] = field(default_factory=dict)
    
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
            tokens_budget=self.budget,
            tool_calls_in_context=tool_calls,
            messages_in_context=messages,
            phase=phase,
        )
        self.snapshots.append(snapshot)
        self.total_tokens_processed += tokens_used
        
        if phase:
            self.phase_tokens[phase] = self.phase_tokens.get(phase, 0) + tokens_used
            self.phase_calls[phase] = self.phase_calls.get(phase, 0) + 1
        
        # Persist
        self._log_snapshot(snapshot)
        
        return snapshot
    
    def should_compact(self, current_tokens: int) -> bool:
        """Determine if compaction should happen."""
        if self.budget <= 0:
            return False
        return current_tokens >= self.budget * self.compaction_threshold
    
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
        usage_pct = current_tokens / self.budget if self.budget > 0 else 0
        
        recommendation = {
            "should_compact": self.should_compact(current_tokens),
            "usage_pct": usage_pct,
            "budget": self.budget,
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
        if not self.snapshots:
            return {"snapshots": 0}
        
        token_counts = [s.tokens_used for s in self.snapshots]
        return {
            "snapshots": len(self.snapshots),
            "total_tokens_processed": self.total_tokens_processed,
            "total_compactions": self.total_compactions,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "avg_tokens": sum(token_counts) // len(token_counts),
            "max_tokens": max(token_counts),
            "min_tokens": min(token_counts),
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
        }
    
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
    
    def to_dict(self) -> dict:
        """Serialize for checkpoint."""
        return {
            "budget": self.budget,
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
            budget=data.get("budget", 8192),
            total_tokens_processed=data.get("total_tokens_processed", 0),
            total_compactions=data.get("total_compactions", 0),
            total_llm_calls=data.get("total_llm_calls", 0),
            total_tool_calls=data.get("total_tool_calls", 0),
        )
        budget.phase_tokens = data.get("phase_tokens", {})
        budget.phase_calls = data.get("phase_calls", {})
        return budget
