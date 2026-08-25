"""Testes das ferramentas de desenvolvimento (core/devtools.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core.devtools import (
    DEV_TOOLS,
    code_search,
    handle_dev_tool,
    list_directory,
    read_file,
    run_tests,
    str_replace,
    write_file,
)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


def _tmp() -> Path:
    """Diretório temporário em /tmp (permitido pelo _safe_path)."""
    import tempfile
    return Path(tempfile.mkdtemp())


def test_read_file_basic() -> None:
    d = _tmp()
    f = d / "test.py"
    f.write_text("line1\nline2\nline3\n")
    result = read_file(str(f))
    assert result["ok"] is True
    assert "line1" in result["content"]
    assert result["total_lines"] == 3


def test_read_file_offset_limit() -> None:
    d = _tmp()
    f = d / "test.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    result = read_file(str(f), offset=1, limit=2)
    assert result["ok"] is True
    assert "line2" in result["content"]
    assert "line3" in result["content"]
    assert "line1" not in result["content"]


def test_read_file_not_found() -> None:
    d = _tmp()
    result = read_file(str(d / "nonexistent.py"))
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_read_file_directory() -> None:
    d = _tmp()
    result = read_file(str(d))
    assert result["ok"] is False
    assert "not a file" in result["error"].lower()


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


def test_write_file_create() -> None:
    d = _tmp()
    f = d / "new.py"
    result = write_file(str(f), "print('hello')\n")
    assert result["ok"] is True
    assert f.read_text() == "print('hello')\n"
    assert result["bytes"] > 0


def test_write_file_overwrite_with_backup() -> None:
    d = _tmp()
    f = d / "existing.py"
    f.write_text("old content")
    result = write_file(str(f), "new content")
    assert result["ok"] is True
    assert f.read_text() == "new content"
    bak = f.with_suffix(".py.bak")
    assert bak.exists()
    assert bak.read_text() == "old content"


def test_write_file_creates_dirs() -> None:
    d = _tmp()
    f = d / "sub" / "dir" / "file.py"
    result = write_file(str(f), "nested")
    assert result["ok"] is True
    assert f.read_text() == "nested"


# ---------------------------------------------------------------------------
# str_replace
# ---------------------------------------------------------------------------


def test_str_replace_basic() -> None:
    d = _tmp()
    f = d / "test.py"
    f.write_text("hello world")
    result = str_replace(str(f), "hello", "bye")
    assert result["ok"] is True
    assert result["replacements"] == 1
    assert f.read_text() == "bye world"


def test_str_replace_not_found() -> None:
    d = _tmp()
    f = d / "test.py"
    f.write_text("hello world")
    result = str_replace(str(f), "xyz", "abc")
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_str_replace_multiple_rejected() -> None:
    d = _tmp()
    f = d / "test.py"
    f.write_text("a b a b a")
    result = str_replace(str(f), "a", "x")
    assert result["ok"] is False
    assert "3 times" in result["error"]


def test_str_replace_multiple_allowed() -> None:
    d = _tmp()
    f = d / "test.py"
    f.write_text("a b a b a")
    result = str_replace(str(f), "a", "x", allow_multiple=True)
    assert result["ok"] is True
    assert result["replacements"] == 3
    assert f.read_text() == "x b x b x"


def test_str_replace_preserves_rest() -> None:
    d = _tmp()
    f = d / "test.py"
    original = "line1\nline2\nline3\n"
    f.write_text(original)
    str_replace(str(f), "line2", "LINE2")
    assert f.read_text() == "line1\nLINE2\nline3\n"


def test_str_replace_file_not_found() -> None:
    d = _tmp()
    result = str_replace(str(d / "nope.py"), "a", "b")
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# str_replace — fuzzy matching (SLM whitespace/indent errors)
# ---------------------------------------------------------------------------


def test_str_replace_fuzzy_normalized_whitespace() -> None:
    """SLM envia whitespace diferente — match normalizado ou fuzzy deve funcionar."""
    d = _tmp()
    f = d / "test.py"
    f.write_text("def hello(   ):\n    return True\n")
    # SLM normalizou os espaços extras
    result = str_replace(str(f), "def hello():\n    return True", "def hello():\n    return False")
    assert result["ok"] is True
    assert result["strategy"] in ("normalized", "fuzzy (95%)")
    assert "return False" in f.read_text()


def test_str_replace_fuzzy_indentation() -> None:
    """SLM erra indentação (tabs vs spaces)."""
    d = _tmp()
    f = d / "test.py"
    f.write_text("if True:\n    x = 1\n    y = 2\n")
    # SLM usou 2 espaços em vez de 4
    result = str_replace(str(f), "if True:\n  x = 1\n  y = 2", "if True:\n    x = 1\n    y = 2\n    z = 3")
    assert result["ok"] is True
    # Pode ser normalized, fuzzy, ou line-match dependendo da similaridade
    assert result["strategy"] != "none"
    assert "z = 3" in f.read_text()


def test_str_replace_fuzzy_mixed_whitespace() -> None:
    """SLM mistura tabs e spaces."""
    d = _tmp()
    f = d / "test.py"
    f.write_text("class Foo:\n    def bar(self):\n        pass\n")
    # SLM usou tab em vez de spaces
    result = str_replace(str(f), "class Foo:\n\tdef bar(self):\n\t\tpass", "class Foo:\n    def bar(self):\n        return 42")
    assert result["ok"] is True
    assert result["strategy"] != "none"
    assert "return 42" in f.read_text()


def test_str_replace_fuzzy_preserves_exact_content() -> None:
    """Fuzzy match deve usar o texto EXATO do arquivo, não o input normalizado."""
    d = _tmp()
    f = d / "test.py"
    original = "x =   1  # lots of spaces\n"
    f.write_text(original)
    # Input normalizado (espaços colapsados)
    result = str_replace(str(f), "x = 1 # lots of spaces", "x = 2")
    assert result["ok"] is True
    # Conteúdo original preservado exceto a substituição
    content = f.read_text()
    assert "x = 2" in content


def test_str_replace_fuzzy_line_match() -> None:
    """Match por linha única quando bloco multi-linha falha."""
    d = _tmp()
    f = d / "test.py"
    f.write_text("# TODO: fix this\nimport os\nimport sys\n")
    result = str_replace(str(f), "# TODO: fix this", "# DONE: fixed")
    assert result["ok"] is True
    assert "# DONE: fixed" in f.read_text()


def test_str_replace_fuzzy_strategy_reported() -> None:
    """Estratégia usada deve ser reportada no resultado."""
    d = _tmp()
    f = d / "test.py"
    f.write_text("hello   world\n")
    result = str_replace(str(f), "hello world", "hi world")
    assert result["ok"] is True
    assert result["strategy"] in ("exact", "normalized", "line-match")


def test_str_replace_truly_not_found_returns_context() -> None:
    """Quando nada funciona, retorna contexto para debug."""
    d = _tmp()
    f = d / "test.py"
    f.write_text("alpha\nbeta\ngamma\n")
    result = str_replace(str(f), "ZZZZZ_NOT_HERE", "new")
    assert result["ok"] is False
    assert "hint" in result
    assert len(result["hint"]) > 0


# ---------------------------------------------------------------------------
# list_directory
# ---------------------------------------------------------------------------


def test_list_directory_basic() -> None:
    d = _tmp()
    (d / "a.py").write_text("")
    (d / "b.py").write_text("")
    (d / "sub").mkdir()
    result = list_directory(str(d))
    assert result["ok"] is True
    names = [e["name"] for e in result["entries"]]
    assert "a.py" in names
    assert "b.py" in names
    assert "sub" in names


def test_list_directory_max_depth() -> None:
    d = _tmp()
    (d / "a").mkdir()
    (d / "a" / "b").mkdir()
    (d / "a" / "b" / "c").mkdir()
    (d / "a" / "b" / "c" / "deep.py").write_text("")
    (d / "top.py").write_text("")
    result = list_directory(str(d), max_depth=1)
    assert result["ok"] is True
    names = [e["name"] for e in result["entries"]]
    assert "a" in names
    assert "top.py" in names
    # depth 1: a/ está listado, mas a/b/c/ não
    assert "a/b/c" not in " ".join(names)


def test_list_directory_ignores() -> None:
    d = _tmp()
    (d / ".git").mkdir()
    (d / "__pycache__").mkdir()
    (d / "real.py").write_text("")
    result = list_directory(str(d))
    names = [e["name"] for e in result["entries"]]
    assert ".git" not in names
    assert "__pycache__" not in names
    assert "real.py" in names


def test_list_directory_not_found() -> None:
    d = _tmp()
    result = list_directory(str(d / "nope"))
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# code_search
# ---------------------------------------------------------------------------


def test_code_search_basic() -> None:
    d = _tmp()
    (d / "test.py").write_text("def hello():\n    pass\ndef world():\n    pass\n")
    result = code_search("def hello", str(d))
    assert result["ok"] is True
    assert result["total"] >= 1
    assert any("hello" in r["text"] for r in result["results"])


def test_code_search_no_results() -> None:
    d = _tmp()
    (d / "test.py").write_text("hello world")
    result = code_search("xyz_nonexistent", str(d))
    assert result["ok"] is True
    assert result["total"] == 0


def test_code_search_max_results() -> None:
    d = _tmp()
    content = "\n".join([f"def func{i}(): pass" for i in range(20)])
    (d / "big.py").write_text(content)
    result = code_search("def func", str(d), max_results=5)
    assert result["ok"] is True
    assert len(result["results"]) <= 5


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------


def test_run_tests_basic() -> None:
    """Executa um teste simples (pode demorar)."""
    result = run_tests(test_path="tests/test_intents.py", timeout=30)
    # Pode passar ou falhar — o importante é não crashar
    assert "ok" in result
    assert isinstance(result.get("passed", 0), int)


# ---------------------------------------------------------------------------
# handle_dev_tool
# ---------------------------------------------------------------------------


def test_handle_dev_tool_read_file(tmp_path: Path) -> None:
    import jarvis.core.devtools as mod
    original = mod._project_root
    mod._project_root = lambda: tmp_path
    try:
        (tmp_path / "test.py").write_text("hello")
        result = handle_dev_tool("read_file", {"path": "test.py"})
        parsed = json.loads(result)
        assert parsed["ok"] is True
    finally:
        mod._project_root = original


def test_handle_dev_tool_unknown() -> None:
    result = handle_dev_tool("nonexistent_tool", {})
    assert "error" in result.lower()


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def test_dev_tools_schema() -> None:
    """Todas as dev tools têm schema válido."""
    names = [t["function"]["name"] for t in DEV_TOOLS]
    assert "read_file" in names
    assert "write_file" in names
    assert "str_replace" in names
    assert "list_directory" in names
    assert "code_search" in names
    assert "run_tests" in names
    assert len(DEV_TOOLS) == 9  # read, write, str_replace, list, code_search, run_tests, run_linter, semantic, jarvis_command (execute_shell is in agent.py TOOLS)


def test_dev_tools_have_required_params() -> None:
    """Cada tool tem required params definidos."""
    for tool in DEV_TOOLS:
        params = tool["function"]["parameters"]
        assert "properties" in params
        assert "required" in params


def test_jarvis_command_tool_exists() -> None:
    """jarvis_command está no DEV_TOOLS."""
    names = [t["function"]["name"] for t in DEV_TOOLS]
    assert "jarvis_command" in names
    tc = [t for t in DEV_TOOLS if t["function"]["name"] == "jarvis_command"][0]
    props = tc["function"]["parameters"]["properties"]
    assert "subcommand" in props
    assert "args" in props


def test_jarvis_command_handler() -> None:
    """jarvis_command retorna dict com ok/output/error."""
    from jarvis.core.devtools import jarvis_command
    result = jarvis_command("status")
    assert isinstance(result, dict)
    assert "ok" in result
    # No sandbox pode falhar (jarvis não instalado), mas retorna dict válido
    if result["ok"]:
        import json
        data = json.loads(result["output"])
        assert isinstance(data, dict)
    else:
        assert "error" in result or "output" in result


def test_semantic_search_tool_exists() -> None:
    """semantic_search está no DEV_TOOLS."""
    names = [t["function"]["name"] for t in DEV_TOOLS]
    assert "semantic_search" in names
