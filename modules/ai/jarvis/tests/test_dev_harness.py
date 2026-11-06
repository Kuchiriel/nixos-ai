"""Regression tests for the `jarvis dev` harness (06/11).

Two failures found in the 06/11 audit:
  - harness nudges were appended as role=system mid-history; Qwen3.x's Jinja
    template aborts with 500 "System message must be at the beginning";
  - AGENTS.md/CLAUDE.md/GEMINI.md symlinks were loaded three times, and files
    larger than the per-file budget were skipped entirely (the closest rules
    never reached the model).
"""
from __future__ import annotations


def test_mid_conversation_system_becomes_user() -> None:
    from jarvis.cli.dev import _normalize_request_messages

    messages = [
        {"role": "system", "content": "base"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "ok"},
        {"role": "system", "content": "nudge"},
    ]
    out = _normalize_request_messages(messages)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"]
    assert out[0]["content"] == "base"
    assert out[-1]["content"] == "nudge"
    # The caller's history must not be mutated (it is persisted/checked later).
    assert messages[-1]["role"] == "system"

    # If history does not start with system, no system may survive anywhere:
    # the template only accepts system at index 0, not "the first system found".
    late = _normalize_request_messages([
        {"role": "user", "content": "hi"},
        {"role": "system", "content": "nudge"},
    ])
    assert [m["role"] for m in late] == ["user", "user"]


def test_agent_context_dedupes_symlinks_and_truncates(tmp_path) -> None:
    from jarvis.cli.dev import _load_agent_context

    big = "# Rules\n" + ("x" * 5000)
    (tmp_path / "AGENTS.md").write_text(big)
    (tmp_path / "CLAUDE.md").symlink_to(tmp_path / "AGENTS.md")
    (tmp_path / "GEMINI.md").symlink_to(tmp_path / "AGENTS.md")

    ctx = _load_agent_context(str(tmp_path))
    assert ctx.count("# From AGENTS.md") == 1
    assert "# From CLAUDE.md" not in ctx
    assert "# From GEMINI.md" not in ctx
    assert "[truncated]" in ctx
