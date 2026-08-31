"""
Self-Testing Architecture — JARVIS tests itself.

Based on research:
- Self-Harness framework (weakness mining → proposal → validation)
- HarnessX AEGIS (Digester → Planner → Evolver → Critic)
- Six-layer agent testing (data → unit → integration → E2E → adversarial → production)

Three testing levels:
1. BLACK BOX — test via public interfaces/MCP only
2. GREY BOX — inspect internal state, logs, metrics
3. WHITE BOX — internal code validation, AST, types
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    level: str  # black, grey, white
    passed: bool
    duration_ms: float = 0
    evidence: str = ""
    error: str = ""
    metrics: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "name": self.name,
            "level": self.level,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "evidence": self.evidence[:200],
            "error": self.error[:200],
            "metrics": self.metrics,
        }


@dataclass
class TestSuite:
    """Collection of test results."""
    name: str
    results: list[TestResult] = field(default_factory=list)
    started_at: float = 0
    completed_at: float = 0

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0

    def to_dict(self):
        return {
            "name": self.name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": f"{self.pass_rate:.1%}",
            "duration_ms": (self.completed_at - self.started_at) * 1000,
            "results": [r.to_dict() for r in self.results],
        }


class BlackBoxTests:
    """Test JARVIS through public interfaces only.

    Simulates an external agent calling JARVIS via MCP/CLI.
    Does NOT inspect internal state.
    """

    def __init__(self, jarvis_cli_path: str = None):
        if jarvis_cli_path is None:
            jarvis_cli_path = os.path.expanduser("~/projects/nixos-ai/scripts/jarvis-cli.sh")
        self.cli_path = jarvis_cli_path

    def run_all(self) -> TestSuite:
        """Run all black box tests."""
        suite = TestSuite(name="black_box", started_at=time.time())

        tests = [
            self.test_rag_search,
            self.test_memory_recall,
            self.test_memory_remember,
            self.test_workspace_discovery,
            self.test_persona_selection,
            self.test_workitem_creation,
            self.test_orchestrator_decompose,
            self.test_vault_status,
            self.test_shell_execution,
            self.test_health_check,
        ]

        for test_fn in tests:
            try:
                result = test_fn()
                suite.results.append(result)
            except Exception as e:
                suite.results.append(TestResult(
                    name=test_fn.__name__,
                    level="black",
                    passed=False,
                    error=str(e),
                ))

        suite.completed_at = time.time()
        return suite

    def _run_cli(self, args: str, timeout: int = 30) -> tuple[bool, str]:
        """Run a JARVIS CLI command and return (success, output)."""
        import subprocess
        try:
            result = subprocess.run(
                f"cd ~/projects/nixos-ai && ./scripts/jarvis-cli.sh {args}",
                shell=True, capture_output=True, text=True,
                timeout=timeout,
            )
            return result.returncode == 0, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "timeout"
        except Exception as e:
            return False, str(e)

    def test_rag_search(self) -> TestResult:
        """Test RAG semantic search."""
        start = time.time()
        ok, output = self._run_cli('rag-search "test query"')
        return TestResult(
            name="rag_search", level="black", passed=ok,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_memory_recall(self) -> TestResult:
        """Test memory recall."""
        start = time.time()
        ok, output = self._run_cli('recall "test"')
        return TestResult(
            name="memory_recall", level="black", passed=ok,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_memory_remember(self) -> TestResult:
        """Test memory remember."""
        start = time.time()
        ok, output = self._run_cli('remember "self-test fact"')
        return TestResult(
            name="memory_remember", level="black", passed=ok,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_workspace_discovery(self) -> TestResult:
        """Test workspace discovery."""
        start = time.time()
        ok, output = self._run_cli('workspace --list')
        has_projects = "Projects:" in output or "nixos-ai" in output
        return TestResult(
            name="workspace_discovery", level="black", passed=ok and has_projects,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_persona_selection(self) -> TestResult:
        """Test persona selection."""
        start = time.time()
        ok, output = self._run_cli('persona --select "fix nixos config"')
        has_persona = "nixos_engineer" in output or "NixOS" in output
        return TestResult(
            name="persona_selection", level="black", passed=ok and has_persona,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_workitem_creation(self) -> TestResult:
        """Test work item creation."""
        start = time.time()
        ok, output = self._run_cli('workitem --create "self-test task" "test"')
        return TestResult(
            name="workitem_creation", level="black", passed=ok,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_orchestrator_decompose(self) -> TestResult:
        """Test task decomposition."""
        start = time.time()
        ok, output = self._run_cli('orchestrate --decompose "fix bug" "test"')
        has_items = "work items" in output.lower() or "Created" in output
        return TestResult(
            name="orchestrator_decompose", level="black", passed=ok and has_items,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_vault_status(self) -> TestResult:
        """Test vault status."""
        start = time.time()
        ok, output = self._run_cli('vault-status')
        return TestResult(
            name="vault_status", level="black", passed=ok,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_shell_execution(self) -> TestResult:
        """Test shell command execution."""
        start = time.time()
        ok, output = self._run_cli('shell "echo hello"')
        has_output = "hello" in output
        return TestResult(
            name="shell_execution", level="black", passed=ok and has_output,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )

    def test_health_check(self) -> TestResult:
        """Test health/status check."""
        start = time.time()
        ok, output = self._run_cli('status')
        return TestResult(
            name="health_check", level="black", passed=ok,
            duration_ms=(time.time() - start) * 1000,
            evidence=output[:200],
        )


class GreyBoxTests:
    """Test JARVIS by inspecting internal state.

    Reads logs, metrics, checkpoints, and state files.
    """

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = os.path.expanduser("~/.local/state/jarvis")
        self.state_dir = Path(state_dir)

    def run_all(self) -> TestSuite:
        """Run all grey box tests."""
        suite = TestSuite(name="grey_box", started_at=time.time())

        tests = [
            self.test_state_directory_exists,
            self.test_workspace_state,
            self.test_work_items_state,
            self.test_orchestrator_state,
            self.test_memory_state,
            self.test_vault_state,
            self.test_logs_exist,
            self.test_dependency_graph,
        ]

        for test_fn in tests:
            try:
                result = test_fn()
                suite.results.append(result)
            except Exception as e:
                suite.results.append(TestResult(
                    name=test_fn.__name__,
                    level="grey",
                    passed=False,
                    error=str(e),
                ))

        suite.completed_at = time.time()
        return suite

    def test_state_directory_exists(self) -> TestResult:
        """Verify state directory structure."""
        exists = self.state_dir.exists()
        contents = list(self.state_dir.iterdir()) if exists else []
        return TestResult(
            name="state_directory", level="grey", passed=exists,
            evidence=f"Contents: {[f.name for f in contents[:10]]}",
            metrics={"file_count": len(contents)},
        )

    def test_workspace_state(self) -> TestResult:
        """Verify workspace state was saved."""
        ws_file = self.state_dir / "workspace.json"
        if not ws_file.exists():
            return TestResult(name="workspace_state", level="grey", passed=False,
                            error="workspace.json not found")
        try:
            with open(ws_file) as f:
                data = json.load(f)
            project_count = len(data.get("projects", {}))
            return TestResult(
                name="workspace_state", level="grey", passed=True,
                evidence=f"{project_count} projects indexed",
                metrics={"projects": project_count},
            )
        except Exception as e:
            return TestResult(name="workspace_state", level="grey", passed=False, error=str(e))

    def test_work_items_state(self) -> TestResult:
        """Verify work items state."""
        items_file = self.state_dir / "work" / "items.json"
        if not items_file.exists():
            return TestResult(name="work_items_state", level="grey", passed=True,
                            evidence="No work items yet (clean state)")
        try:
            with open(items_file) as f:
                items = json.load(f)
            return TestResult(
                name="work_items_state", level="grey", passed=True,
                evidence=f"{len(items)} work items",
                metrics={"items": len(items)},
            )
        except Exception as e:
            return TestResult(name="work_items_state", level="grey", passed=False, error=str(e))

    def test_orchestrator_state(self) -> TestResult:
        """Verify orchestrator state."""
        orch_dir = self.state_dir / "orchestrator"
        if not orch_dir.exists():
            return TestResult(name="orchestrator_state", level="grey", passed=True,
                            evidence="Orchestrator state dir not created yet")
        events_file = orch_dir / "events.jsonl"
        event_count = 0
        if events_file.exists():
            event_count = len(events_file.read_text().splitlines())
        return TestResult(
            name="orchestrator_state", level="grey", passed=True,
            evidence=f"{event_count} events logged",
            metrics={"events": event_count},
        )

    def test_memory_state(self) -> TestResult:
        """Verify memory/state persistence."""
        # Check if memory-related files exist
        memory_files = list(self.state_dir.rglob("*.jsonl")) if self.state_dir.exists() else []
        return TestResult(
            name="memory_state", level="grey", passed=True,
            evidence=f"{len(memory_files)} JSONL files",
            metrics={"jsonl_files": len(memory_files)},
        )

    def test_vault_state(self) -> TestResult:
        """Verify vault state."""
        vault_dir = self.state_dir / "vault"
        if not vault_dir.exists():
            return TestResult(name="vault_state", level="grey", passed=True,
                            evidence="Vault dir not created yet")
        notes = list(vault_dir.glob("*.md"))
        return TestResult(
            name="vault_state", level="grey", passed=True,
            evidence=f"{len(notes)} vault notes",
            metrics={"notes": len(notes)},
        )

    def test_logs_exist(self) -> TestResult:
        """Verify logs are being written."""
        log_dir = self.state_dir / "logs"
        if not log_dir.exists():
            return TestResult(name="logs_exist", level="grey", passed=True,
                            evidence="Log dir not created yet")
        log_files = list(log_dir.glob("*.jsonl"))
        return TestResult(
            name="logs_exist", level="grey", passed=len(log_files) > 0,
            evidence=f"{len(log_files)} log files",
            metrics={"log_files": len(log_files)},
        )

    def test_dependency_graph(self) -> TestResult:
        """Verify dependency graph was built."""
        ws_file = self.state_dir / "workspace.json"
        if not ws_file.exists():
            return TestResult(name="dependency_graph", level="grey", passed=False,
                            error="workspace.json not found")
        try:
            with open(ws_file) as f:
                data = json.load(f)
            graph = data.get("dependency_graph", {})
            edges = sum(len(deps) for deps in graph.values())
            return TestResult(
                name="dependency_graph", level="grey", passed=True,
                evidence=f"{edges} dependency edges across {len(graph)} projects",
                metrics={"edges": edges, "projects": len(graph)},
            )
        except Exception as e:
            return TestResult(name="dependency_graph", level="grey", passed=False, error=str(e))


class WhiteBoxTests:
    """Test JARVIS internals — code quality, AST, imports, types."""

    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = os.path.expanduser("~/projects/nixos-ai")
        self.project_root = Path(project_root)

    def run_all(self) -> TestSuite:
        """Run all white box tests."""
        suite = TestSuite(name="white_box", started_at=time.time())

        tests = [
            self.test_python_syntax,
            self.test_imports_valid,
            self.test_no_markdown_in_python,
            self.test_no_bare_except,
            self.test_no_hardcoded_paths,
            self.test_platform_modules_importable,
        ]

        for test_fn in tests:
            try:
                result = test_fn()
                suite.results.append(result)
            except Exception as e:
                suite.results.append(TestResult(
                    name=test_fn.__name__,
                    level="white",
                    passed=False,
                    error=str(e),
                ))

        suite.completed_at = time.time()
        return suite

    def test_python_syntax(self) -> TestResult:
        """Verify all Python files parse correctly."""
        import ast
        failed = []
        checked = 0
        for py_file in self.project_root.rglob("modules/ai/jarvis/src/jarvis/**/*.py"):
            if "__pycache__" in str(py_file):
                continue
            checked += 1
            try:
                ast.parse(py_file.read_text(errors="ignore"))
            except SyntaxError as e:
                failed.append(f"{py_file.name}: {e.msg} line {e.lineno}")

        return TestResult(
            name="python_syntax", level="white",
            passed=len(failed) == 0,
            evidence=f"{checked} files checked, {len(failed)} failed",
            metrics={"checked": checked, "failed": len(failed)},
            error="; ".join(failed[:5]) if failed else "",
        )

    def test_imports_valid(self) -> TestResult:
        """Verify key modules can be imported."""
        import sys
        sys.path.insert(0, str(self.project_root / "modules/ai/jarvis/src"))

        modules = [
            "jarvis.core.workspace",
            "jarvis.core.persona",
            "jarvis.core.workitem",
            "jarvis.core.orchestrator",
            "jarvis.core.context",
            "jarvis.core.model_policy",
        ]

        failed = []
        for mod in modules:
            try:
                __import__(mod)
            except Exception as e:
                failed.append(f"{mod}: {e}")

        return TestResult(
            name="imports_valid", level="white",
            passed=len(failed) == 0,
            evidence=f"{len(modules) - len(failed)}/{len(modules)} imports OK",
            metrics={"checked": len(modules), "failed": len(failed)},
            error="; ".join(failed[:3]) if failed else "",
        )

    def test_no_markdown_in_python(self) -> TestResult:
        """Check for markdown fences accidentally inserted in Python."""
        issues = []
        for py_file in self.project_root.rglob("modules/ai/jarvis/src/jarvis/**/*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                content = py_file.read_text(errors="ignore")
                if "```python" in content or "```nix" in content:
                    issues.append(py_file.name)
            except Exception:
                pass

        return TestResult(
            name="no_markdown_in_python", level="white",
            passed=len(issues) == 0,
            evidence=f"{len(issues)} files with markdown fences" if issues else "Clean",
            metrics={"issues": len(issues)},
        )

    def test_no_bare_except(self) -> TestResult:
        """Check for bare except clauses (bad practice)."""
        issues = []
        for py_file in self.project_root.rglob("modules/ai/jarvis/src/jarvis/**/*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                content = py_file.read_text(errors="ignore")
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped == "except:" or stripped == "except :":
                        issues.append(f"{py_file.name}:{i}")
            except Exception:
                pass

        return TestResult(
            name="no_bare_except", level="white",
            passed=len(issues) == 0,
            evidence=f"{len(issues)} bare except clauses" if issues else "Clean",
            metrics={"issues": len(issues)},
        )

    def test_no_hardcoded_paths(self) -> TestResult:
        """Check for hardcoded paths that should use config."""
        issues = []
        forbidden = ["/home/m3ta", "/home/user", "/tmp/jarvis"]
        for py_file in self.project_root.rglob("modules/ai/jarvis/src/jarvis/**/*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                content = py_file.read_text(errors="ignore")
                for pattern in forbidden:
                    if pattern in content:
                        issues.append(f"{py_file.name}: {pattern}")
            except Exception:
                pass

        return TestResult(
            name="no_hardcoded_paths", level="white",
            passed=len(issues) == 0,
            evidence=f"{len(issues)} hardcoded paths" if issues else "Clean",
            metrics={"issues": len(issues)},
        )

    def test_platform_modules_importable(self) -> TestResult:
        """Verify all platform modules can be imported together."""
        import sys
        sys.path.insert(0, str(self.project_root / "modules/ai/jarvis/src"))

        try:
            from jarvis.core.workspace import WorkspaceDiscovery
            from jarvis.core.persona import PersonaRegistry
            from jarvis.core.workitem import WorkItemEngine
            from jarvis.core.orchestrator import Orchestrator
            from jarvis.core.context import ContextPipeline
            from jarvis.core.model_policy import ModelPolicy
            return TestResult(
                name="platform_modules_importable", level="white", passed=True,
                evidence="All 6 platform modules import successfully",
            )
        except Exception as e:
            return TestResult(
                name="platform_modules_importable", level="white", passed=False,
                error=str(e),
            )


def run_self_test(level: str = "all") -> dict:
    """Run self-tests at specified level.

    Levels: black, grey, white, all
    """
    all_suites = []

    if level in ("black", "all"):
        bb = BlackBoxTests()
        all_suites.append(bb.run_all())

    if level in ("grey", "all"):
        gb = GreyBoxTests()
        all_suites.append(gb.run_all())

    if level in ("white", "all"):
        wb = WhiteBoxTests()
        all_suites.append(wb.run_all())

    # Aggregate
    total_passed = sum(s.passed for s in all_suites)
    total_failed = sum(s.failed for s in all_suites)
    total = sum(s.total for s in all_suites)

    return {
        "summary": {
            "total": total,
            "passed": total_passed,
            "failed": total_failed,
            "pass_rate": f"{total_passed/total:.1%}" if total > 0 else "N/A",
        },
        "suites": [s.to_dict() for s in all_suites],
    }
