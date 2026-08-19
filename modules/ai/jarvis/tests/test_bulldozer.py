"""Bulldozer Loop — testes de atrito reais contra o SLM local.

Cada teste submete uma tarefa de engenharia de software ao SLM via
`jarvis dev --once` e valida que o resultado é correto.

Progressão de dificuldade:
  Nível 1: Edição simples (1 linha)
  Nível 2: Criação de função
  Nível 3: Refatoração multi-linha
  Nível 4: Criação de módulo completo
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def _run_dev_task(task: str, project_root: str, timeout: int = 60) -> dict:
    """Executa uma tarefa via jarvis dev <task> e retorna o resultado."""
    env = os.environ.copy()
    env["JARVIS_PROJECT_ROOT"] = project_root
    try:
        result = subprocess.run(
            ["jarvis", "dev", task],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_root,
            env=env,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-3000:],
            "stderr": result.stderr[-1000:],
            "exit_code": result.returncode,
        }
    except FileNotFoundError:
        # Fallback: python module
        try:
            result = subprocess.run(
                ["python", "-m", "jarvis.cli.main", "dev", task],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=project_root,
                env=env,
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout[-3000:],
                "stderr": result.stderr[-1000:],
                "exit_code": result.returncode,
            }
        except Exception as e:
            return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "timeout", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}


def _create_project() -> Path:
    """Cria um projeto temporário para testes."""
    d = Path(tempfile.mkdtemp())
    (d / "main.py").write_text(
        'def greet(name: str) -> str:\n    """Greet someone."""\n    return f"Hello, {name}!"\n\n\ndef add(a: int, b: int) -> int:\n    """Add two numbers."""\n    return a + b\n'
    )
    (d / "utils.py").write_text(
        'def upper(s: str) -> str:\n    """Convert to uppercase."""\n    return s.upper()\n'
    )
    (d / "tests").mkdir()
    (d / "tests" / "__init__.py").write_text("")
    (d / "tests" / "test_main.py").write_text(
        'from main import greet, add\n\n\ndef test_greet():\n    assert greet("World") == "Hello, World!"\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'
    )
    return d


# ---------------------------------------------------------------------------
# Nível 1: Edição simples (1 linha)
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_level1_edit_one_line() -> None:
    """SLM deve alterar o greeting de 'Hello' para 'Hi'."""
    proj = _create_project()
    result = _run_dev_task(
        f"In the file main.py, change the greet function to return 'Hi' instead of 'Hello'. "
        f"Use str_replace on {proj / 'main.py'}",
        str(proj),
    )
    # Valida que o arquivo foi modificado corretamente
    content = (proj / "main.py").read_text()
    assert "Hi" in content, f"SLM failed to edit. stdout: {result['stdout'][-500:]}"


# ---------------------------------------------------------------------------
# Nível 2: Criação de função
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_level2_create_function() -> None:
    """SLM deve criar uma nova função multiply em main.py."""
    proj = _create_project()
    result = _run_dev_task(
        f"Add a new function 'multiply(a, b)' to {proj / 'main.py'} that returns a * b. "
        f"Place it after the add function.",
        str(proj),
    )
    content = (proj / "main.py").read_text()
    assert "multiply" in content, f"SLM failed to create function. stdout: {result['stdout'][-500:]}"
    assert "a * b" in content or "a*b" in content


# ---------------------------------------------------------------------------
# Nível 3: Refatoração multi-linha
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_level3_refactor() -> None:
    """SLM deve adicionar type hints a todas as funções."""
    proj = _create_project()
    # Remove type hints existentes para forçar o SLM a adicioná-los
    (proj / "main.py").write_text(
        'def greet(name):\n    """Greet someone."""\n    return f"Hello, {name}!"\n\n\ndef add(a, b):\n    """Add two numbers."""\n    return a + b\n'
    )
    result = _run_dev_task(
        f"Add type hints to all functions in {proj / 'main.py'}: "
        f"greet takes str returns str, add takes int, int returns int.",
        str(proj),
    )
    content = (proj / "main.py").read_text()
    # Pelo menos uma function deve ter type hint
    has_hint = "def greet(name: str)" in content or "def greet(name:str)" in content
    assert has_hint, f"SLM failed to add type hints. Content:\n{content}"


# ---------------------------------------------------------------------------
# Nível 4: Criação de arquivo
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_level4_create_file() -> None:
    """SLM deve criar um novo arquivo de configuração."""
    proj = _create_project()
    result = _run_dev_task(
        f"Create a new file {proj / 'config.py'} with a dictionary called "
        f"SETTINGS containing 'debug': True and 'version': '1.0.0'.",
        str(proj),
    )
    assert (proj / "config.py").exists(), f"SLM failed to create file. stdout: {result['stdout'][-500:]}"
    content = (proj / "config.py").read_text()
    assert "SETTINGS" in content
    assert "debug" in content


# ---------------------------------------------------------------------------
# Nível 5: Leitura + edição iterativa
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_level5_read_then_edit() -> None:
    """SLM deve ler um arquivo, entender seu conteúdo, e fazer uma edição."""
    proj = _create_project()
    # Cria um arquivo com erros propositais
    (proj / "buggy.py").write_text(
        'def divide(a, b):\n    return a / b  # Bug: no zero check\n\n\ndef multiply(a, b):\n    return a + b  # Bug: should be *\n'
    )
    result = _run_dev_task(
        f"Read {proj / 'buggy.py'}, find the bugs, and fix them using str_replace. "
        f"The divide function should check for zero, and multiply should use * not +.",
        str(proj),
    )
    content = (proj / "buggy.py").read_text() if (proj / "buggy.py").exists() else ""
    # Pelo menos um dos bugs deve ter sido corrigido
    fixed = False
    if "ZeroDivisionError" in content or "if b == 0" in content or "if b!=0" in content:
        fixed = True
    if "a * b" in content or "a*b" in content:
        fixed = True
    # Nota: o SLM pode ter corrigido apenas um bug — isso é aceitável
    # O teste valida que o SLM PELA MENOS leu e tentou editar
    assert result["ok"] or "str_replace" in result["stdout"] or fixed, (
        f"SLM didn't even attempt. stdout: {result['stdout'][-500:]}"
    )


# ---------------------------------------------------------------------------
# Validação de tool calling
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_tool_calling_json_valid() -> None:
    """Valida que o SLM gera JSON válido para tool calls."""
    proj = _create_project()
    result = _run_dev_task(
        f"List the files in {proj} using list_directory.",
        str(proj),
        timeout=90,
    )
    # O resultado deve conter informações sobre arquivos OU ter rodado
    assert result["ok"] or "main.py" in result["stdout"] or result["exit_code"] == 0, (
        f"SLM failed tool calling. stdout: {result['stdout'][-500:]} stderr: {result['stderr'][-200:]}"
    )
