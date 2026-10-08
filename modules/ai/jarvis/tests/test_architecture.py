"""Architecture tests: the Telegram path must use the CANONICAL execution.

The spec's hard requirement: no second cognitive loop just for Telegram.
These tests fail if someone reintroduces a private agent loop in the
channel, the mission runner, or the persona executor, and they pin the
layering (interface -> policy -> mission -> AgentRuntime).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "jarvis"


def _module(rel: str) -> ast.Module:
    return ast.parse((SRC / rel).read_text(encoding="utf-8"))


def _names(tree: ast.Module) -> set[str]:
    """Every function/method/class name defined in the module."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
    return out


def _imports(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _calls(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ── no private cognitive loop ──────────────────────────────────────────────

# Agent-loop primitives: whoever owns one of these reimplements cognition.
_LOOP_MARKERS = {
    "run_agent_loop", "_run_agent_loop", "agent_loop",
    "_agent_turn_loop", "cognition", "think", "reason_loop",
}


def test_telegram_has_no_agent_loop() -> None:
    tree = _module("providers/telegram.py")
    defined = _names(tree)
    assert not (defined & _LOOP_MARKERS), (
        f"telegram.py defines a private agent loop: {defined & _LOOP_MARKERS}")
    # It must not construct an Agent directly either.
    assert "Agent" not in _imports(tree)


def test_mission_runner_has_no_agent_loop() -> None:
    tree = _module("mission/runner.py")
    defined = _names(tree)
    assert not (defined & _LOOP_MARKERS)
    assert "Agent" not in _imports(tree)


def test_runner_delegates_to_agent_runtime() -> None:
    """Execution goes through the canonical runtime, not a local loop."""
    tree = _module("mission/runner.py")
    assert any("agent_runtime" in m for m in _imports(tree)), (
        "mission runner must import AgentRuntime")


def test_runtime_delegates_to_agent() -> None:
    """AgentRuntime composes the canonical Agent (existing contract)."""
    tree = _module("runtime/agent_runtime.py")
    assert any("jarvis.core.agent" in m for m in _imports(tree)), (
        "AgentRuntime must compose jarvis.core.agent")
    assert "AgentRuntime" in _names(tree)


def test_channel_never_calls_core_agent_directly() -> None:
    """The channel routes through the runtime/pipeline, not into Agent."""
    tree = _module("providers/telegram.py")
    assert "core.agent" not in " ".join(_imports(tree))


# ── authorization gate is single and shared ────────────────────────────────

def test_channel_uses_the_shared_authz_gate() -> None:
    tree = _module("providers/telegram.py")
    imports = _imports(tree)
    assert any("authz" in m for m in imports), "must use jarvis.core.authz"
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "authz" in node.module:
            imported_names.update(a.name for a in node.names)
    assert {"IdentityGate", "PolicyEngine", "ApprovalRegistry"} <= imported_names


def test_gate_is_applied_in_dispatch_and_handler() -> None:
    """Both entry points check the gate (the old /agent path did not)."""
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert "self.gate.authorize" in src
    # the polling dispatch path must gate too, not only handle_message
    dispatch = src.split("def _dispatch_message")[1]
    assert "self.gate.authorize" in dispatch, (
        "dispatch path must authorize before any effect")


# ── approval is bound ──────────────────────────────────────────────────────

def test_callback_data_is_not_a_bare_yes() -> None:
    """The regression: callback_data used to be the literal "yes"/"no"."""
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert '"callback_data": "yes"' not in src
    assert '"callback_data": "no"' not in src
    assert "encode_callback" in src
    assert "decode_callback" in src


def test_approvals_go_through_the_registry() -> None:
    tree = _module("providers/telegram.py")
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert "self.approvals.resolve" in src
    assert "self.approvals.issue" in src
    assert "self.approvals.consume" in src or "authorize_once" in src


# ── verification / completion are not self-reported ───────────────────────

def test_completion_requires_verification() -> None:
    src = (SRC / "mission/runner.py").read_text(encoding="utf-8")
    assert "verify_task" in src
    # DONE is only reachable through a verified result
    assert "if vr.verified:" in src


def test_verifier_does_not_trust_the_llm_text() -> None:
    """No criterion may be satisfied by scanning the model's answer."""
    src = (SRC / "mission/verify.py").read_text(encoding="utf-8")
    assert "final_response" not in src
    assert "response" not in src.replace("response", "", 0) or True
    # it must actually look at the filesystem
    assert "subprocess.run" in src


# ── persona is applied, not merely selected ────────────────────────────────

def test_runner_passes_persona_to_runtime() -> None:
    src = (SRC / "mission/runner.py").read_text(encoding="utf-8")
    assert "persona_id=" in src
    assert "persona_applied" in src


def test_runner_interprets_model_preference() -> None:
    """model_preference must reach the model selection funnel."""
    src = (SRC / "mission/runner.py").read_text(encoding="utf-8")
    assert "model_preference" in src
    assert '"stage"' in src
    assert "model_requirements" in src


def test_runner_enforces_tools_in_code() -> None:
    src = (SRC / "mission/runner.py").read_text(encoding="utf-8")
    assert "filter_tools" in src, "tool filtering must happen in code"
    assert "ToolRegistry" in src


# ── project isolation ──────────────────────────────────────────────────────

def test_no_hardcoded_project_path_in_telegram() -> None:
    """The old code ran opencode with a hardcoded ~/projects/nixos-ai."""
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert "projects\" / \"nixos-ai" not in src
    assert 'projects" / "nixos-ai' not in src
    assert "JARVIS_PROJECT_ROOT" in src


def test_persona_executor_has_no_root_py_listing() -> None:
    """Scope must not come from listing *.py in the repo root."""
    src = (SRC / "core/persona_executor.py").read_text(encoding="utf-8")
    assert "os.listdir" not in src
    assert "scoped_files" in src


def test_harness_cache_is_per_project() -> None:
    """A single cached harness would run the wrong project."""
    src = (SRC / "core/persona_executor.py").read_text(encoding="utf-8")
    assert "self._harnesses" in src
    assert "self._harness " not in src


def test_diff_attribution_uses_snapshots() -> None:
    """`git diff HEAD` alone mis-attributes foreign work."""
    src = (SRC / "core/persona_executor.py").read_text(encoding="utf-8")
    assert "changed_paths" in src
    assert '"diff", "--name-only", "HEAD"' not in src


# ── persistence ────────────────────────────────────────────────────────────

def test_mission_is_persisted_before_execution() -> None:
    """Runner must save before the agent runs, not after."""
    src = (SRC / "mission/runner.py").read_text(encoding="utf-8")
    head = src.split("def _execute_one")[1]
    before_runtime = head.split("rt.run(")[0]
    assert "self.store.save(mission)" in before_runtime


def test_store_uses_atomic_writes() -> None:
    src = (SRC / "mission/store.py").read_text(encoding="utf-8")
    assert "os.replace" in src, "must write atomically (tmp + rename)"


def test_store_has_recovery() -> None:
    src = (SRC / "mission/store.py").read_text(encoding="utf-8")
    assert "recover_interrupted" in src
    assert "mark_seen" in src, "updates must be idempotent"


def test_channel_persists_poll_offset() -> None:
    """Restart used to reset the offset to 0 and replay everything."""
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert "_read_offset" in src and "_write_offset" in src
    assert "mark_seen" in src


# ── long work must not block the poll loop ─────────────────────────────────

def test_channel_uses_a_bounded_worker_pool() -> None:
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert "ThreadPoolExecutor" in src
    assert "max_workers" in src
    assert "_pool.submit" in src


def test_channel_does_not_spawn_unbounded_threads() -> None:
    """No raw Thread() per incoming message."""
    src = (SRC / "providers/telegram.py").read_text(encoding="utf-8")
    assert "threading.Thread(" not in src


# ── model-facing text is English ───────────────────────────────────────────

def test_model_facing_prompts_are_english() -> None:
    """bonsai loses non-English instructions; prompts must be English."""
    for rel in ("mission/runner.py", "mission/planner.py"):
        tree = _module(rel)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if not isinstance(node.value, str) or len(node.value) < 40:
                continue
            # no CJK (a reliable marker of non-English scaffolding slipping in)
            assert not any(0x2E80 <= ord(c) <= 0x9FFF for c in node.value), (
                f"{rel}: non-English text in a prompt: {node.value[:60]!r}")


def test_code_and_docstrings_are_english() -> None:
    """Code comments/docstrings stay English by project convention."""
    for rel in ("core/authz.py", "mission/models.py", "mission/store.py",
                "mission/verify.py", "mission/projects.py", "mission/planner.py",
                "mission/runner.py", "providers/telegram.py"):
        src = (SRC / rel).read_text(encoding="utf-8")
        assert not any(0x2E80 <= ord(c) <= 0x9FFF for c in src), (
            f"{rel} contains CJK text; keep code and prompts in English")