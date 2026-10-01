"""Validator — Validation pipeline for the Nightwatch harness.

Runs proportional checks based on what changed:
- Python: ast.parse, import check, targeted tests
- Nix: nix-instantiate, nix flake check
- Shell: bash -n
- JSON: parser
- Tests: discover and run relevant tests
"""

from __future__ import annotations
import os
import shlex

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nightwatch.file_guard import detect_language, validate_file, ValidationResult
from jarvis.core.paths import find_repo_root


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
    # (30/09) Atribuição. `passed` sozinho não diz se a falha é nossa —
    # `regressed=False` com `passed=False` significa "a suíte tem lixo
    # antigo, mas minha mudança não quebrou nada", que é uma situação
    # diferente de "regressão".
    baseline: list[str] = field(default_factory=list)
    new_failures: list[str] = field(default_factory=list)
    regressed: bool | None = None


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


def run_command(cmd: str, timeout: int = 60, env: dict | None = None) -> tuple[bool, str, int]:
    """(30/09) DELEGA para `jarvis.core.testenv.run_argv`.

    Mantém a API por string (vários call sites já a usam), mas a execução
    em si é a do dono único. `shlex.split` numa string é armadilha — foi o
    que impediu `VAR=valor cmd` de funcionar e o que quase me fez escribir
    `run_command` duas vezes.
    """
    import shlex
    from jarvis.core.testenv import run_argv
    argv = shlex.split(cmd)
    rc, output, ms = run_argv(argv, cwd=find_repo_root(), timeout=timeout, env=env)
    return rc == 0, output, ms


def discover_test_files() -> list[str]:
    """Discover test files in the project.

    Checks the active project root, then common subdirectory layouts.
    (O fallback antigo para os testes do próprio nixos-ai foi removido:
    cada projeto valida com seus testes — ver comentário em run_tests_for.)
    """
    project_root = find_repo_root()

    # Check project root directly for test_*.py files (flat layout)
    flat_tests = list(project_root.glob("test_*.py"))
    if flat_tests:
        return [str(f) if f.is_absolute() else str(project_root / f) for f in flat_tests]

    # Check common subdirectory layouts
    candidates = [
        project_root / "tests",
        project_root / "test",
        # (30/09) Layout Nix do próprio nixos-ai: os testes NÃO ficam em
        # tests/ nem na raiz — ficam em modules/ai/jarvis/tests/. Sem esta
        # linha, discover_test_files() devolvia [] pra工作 no nixos-ai, e o
        # run_targeted_tests caía no fallback "roda a suíte inteira" — que
        # pegava falha PRÉ-EXISTENTE e reprovava o patch do modelo por
        # algo que ele não fez. Lição (1): verifier que não acha o
        # próprio teste é o instrumento mentindo, não o modelo errando.
        project_root / "modules" / "ai" / "jarvis" / "tests",
    ]
    for test_dir in candidates:
        if test_dir.exists():
            found = [str(f) for f in test_dir.glob("test_*.py")]
            if found:
                return found
    # (30/09) Varredura ampla como último recurso: qualquer test_*.py
    # sob o root (pega layouts aninhados/raros que os candidatos fixos
    # acima não cobrem). Barato (uns walked dozens de dirs) e só roda
    # quando nada mais achou — evita "verifier não achou teste" que
    # degrada pra suíte errada.
    wide = [str(f) for f in project_root.rglob("test_*.py")
            if "__pycache__" not in f.parts and "node_modules" not in f.parts]
    return wide


def _test_has_real_assertion(content: str) -> tuple[bool, str]:
    """(30/09) Um teste NOVO precisa provar que testa algo.

    Reward-hacking medido: o harness rodava o teste que o próprio modelo
    acabou de escrever, então um teste VACUO (`def test_x(): assert True`)
    passava e contava como "melhoria". Num harness que se auto-evolui isso
    é o pior tipo de falha: ele se premia com nada, para sempre.

    Regras (conservadoras — só reprova o óbvio, nunca o sutil):
      - needs at least one test function (def test_*)
      - needs a real assertion: assert X where X is not literally
        True/1/"" — i.e. something with a comparison or a call
    Anything subtler is pytest's job; here we only reject the obvious
    vacuous case.
    """
    import ast as _ast
    try:
        tree = _ast.parse(content)
    except SyntaxError:
        return True, ""  # sintaxe é tratada em outro lugar; não duplica
    test_funcs = [n for n in _ast.walk(tree)
                  if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                  and n.name.startswith("test")]
    if not test_funcs:
        return False, "novo arquivo de teste não define nenhuma função test_*"
    real_asserts = 0
    for fn in test_funcs:
        for node in _ast.walk(fn):
            if not isinstance(node, _ast.Assert):
                continue
            t = node.test
            # assert True / assert 1 / assert "x" (constante trivial) = vazio
            if isinstance(t, _ast.Constant):
                continue
            # assert not X / assert X.is_... / assert x == y => real
            real_asserts += 1
    if real_asserts == 0:
        return False, ("teste novo só tem assert de constante (assert True) — "
                       "não prova nada; reward-hacking, não melhoria")
    return True, ""


# (30/09) Dono único da política de teste: `jarvis.core.testenv`.
# Estas duas funções eram cópias literais das que estavam em
# `core/devtools.py` — e os 5 bugs do verifier (sem pytest, env do store,
# import duplicado, sem deps, sem baseline) precisei corrigir duas vezes,
# uma em cada lado. Agora os dois harnesses importam o mesmo módulo e o
# próximo bug é corrigido uma vez.
def _python_with_pytest() -> str:
    from jarvis.core.testenv import python_with_pytest
    return python_with_pytest()


def _test_env(root=None) -> dict:
    from jarvis.core.testenv import test_env
    return test_env(root)


def _test_command(target: str, extra: str = "") -> str:
    """Monta o comando de pytest com o interpretador que TEM pytest."""
    py = _python_with_pytest()
    return f"{py} -m pytest {target} {extra}".strip()


def validate_changed_files(files: list[str]) -> ValidationReport:
    """Validate all changed files."""
    report = ValidationReport()
    project_root = find_repo_root()

    for file_path in files:
        path = project_root / file_path
        if not path.exists():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        step = ValidationStep(name=f"validate:{file_path}")
        start = time.time()

        # (30/09) Guard de significado para teste NOVO/CRIADO: fecha o
        # reward-hacking de "teste vazio conta como melhoria". Só para
        # arquivo de teste que o agente acabou de criar.
        name = Path(file_path).name
        if name.startswith("test_") and name.endswith(".py"):
            ok, why = _test_has_real_assertion(content)
            if not ok:
                step.passed = False
                step.output = why
                report.steps.append(step)
                report.files_validated.append(file_path)
                report.passed = False
                continue

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
    project_root = find_repo_root()

    for file_path in files:
        path = project_root / file_path
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


def _run_and_attribute(target: str, extra: str, timeout: int,
                       baseline: list[str] | None,
                       step_name: str = "tests",
                       cwd: str | None = None) -> "ValidationStep":
    """Roda pytest via testenv e monta o ValidationStep com ATRIBUIÇÃO.

    (30/09) `-x` saiu de propósito: com -x o processo morre no primeiro
    erro e o resto da suíte (o baseline inteiro) fica desconhecido — sem
    baseline completo não dá para distinguir regressão de lixo antigo.
    """
    from jarvis.core import testenv
    run = testenv.run_pytest(target, timeout=timeout, baseline=baseline,
                             extra_args=extra, cwd=cwd or find_repo_root(),
                             test_root=testenv.jarvis_test_root())
    step = ValidationStep(name=step_name, command=" ".join(run.argv))
    step.passed = run.passed_no_regression
    step.output = (run.verdict_line() + "\n" + run.output)[-3000:]
    step.duration_ms = run.duration_ms
    step.baseline = list(baseline or ())
    step.new_failures = list(run.new_failures)
    step.regressed = run.regressed
    return step


def run_targeted_tests(files: list[str], baseline: list[str] | None = None) -> ValidationReport:
    """Run tests relevant to the changed files.

    (30/09) `baseline` = IDs que já falhavam ANTES do patch. Sem ele o
    veredito é `returncode == 0`, ou seja: qualquer teste já quebrado no
    repo reprova a task e o modelo é culpado por nada (o bug 6). Com ele,
    o veredito passa a ser "o patch introduziu alguma falha nova?" — que é
    a pergunta certa. A política mora em jarvis.core.testenv.
    """
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
        # No test maps to the changed file — run the test suite from
        # the project being worked on (not nixos-ai's own tests).
        project_root = find_repo_root()

        # Find the test directory in the target project
        #
        # (30/09) Bug real medido: a raiz tem um `tests/` VAZIO (sem
        # nenhum test_*.py). O `next(...)` pegava esse diretório vazio
        # PRIMEIRO, rodava `pytest tests/` → "no tests ran" →
        # passed=False. A task era reprovada por "não achou teste", e o
        # baseline nunca era populado (não havia linha FAILED). Os 112
        # testes reais em modules/ai/jarvis/tests/ nunca eram alcançados.
        # Só agoracorre o fallback Nix.
        def _has_tests(d):
            try:
                return d.is_dir() and any(d.glob("test_*.py"))
            except Exception:
                return False

        test_dir = next(
            (d for d in (project_root / "tests", project_root / "test",
                         project_root,)  # flat layout
             if _has_tests(d)),
            None,
        )
        # Fall back to nixos-ai layout only when working nixos-ai itself
        # (detectado pelo layout, não por comparação de identidade).
        if test_dir is None:
            own = project_root / "modules" / "ai" / "jarvis" / "tests"
            if own.exists():
                test_dir = own
            else:
                legacy = project_root / "tests"
                if legacy.exists():
                    test_dir = legacy
        # (30/09) BUG introduzido na consolidação: passava
        # `str(test_dir)`, que é "None" quando nenhum layout serve — o
        # pytest recebia literally "None" como path. O `test_target`
        # abaixo já resolvia isso (dir, ou "." na raiz). O gate do rebuild
        # pegou (o teste de fallback affirmations 'tests' in cmd).
        if test_dir:
            test_target = str(test_dir)
            run_cwd = str(project_root)
        else:
            test_target = "."
            run_cwd = str(project_root)
        run = _run_and_attribute(test_target, "-q --tb=short -rf", 600, baseline,
                                 step_name="tests:full-suite-fallback",
                                 cwd=run_cwd)
        report.steps.append(run)
        report.passed = run.passed
        return report

    # Run tests (atribuídos via testenv — dono único)
    step = _run_and_attribute(" ".join(relevant_tests), "-q --tb=short -rf", 120,
                              baseline, step_name="tests")
    report.steps.append(step)
    report.passed = step.passed
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
        path = find_repo_root() / file_path
        if not path.exists():
            continue

        # Convert file path to module path
        # (30/09) BUG: prefixava "jarvis." com rel JÁ vindo de dentro de
        # src/, que contém o pacote jarvis/ — então rel JA começa com
        # "jarvis" e o resultado era `jarvis.jarvis.control_plane.events`.
        # Ou seja, o check de import falhava em TODO arquivo do pacote, e
        # contava como falha da task (a Lição 1 de novo: verificador
        # mentindo). O nome do módulo é o próprio rel com "/"→".".
        try:
            rel = path.relative_to(find_repo_root() / "modules" / "ai" / "jarvis" / "src")
            module = str(rel.with_suffix("")).replace("/", ".")
        except ValueError:
            continue

        step = ValidationStep(name=f"import:{module}")
        # (30/09) `python3` bare NÃO EXISTE no PATH do unit (medido:
        # /run/current-system/sw/bin/python3 não existe). Usar o
        # interpretador do próprio processo — que tem o jarvis importável.
        success, output, duration = run_command(
            f'"{sys.executable}" -c "import {module}"',
            timeout=60, env=_test_env(),
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
    baseline: list[str] | None = None,
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
        tests = run_targeted_tests(files, baseline=baseline)
    
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
