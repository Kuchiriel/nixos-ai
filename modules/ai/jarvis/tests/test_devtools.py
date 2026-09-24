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
    # Backup centralizado (SafeEditor), não mais .bak ao lado do arquivo
    assert result["backup"] is not None
    assert Path(result["backup"]).read_text() == "old content"


def test_write_file_creates_dirs() -> None:
    d = _tmp()
    f = d / "sub" / "dir" / "file.py"
    result = write_file(str(f), "nested")
    assert result["ok"] is True
    assert f.read_text() == "nested"


def test_write_file_normalizes_space_join_bug() -> None:
    """Path com espaço adjacente a '/' (join bug L8: 'dir/ file') é
    NORMALIZADO p/ o path pretendido (fuzzy OpenDev) — rejeitar travava
    em STUCK pois o modelo nunca se autocorrige."""
    d = _tmp()
    result = write_file(str(d) + "/ script.sh", "echo")
    assert result["ok"] is True
    assert (d / "script.sh").read_text() == "echo"
    assert not (d / " script.sh").exists()


def test_write_file_allows_space_inside_name() -> None:
    """Espaço DENTRO do nome ('My Docs/x') continua válido."""
    d = _tmp()
    f = d / "My Docs" / "x.txt"
    result = write_file(str(f), "v")
    assert result["ok"] is True


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


def test_handle_dev_tool_read_file(tmp_path: Path, monkeypatch) -> None:
    import jarvis.core.devtools as mod
    original = mod._project_root
    mod._project_root = lambda: tmp_path
    # Hermético: CWD == raiz mockada (resolve_base faz walk-up do CWD;
    # fora de repo — ex.: sandbox nix sem .git — voltava CWD e o teste
    # falhava sem relação com o código. Gate de rebuild 18/09).
    monkeypatch.chdir(tmp_path)
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


def test_sanitize_secrets_deterministic(tmp_path) -> None:
    """sanitize_secrets: troca valores por placeholders, só tipos no report."""
    from jarvis.core.devtools import sanitize_secrets
    (tmp_path / "a.py").write_text(
        'k = "AKIA1234567890123456"; t = "hf_abcdefghijklmnopqrstuvwxyz123456"\n')
    (tmp_path / "b.txt").write_text("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789 ok\n")
    r = sanitize_secrets(str(tmp_path))
    assert r["changed"] == 2
    txt = (tmp_path / "a.py").read_text()
    assert "AKIA1234567890123456" not in txt
    assert "<your-aws-access-key-id>" in txt
    assert "AKIA1234567890123456" not in str(r)  # nunca vaza valor
    assert (tmp_path / "b.txt").read_text() == "<your-github-token> ok\n"


def test_build_json_dataset(tmp_path, monkeypatch) -> None:
    """build_json_dataset: lê CSVs, junta por FK, gera JSON + stats."""
    from jarvis.core.devtools import build_json_dataset
    (tmp_path / "departments.csv").write_text("id,name,budget\nD1,Eng,100\nD2,Sales,60\n")
    (tmp_path / "employees.csv").write_text(
        "id,name,position,skills,years_of_service,department_id\n"
        "E1,A,Mgr,Python;SQL,5,D1\nE2,B,Dev,Python,3,D1\nE3,C,Dev,SQL,2,D2\n")
    (tmp_path / "projects.csv").write_text(
        "name,status,member_ids,deadline,department_id\n"
        "P1,In Progress,E1;E2,2025-01-01,D1\nP2,Planning,E3,2025-02-01,D2\n")
    (tmp_path / "schema.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    r = build_json_dataset(schema="schema.json", out="organization.json")
    assert r["ok"] is True
    assert r["departments"] == 2
    assert r["employees"] == 3
    d = json.loads((tmp_path / "organization.json").read_text())
    assert d["statistics"]["averageDepartmentBudget"] == 80.0
    assert d["statistics"]["totalEmployees"] == 3
    assert d["statistics"]["skillDistribution"] == {"Python": 2, "SQL": 2}
    # integrity: project members estão nos employees do dept
    for dept in d["organization"]["departments"]:
        eids = {e["id"] for e in dept["employees"]}
        for proj in dept["projects"]:
            assert set(proj["members"]) <= eids


def test_sanitize_secrets_dry_run(tmp_path) -> None:
    from jarvis.core.devtools import sanitize_secrets
    (tmp_path / "a.py").write_text("k = \"AKIA1234567890123456\"\n")
    r = sanitize_secrets(str(tmp_path), dry_run=True)
    assert r["changed"] == 1
    assert "AKIA1234567890123456" in (tmp_path / "a.py").read_text()  # intacto


def test_dev_tools_schema() -> None:
    """Todas as dev tools têm schema válido."""
    names = [t["function"]["name"] for t in DEV_TOOLS]
    assert "read_file" in names
    assert "write_file" in names
    assert "str_replace" in names
    assert "list_directory" in names
    assert "code_search" in names
    assert "run_tests" in names
    assert "sanitize_secrets" in names
    assert "build_json_dataset" in names
    assert len(DEV_TOOLS) == 12  # +load_skill (skills on-demand) às 11 acima (execute_shell is in agent.py TOOLS)


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


def test_write_file_recusa_diretorio(tmp_path, monkeypatch) -> None:
    """write_file em path de diretório: erro honesto + hint (F2)."""
    from jarvis.core import devtools as D
    from jarvis.core.paths import use_project_root
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "pasta"
    d.mkdir()
    with use_project_root(tmp_path):
        res = D.write_file(str(d), "x")
    assert res["ok"] is False
    assert "diretório" in res["error"]
    assert "hint" in res


def test_write_file_cria_pais(tmp_path, monkeypatch) -> None:
    """write_file cria diretórios-pais ausentes (F2)."""
    from jarvis.core import devtools as D
    from jarvis.core.paths import use_project_root
    monkeypatch.chdir(tmp_path)
    with use_project_root(tmp_path):
        res = D.write_file(str(tmp_path / "a" / "b" / "f.txt"), "oi")
    assert res["ok"] is True
    assert (tmp_path / "a" / "b" / "f.txt").read_text() == "oi"


def test_looks_like_promise() -> None:
    import sys
    sys.path.insert(0, "modules/ai/jarvis/src")
    from jarvis.cli.dev import _looks_like_promise
    assert _looks_like_promise("Vou criar a pasta e os arquivos agora.")
    assert _looks_like_promise("I will check the logs.")
    assert not _looks_like_promise("A pasta foi criada com sucesso.")
    assert not _looks_like_promise("Não encontrei o arquivo.")


class TestReadDirHint:
    def test_read_directory_returns_listing(self, tmp_path, monkeypatch):
        """Sensor elo H3: read_file em diretório devolve a listagem junto
        (modelo conta sem outra call) em vez de erro seco."""
        import os
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        from jarvis.core import devtools as dt
        r = dt.read_file(str(tmp_path), 0, 10)
        assert r["ok"] is False
        assert "2 itens" in r["hint"]
        assert "a.txt" in r["hint"] and "b.txt" in r["hint"]


class TestRelapseShellContent:
    def test_shell_script_to_extensionless_path_refused(self, tmp_path, monkeypatch):
        """Cap estendido (elo H3b): modelo escreveu shell script
        (mkdir/echo) NO path do diretório — padrão fence/placeholder não
        pegava. Sem tool de delete, o erro é irrecuperável → fail-closed."""
        import os
        monkeypatch.chdir(tmp_path)
        from jarvis.core import devtools as dt
        r = dt.write_file("data", "mkdir -p /tmp/x\necho '' > f.txt\n")
        assert r["ok"] is False
        assert "DIRET" in r["error"]

    def test_legit_extensionless_still_allowed(self, tmp_path, monkeypatch):
        """Arquivo legítimo sem extensão (LICENSE-like) continua OK."""
        import os
        monkeypatch.chdir(tmp_path)
        from jarvis.core import devtools as dt
        import pathlib
        # _safe_path resolve paths relativos contra o project root (não o
        # cwd), então um nome relativo poluiria a raiz do repo a cada run
        # (artefato CH-UNIQUE-NOTES-XYZ comitado por git add -A). Usar path
        # absoluto sob tmp_path (/tmp é prefixo permitido pelo jail).
        target = tmp_path / "CH-UNIQUE-NOTES-XYZ"
        try:
            r = dt.write_file(str(target), "Release notes\n\nVersion 2 fixes the parser.\n")
            assert r["ok"] is True
            assert target.read_text() == "Release notes\n\nVersion 2 fixes the parser.\n"
        finally:
            target.unlink(missing_ok=True)
            for _b in pathlib.Path.home().glob(".local/state/jarvis/backups/CH-UNIQUE-NOTES-XYZ*"):
                _b.unlink(missing_ok=True)


class TestReadTruncationNotice:
    def test_truncated_read_announces(self, tmp_path, monkeypatch):
        """Sensor E3: leitura parcial anuncia total (modelo extrapolava)."""
        import os
        monkeypatch.chdir(tmp_path)
        (tmp_path / "l.txt").write_text("a\nb\nc\nd\n")
        from jarvis.core import devtools as dt
        import pathlib
        # resolve via project root: usa path absoluto no tmp
        r = dt.read_file(str(tmp_path / "l.txt"), 0, 1)
        assert r["ok"] is True
        assert "de 4 total" in r["content"]
        assert "MAIS linhas" in r["content"]

    def test_full_read_no_notice(self, tmp_path, monkeypatch):
        import os
        monkeypatch.chdir(tmp_path)
        (tmp_path / "l.txt").write_text("a\nb\n")
        from jarvis.core import devtools as dt
        r = dt.read_file(str(tmp_path / "l.txt"), 0, 10)
        assert r["ok"] is True
        assert "MAIS linhas" not in r["content"]


class TestCwdRelativeFallback:
    """CWD fora da raiz + sem pin: relativo = relativo ao CWD (POSIX).

    (heterogeneous real: task destacada lia relativo contra a raiz do
    repo em loop enquanto o `ls` mostrava os arquivos no cwd.)
    """

    def test_detached_cwd_resolves_relative(self, tmp_path, monkeypatch):
        import os
        monkeypatch.chdir(tmp_path)
        (tmp_path / "dado.csv").write_text("a\n")
        from jarvis.core import devtools as dt
        assert dt._safe_path("dado.csv") == (tmp_path / "dado.csv").resolve()

    def test_pinned_root_wins_over_cwd(self, tmp_path, monkeypatch):
        import os
        from jarvis.core.paths import use_project_root
        monkeypatch.chdir(tmp_path)
        (tmp_path / "dado.csv").write_text("a\n")
        from jarvis.core import devtools as dt
        from pathlib import Path
        other = tmp_path / "outro"
        other.mkdir()
        with use_project_root(other):
            assert dt._safe_path("dado.csv") == (other / "dado.csv").resolve()

    def test_explicit_root_param_wins(self, tmp_path, monkeypatch):
        import os
        from pathlib import Path
        monkeypatch.chdir(tmp_path)
        from jarvis.core import devtools as dt
        assert dt._safe_path("x.txt", root=Path("/tmp")) == Path("/tmp/x.txt")


class TestSystemPaths:
    def test_repo_map_has_system_paths_no_secrets(self):
        """SYSTEM PATHS no REPO MAP: paths declarativos legíveis, nunca
        valores (elo H1 — descoberta determinística, zero turns)."""
        import sys
        sys.path.insert(0, 'modules/ai/jarvis/src')
        from jarvis.cli.dev import _build_repo_map
        m = _build_repo_map('.', max_files=2, max_tokens=50)
        assert "SYSTEM PATHS" in m
        assert "/etc/jarvis/model-registry.json" in m
        assert "sk-" not in m and "gsk_" not in m and "tvly-" not in m


# ---------------------------------------------------------------------------
# immutable inputs (L8v33: modelo reescreveu logs de entrada)
# ---------------------------------------------------------------------------


def test_write_overwrite_log_blocked() -> None:
    """Sobrescrever .log pré-existente é bloqueado (input, não artefato)."""
    d = _tmp()
    f = d / "auth.log"
    f.write_text("line\n")
    r = write_file(str(f), "tampered\n")
    assert r["ok"] is False
    assert "INPUT" in r["error"]
    assert f.read_text() == "line\n"


def test_str_replace_log_blocked() -> None:
    """.log pré-existente nem via str_replace."""
    d = _tmp()
    f = d / "auth.log"
    f.write_text("Failed password\n")
    r = str_replace(str(f), "Failed", "X")
    assert r["ok"] is False
    assert "INPUT" in r["error"]
    assert "Failed" in f.read_text()


def test_run_created_csv_editable() -> None:
    """.csv criado no run pode ser editado (só pré-existente é imutável)."""
    d = _tmp()
    f = d / "data.csv"
    assert write_file(str(f), "a,b\n")["ok"] is True
    r = str_replace(str(f), "a,b", "a,c")
    assert r["ok"] is True
    assert "a,c" in f.read_text()


def test_preexisting_py_still_editable() -> None:
    """.py pré-existente edita normal (fix-tasks intactas)."""
    d = _tmp()
    f = d / "broken.py"
    f.write_text("x = 1\n")
    r = str_replace(str(f), "x = 1", "x = 2")
    assert r["ok"] is True
    assert "x = 2" in f.read_text()
