"""P7 validation: context budget auto-detection, threshold consistency, compression.

Verifies:
- Auto-detect n_ctx from server (or use default)
- Threshold consistency between class and from_dict
- compress_history preserves high-signal content
- Token estimation accuracy
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.context_budget import ContextBudget, query_server_context_size


class TestP7ContextBudget:
    """Test context budget improvements."""

    def test_default_max_tokens(self):
        """Default max_tokens is 32000 when server unavailable."""
        with patch("jarvis.core.context_budget.query_server_context_size", return_value=0):
            budget = ContextBudget()
            assert budget.max_tokens == 32000

    def test_auto_detect_n_ctx(self):
        """Auto-detect n_ctx from server when available."""
        with patch("jarvis.core.context_budget.query_server_context_size", return_value=16384):
            budget = ContextBudget()
            assert budget.max_tokens == 16384
            assert budget._auto_detected is True

    def test_no_override_explicit_max_tokens(self):
        """Don't override explicitly set max_tokens."""
        with patch("jarvis.core.context_budget.query_server_context_size", return_value=16384):
            budget = ContextBudget(max_tokens=8192)
            assert budget.max_tokens == 8192
            assert budget._auto_detected is False

    def test_threshold_consistency(self):
        """Compaction threshold is consistent between class and from_dict."""
        # Class default
        budget1 = ContextBudget()
        assert budget1.compaction_threshold == 0.85

        # from_dict with missing key
        budget2 = ContextBudget.from_dict({})
        assert budget2.compaction_threshold == 0.85

        # from_dict with explicit value
        budget3 = ContextBudget.from_dict({"compaction_threshold": 0.90})
        assert budget3.compaction_threshold == 0.90

    def test_compress_preserves_errors(self):
        """Compression preserves error messages."""
        budget = ContextBudget(max_tokens=32000)
        
        # Add system message first
        budget.add_message({"role": "system", "content": "You are helpful."})
        
        # Add a long tool output with errors
        long_content = "line1\n" * 100 + "Error: import failed\n" + "line3\n" * 100
        budget.add_message({"role": "tool", "content": long_content, "name": "execute_shell"})
        
        # Add more messages to trigger compression
        for i in range(10):
            budget.add_message({"role": "assistant", "content": f"Step {i}: " + "x" * 300})
        
        # Compress
        saved = budget.compress_history(keep_last=3)
        
        # Verify error is preserved in compressed content
        tool_msg = budget._messages[1]  # The tool message (index 1)
        assert "Error: import failed" in tool_msg["content"]

    def test_compress_preserves_code_blocks(self):
        """Compression preserves code blocks in assistant messages."""
        budget = ContextBudget(max_tokens=32000)
        
        # Add system-like message first
        budget.add_message({"role": "system", "content": "You are helpful."})
        
        code_content = "Here's the fix:\n```python\ndef fix():\n    pass\n```\nDone."
        budget.add_message({"role": "assistant", "content": code_content})
        
        # Add more messages
        for i in range(10):
            budget.add_message({"role": "user", "content": f"Continue {i}: " + "y" * 300})
        
        # Compress
        budget.compress_history(keep_last=3)
        
        # Verify code is preserved in assistant message (index 1)
        assistant_msg = budget._messages[1]
        assert "def fix():" in assistant_msg["content"]

    def test_token_estimation(self):
        """Token estimation is roughly 4 chars per token."""
        budget = ContextBudget()
        assert budget.estimate_tokens("a" * 4) == 1
        assert budget.estimate_tokens("a" * 8) == 2
        assert budget.estimate_tokens("") == 1  # minimum 1

    def test_usage_percent(self):
        """Usage percent calculation is correct."""
        budget = ContextBudget(max_tokens=10000, reserved_tokens=2000)
        assert budget.available_tokens == 8000
        
        # Add some content
        budget._total_tokens = 4000
        assert budget.usage_percent == 50.0
        
        budget._total_tokens = 8000
        assert budget.usage_percent == 100.0

    def test_compaction_threshold_check(self):
        """should_compact respects threshold."""
        budget = ContextBudget(max_tokens=10000, compaction_threshold=0.85)
        
        assert not budget.should_compact(8000)  # 80% < 85%
        assert budget.should_compact(8500)  # 85% >= 85%
        assert budget.should_compact(9000)  # 90% >= 85%

    def test_recommendation_urgency(self):
        """Recommendation urgency levels are correct."""
        budget = ContextBudget(max_tokens=10000)
        
        rec = budget.get_recommendation(5000)  # 50%
        assert rec["urgency"] == "low"
        
        rec = budget.get_recommendation(7000)  # 70%
        assert rec["urgency"] == "medium"
        
        rec = budget.get_recommendation(8500)  # 85%
        assert rec["urgency"] == "high"
        
        rec = budget.get_recommendation(9500)  # 95%
        assert rec["urgency"] == "critical"
