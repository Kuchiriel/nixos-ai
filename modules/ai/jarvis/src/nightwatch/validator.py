"""Validator — Validation pipeline for the Nightwatch harness.

Runs proportional checks based on what changed:
- Python: ast.parse, import check, targeted tests
- Nix: nix-instantiate, nix flake check
- Shell: bash -n
- JSON: parser
- Tests: discover and run relevant tests
"""

from __future__ import annotations
import shlex

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nightwatch.file_guard import detect_language, validate_file, ValidationResult
from nightwatch.paths import REPO_ROOT


@dataclass
class ValidationStep:
    """A single validation step."""
    name: str
    command: str | None = None
    passed: bool = False
    output: str = ""
    duration_ms: int = 0
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ValidationReport:
    """Full validation report."""
    steps: list[ValidationStep] = field(default_factory=list)
    passed: bool = True
    total_duration_ms: int = 0
    files_validated: list[str] = field(default_factory=list)
    
    @property
    def summary(self) -> str:
        passed = sum(1 for s in self.steps if s.passed)
        failed = sum(1 for s in self.steps if not s.passed and not s.skipped)
        skipped = sum(1 for s in self.steps if s.skipped)
        return f"{passed} passed, {failed} failed, {skipped} skipped"


def run_command(cmd: str, timeout: int = 60) -> tuple[bool, str, int]:
    """Run a command and return (success, output, duration_ms)."""
    start = time.time()
    try:
        result = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True,
            timeout=timeout, cwd=str(REPO_ROOT),
        )
        duration = int((time.time() - start) * 1000)
        output = result.stdout + result.stderr
        return result.returncode == 0, output[:5000], duration
    except subprocess.TimeoutExpired:
        duration = int((time.time() - start) * 1000)
        return False, f"Timeout after {timeout}s", duration
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        return False, str(e), duration


def discover_test_files() -> list[str]:
    """Discover test files in the project.

    modules/ai/jarvis/tests is nixos-ai's own layout, not a generic
    convention — for any other project (post use_project_root()) that
    path won't exist. Try common layouts in order; first match wins.
    """
    candidates = [
        REPO_ROOT / "modules/ai/jarvis/tests",  # nixos-ai
        REPO_ROOT / "tests",
        REPO_ROOT / "test",
    ]
    for test_dir in candidates:
        if test_dir.exists():
            return [str(f.relative_to(REPO_ROOT)) for f in test_dir.glob("test_*.py")]
    return []


def validate_changed_files(files: list[str]) -> ValidationReport:
    """Validate all changed files."""
    report = ValidationReport()
    
    for file_path in files:
        path = REPO_ROOT / file_path
        if not path.exists():
            continue
        
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        
        step = ValidationStep(name=f"validate:{file_path}")
        start = time.time()
        
        result = validate_file(path, content)
        step.duration_ms = int((time.time() - start) * 1000)
        step.passed = result.valid
        step.output = "; ".join(result.errors) if result.errors else "ok"
        
        report.steps.append(step)
        report.files_validated.append(file_path)
        
        if not result.valid:
            report.passed = False
    
    return report


def run_syntax_checks(files: list[str]) -> ValidationReport:
    """Run syntax checks on changed files."""
    report = ValidationReport()
    
    for file_path in files:
        path = REPO_ROOT / file_path
        if not path.exists():
            continue
        
        lang = detect_language(path)
        
        if lang == "python":
            step = ValidationStep(name=f"syntax:{file_path}", command="python3 -m py_compile")
            success, output, duration = run_command(f"python3 -m py_compile {path}")
            step.passed = success
            step.output = output[:1000]
            step.duration_ms = duration
            report.steps.append(step)
        
        elif lang == "nix":
            step = ValidationStep(name=f"syntax:{file_path}", command="nix-instantiate --parse")
            success, output, duration = run_command(f"nix-instantiate --parse {path} > /dev/null")
            step.passed = success
            step.output = output[:1000]
            step.duration_ms = duration
            report.steps.append(step)
        
        elif lang == "bash":
            step = ValidationStep(name=f"syntax:{file_path}", command="bash -n")
            success, output, duration = run_command(f"bash -n {path}")
            step.passed = success
            step.output = output[:1000]
            step.duration_ms = duration
            report.steps.append(step)
        
        elif lang == "json":
            step = ValidationStep(name=f"syntax:{file_path}", command="python3 -m json.tool")
            success, output, duration = run_command(f"python3 -m json.tool {path} > /dev/null")
            step.passed = success
            step.output = output[:1000]
            step.duration_ms = duration
            report.steps.append(step)
        
        else:
            step = ValidationStep(name=f"syntax:{file_path}", skipped=True, skip_reason=f"Unknown language: {lang}")
            report.steps.append(step)
        
        if not step.passed and not step.skipped:
            report.passed = False
    
    return report


def run_targeted_tests(files: list[str]) -> ValidationReport:
    """Run tests relevant to the changed files."""
    report = ValidationReport()
    
    # Determine which test files to run
    test_files = discover_test_files()
    if not test_files:
        # No discoverable test directory anywhere in the project — there
        # is no safety net for this change. ValidationReport.passed
        # defaults to True, which would make this a silent green light
        # for an autonomous commit with zero tests run. Fail closed
        # instead: a project with no tests needs a human to decide
        # whether autonomous commits are even appropriate here.
        step = ValidationStep(
            name="tests", skipped=True,
            skip_reason="No test directory found (tried modules/ai/jarvis/tests, tests/, test/) "
                        "— failing closed, not silently passing with zero coverage",
        )
        report.steps.append(step)
        report.passed = False
        return report
    
    # Map source files to test files
    relevant_tests = []
    for file_path in files:
        # Simple heuristic: module name matches test name
        module_name = Path(file_path).stem
        for test_file in test_files:
            test_name = Path(test_file).stem
            if module_name in test_name or test_name.replace("test_", "") in module_name:
                relevant_tests.append(test_file)
    
    # Se nenhum teste específico for encontrado, o arquivo mudado não tem
    # cobertura dedicada — não dá pra saber o blast radius, então roda a
    # suíte inteira em vez de cair para um arquivo arbitrário e não
    # relacionado (era assim antes: sempre test_agent.py, mesmo pra mudança
    # em módulo compartilhado sem teste homônimo — furo real de regressão).
    if not relevant_tests:
        # Same test_dir discover_test_files() already found — run the
        # whole suite from there instead of hardcoding nixos-ai's own
        # nested test path (that path doesn't exist in other projects).
        test_dir = next(
            (d for d in (REPO_ROOT / "modules/ai/jarvis/tests", REPO_ROOT / "tests", REPO_ROOT / "test")
             if d.exists()),
            None,
        )
        test_target = str(test_dir.relative_to(REPO_ROOT)) if test_dir else "."
        test_cmd = f"python3 -m pytest {test_target} -q --tb=short"
        step = ValidationStep(name="tests:full-suite-fallback", command=test_cmd)
        success, output, duration = run_command(test_cmd, timeout=600)
        step.passed = success
        step.output = output[-3000:]
        step.duration_ms = duration
        report.steps.append(step)
        report.passed = success
        return report

    # Run tests
    test_cmd = f"python3 -m pytest {' '.join(relevant_tests)} -x -q --tb=short"
    step = ValidationStep(name="tests", command=test_cmd)
    success, output, duration = run_command(test_cmd, timeout=120)
    step.passed = success
    step.output = output[:3000]
    step.duration_ms = duration
    report.steps.append(step)
    report.passed = success
    
    return report


def run_import_check(files: list[str]) -> ValidationReport:
    """Check that imports still work after changes."""
    report = ValidationReport()
    
    # Only check Python files
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        step = ValidationStep(name="imports", skipped=True, skip_reason="No Python files changed")
        report.steps.append(step)
        return report
    
    # Try to import each module
    for file_path in py_files:
        path = REPO_ROOT / file_path
        if not path.exists():
            continue
        
        # Convert file path to module path
        try:
            rel = path.relative_to(REPO_ROOT / "modules" / "ai" / "jarvis" / "src")
            module = "jarvis." + str(rel.with_suffix("")).replace("/", ".")
        except ValueError:
            continue
        
        step = ValidationStep(name=f"import:{module}")
        success, output, duration = run_command(
            f"python3 -c \"import {module}\"",
            timeout=10,
        )
        step.passed = success
        step.output = output[:500]
        step.duration_ms = duration
        report.steps.append(step)
        
        if not success:
            report.passed = False
    
    return report


def validate_change(
    files: list[str],
    run_tests: bool = True,
    run_imports: bool = True,
) -> ValidationReport:
    """Run full validation pipeline on changed files."""
    start = time.time()
    
    # 1. Structural validation
    structural = validate_changed_files(files)
    
    # 2. Syntax checks
    syntax = run_syntax_checks(files)
    
    # 3. Import checks
    imports = ValidationReport()
    if run_imports:
        imports = run_import_check(files)
    
    # 4. Targeted tests
    tests = ValidationReport()
    if run_tests:
        tests = run_targeted_tests(files)
    
    # Combine results
    combined = ValidationReport()
    combined.steps.extend(structural.steps)
    combined.steps.extend(syntax.steps)
    combined.steps.extend(imports.steps)
    combined.steps.extend(tests.steps)
    combined.files_validated = structural.files_validated
    combined.passed = all(r.passed for r in [structural, syntax, imports, tests])
    combined.total_duration_ms = int((time.time() - start) * 1000)
    
    return combined
