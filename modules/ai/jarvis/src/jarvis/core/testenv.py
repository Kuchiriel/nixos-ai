"""Dono único de "rodar os testes do projeto e ATRIBUIR o resultado".

(30/09) Este módulo existe para eliminar duplicação que custou uma noite
inteira. `nightwatch/validator.py` e `core/devtools.py` tinham cada um a
su própria `_python_with_pytest`, sua env de PYTHONPATH e seu veredito de
sucesso — e os bugs do verifier (5 no nightwatch) precisei corrigir **duas
vezes**, uma em cada lado. A segunda vez eu ainda esqueci.

Regra daqui pra frente: **conceito tem um dono só.** Quem precisar delega.

O que mora aqui:
  - `python_with_pytest()`  — interpretador que TEM pytest (o Nix escolhe)
  - `test_env()`           — PYTHONPATH com a FONTE na frente, não o store
  - `run_pytest()`         — a execução
  - `normalize_fail_ids()` — IDs de falha estáveis (sem isso o baseline não
                             casa e a atribuição não funciona na prática)
  - `TestRun.regressed`    — separa regressão NOVA de falha PRÉ-EXISTENTE

O bug 6 (o mais caro da noite) mora aqui como `regressed`, e os dois
harnesses consomem o mesmo campo. Não pode existir duas respostas para
"isso quebrou?".
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "TestRun",
    "python_with_pytest",
    "test_env",
    "jarvis_test_root",
    "run_argv",
    "pytest_argv",
    "parse_pytest_output",
    "normalize_fail_ids",
    "run_pytest",
]

# pytesti que o repositório garante: o caminho relativo ao jarvis test root.
JARVIS_TEST_SUBDIR = ("modules", "ai", "jarvis")
JARVIS_TESTS_REL = ("modules", "ai", "jarvis", "tests")


def _repo_root() -> Path:
    from jarvis.core.paths import find_repo_root
    return find_repo_root()


def jarvis_test_root(root: Path | None = None) -> Path:
    """Diretório a partir do qual os IDs de teste são normalizados."""
    return (root or _repo_root()).joinpath(*JARVIS_TEST_SUBDIR)


# ──────────────────────────────────────────────────────────────────────────
# Ambiente
# ──────────────────────────────────────────────────────────────────────────
def python_with_pytest() -> str:
    """O interpretador que TEM pytest — certificado, não presumido.

    Ordem: `JARVIS_TEST_PYTHON` (o Nix escolhe, via nightwatch-timer.nix /
    com o `pkgs.jarvis-test-env`) → `sys.executable` → `python3`/`python` do
    PATH. Cada candidato é testado com `import pytest` antes de aceito.

    Medido (30/09): o serviço não tem `python3` no PATH
    (`/run/current-system/sw/bin/python3` não existe) e o site-packages do
    jarvis só tinha `jarvis` + `nightwatch`. `python3 -m pytest` dava
    "No module named pytest" — contado como FALHA DA TASK.
    """
    cands = [os.environ.get("JARVIS_TEST_PYTHON") or "", sys.executable or ""]
    import shutil as _sh
    for name in ("python3", "python"):
        p = _sh.which(name)
        if p:
            cands.append(p)
    for c in cands:
        if not c:
            continue
        resolved = c if os.path.isfile(c) else _sh.which(c)
        if not resolved:
            continue
        try:
            r = subprocess.run([resolved, "-c", "import pytest"],
                               capture_output=True, timeout=20)
            if r.returncode == 0:
                return resolved
        except Exception:
            continue
    return sys.executable or "python3"


def test_env(root: Path | None = None) -> dict[str, str]:
    """PYTHONPATH com a FONTE na frente, não a cópia do /nix/store.

    Medido (30/09): sem isto, `import jarvis.core.agent` resolvia para
    `/nix/store/...-jarvis-0.1.0/...` — a cópia instalada, stale por
    definição, já que o patch foi aplicado na árvore de fontes. O agente
    validava uma coisa e alterava outra. As deps do store continuam
    disponíveis via o PYTHONPATH herdado.
    """
    env = dict(os.environ)
    src = (root or _repo_root()).joinpath(*JARVIS_TEST_SUBDIR, "src")
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{src}:{prev}" if prev else str(src)
    return env


# ──────────────────────────────────────────────────────────────────────────
# Execução
# ──────────────────────────────────────────────────────────────────────────
def run_argv(argv: list[str], cwd: Path | str | None = None,
             timeout: int = 120, env: dict[str, str] | None = None,
             ) -> tuple[int, str, int]:
    """Roda `argv` (LISTA, nunca string — shlex.split é armadilha) e devolve
    (returncode, stdout+stderr, duração_ms)."""
    import time as _t
    start = _t.time()
    try:
        r = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            cwd=str(cwd) if cwd else None, env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, f"Timeout after {timeout}s", int((_t.time() - start) * 1000)
    except (OSError, subprocess.SubprocessError) as e:
        return 125, f"Exec error: {e}", int((_t.time() - start) * 1000)
    return r.returncode, (r.stdout or "") + (r.stderr or ""), int((_t.time() - start) * 1000)


def pytest_argv(python: str, target: str, extra_args: str | list[str] = "",
                pattern: str = "") -> list[str]:
    """Monta o argv do pytest. `extra_args` em string é split por shlex
    (aceita o padrão histórico "-q --tb=short")."""
    argv = [python, "-m", "pytest", target]
    if isinstance(extra_args, str):
        import shlex
        argv += shlex.split(extra_args)
    else:
        argv += list(extra_args)
    if pattern:
        argv += ["-k", pattern]
    return argv


# ──────────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────────
def normalize_fail_ids(failing: list[str], test_root: Path | None = None) -> list[str]:
    """Normaliza IDs de teste para relativos ao test root.

    (30/09) Sem isto o bug 6 continua vivo NA PRÁTICA mesmo com o código
    certo: os IDs saíam como `../../../tmp/x.py::test_y` e o `baseline` que
    o agente montava não casava com nada, então tudo parecia regressão.
    ID estável é requisito, não estética.
    """
    root = test_root or jarvis_test_root()
    out: list[str] = []
    for tid in failing:
        if not tid:
            continue
        head, sep, tail = tid.partition("::")
        p = Path(head)
        if p.is_absolute():
            try:
                head = str(p.relative_to(root))
            except ValueError:
                head = p.name
        else:
            try:
                head = os.path.normpath(str((root / p).resolve().relative_to(root)))
            except Exception:
                head = p.name
        fixed = head + (sep + tail if sep else "")
        if fixed not in out:
            out.append(fixed)
    return out


def _count(output: str, word: str) -> int:
    for line in output.splitlines():
        if f" {word}" in line or line.strip().endswith(word):
            m = re.search(rf"(\d+)\s+{word}", line)
            if m:
                return int(m.group(1))
    return 0


def parse_pytest_output(output: str) -> dict[str, Any]:
    """Extrai passed/failed/IDs que falharam/traceback real."""
    failing: list[str] = []
    for line in output.splitlines():
        s = line.strip()
        if s.startswith("FAILED ") or s.startswith("ERROR "):
            tid = s.split(" ", 1)[1].split(" - ")[0].strip()
            if tid:
                failing.append(tid)
    # traceback de verdade: entre === FAILURES/ERRORS e === short test summary.
    # Antes, `errors` recebia a LINHA DE RESUMO — que não diz nada.
    errors: list[str] = []
    grab = False
    for line in output.splitlines():
        if "=== FAILURES" in line or "=== ERRORS" in line:
            grab = True
        elif "=== short test summary" in line:
            grab = False
        elif grab and line.strip():
            errors.append(line.rstrip()[:300])
    return {
        "passed": _count(output, "passed"),
        "failed": _count(output, "failed"),
        "failing": failing,
        "errors": errors,
    }


# ──────────────────────────────────────────────────────────────────────────
# Resultado
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class TestRun:
    """O resultado de uma execução — com ATRIBUIÇÃO, não só ok/fail."""
    ok: bool                       # suíte inteira passou
    passed: int = 0
    failed: int = 0
    failing: list[str] = field(default_factory=list)
    new_failures: list[str] = field(default_factory=list)
    regressed: bool | None = None  # None = não se sabe (sem baseline)
    errors: list[str] = field(default_factory=list)
    output: str = ""
    exit_code: int = 0
    python_used: str = ""
    argv: list[str] = field(default_factory=list)
    cwd: str = ""
    duration_ms: int = 0
    error: str | None = None
    baseline_given: bool = False
    note: str = ""

    # ── a pergunta que importa ──────────────────────────────────────────
    @property
    def passed_no_regression(self) -> bool:
        """A mudança NÃO introduziu nenhuma falha nova?

        Sem baseline isso é desconhecido — e a diferença entre "não sei" e
        "não" é exatamente o que fazia o harness acusar o agente por
        quebra antiga. Com baseline, é a resposta correta.
        """
        if not self.baseline_given:
            return self.ok
        return not self.new_failures

    def verdict_line(self) -> str:
        if self.error:
            return f"ERRO: {self.error}"
        if self.baseline_given:
            return (f"{self.passed} passed, {self.failed} failed | "
                    f"regressed={self.regressed} "
                    f"(novas={len(self.new_failures)}, "
                    f"pré-existentes={len(self.failing) - len(self.new_failures)})")
        return f"{self.passed} passed, {self.failed} failed (SEM baseline: não dá para dizer o que é regressão)"

    def to_dict(self, output_chars: int = 2000) -> dict[str, Any]:
        d: dict[str, Any] = {
            "ok": self.ok,
            "passed": self.passed,
            "failed": self.failed,
            "failing": self.failing,
            "errors": self.errors[-40:],
            "output": self.output[-output_chars:],
            "exit_code": self.exit_code,
            "python_used": self.python_used,
        }
        if self.error:
            d["error"] = self.error
        if self.baseline_given:
            d["new_failures"] = self.new_failures
            d["regressed"] = self.regressed
        d["passed_no_regression"] = self.passed_no_regression
        d["note"] = self.note
        return d


def run_pytest(test_path: str, pattern: str = "", timeout: int = 120,
               baseline: list[str] | None = None,
               extra_args: str | list[str] = "-q --tb=short -rf",
               root: Path | None = None, cwd: Path | str | None = None,
               test_root: Path | None = None) -> TestRun:
    """Roda a suíte e ATRIBUI o resultado (novo vs pré-existente).

    `baseline` = IDs que já falhavam ANTES da mudança. Sem ele, `ok` só
    significa "tudo passou" e `regressed` fica None (desconhecido) — nunca
    `False`, que seria mentira.
    """
    root = root or _repo_root()
    t_root = test_root or jarvis_test_root(root)
    py = python_with_pytest()
    argv = pytest_argv(py, test_path, extra_args, pattern)
    run_cwd = cwd if cwd is not None else t_root

    rc, output, ms = run_argv(argv, cwd=run_cwd, timeout=timeout, env=test_env(root))
    parsed = parse_pytest_output(output)
    failing = normalize_fail_ids(parsed["failing"], t_root)

    base = set(baseline or ())
    new_failures = [t for t in failing if t not in base]
    run = TestRun(
        ok=(rc == 0),
        passed=parsed["passed"],
        failed=parsed["failed"],
        failing=failing,
        new_failures=new_failures,
        regressed=(bool(new_failures) if base else None),
        errors=parsed["errors"],
        output=output,
        exit_code=rc,
        python_used=py,
        argv=argv,
        cwd=str(run_cwd),
        duration_ms=ms,
        baseline_given=bool(base),
    )

    if "No module named pytest" in output:
        run.ok = False
        run.error = (f"python_sem_pytest: o interpretador escolhido não tem "
                     f"pytest (tentado={py})")
    if run.error is None and rc in (124, 125) and not run.output:
        run.error = run.output or f"execução falhou (rc={rc})"

    if base:
        run.note = (
            f"baseline: {len(base)} teste(s) já falhavam. "
            f"regressed={run.regressed} (new_failures={len(new_failures)}). "
            + ("Sua mudança NÃO quebrou nada — as falhas em `failing` são "
               "pré-existentes." if not run.regressed else
               "Sua mudança QUEBROU os testes em `new_failures`.")
        )
    else:
        run.note = (
            "SEM baseline: `ok` significa 'a suíte inteira passa'. Passe "
            "baseline=[IDs que já falhavam] para distinguir regressão de "
            "falha pré-existente — sem isso você não sabe se a falha é sua."
        )
    return run
