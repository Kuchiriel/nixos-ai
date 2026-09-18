"""Tests for the post-tool-call validation layer."""
import pytest
from jarvis.core.validator import ToolValidator, ValidationResult


@pytest.fixture
def validator():
    return ToolValidator()


class TestShellValidation:
    def test_clean_output(self, validator):
        result = validator.validate("execute_shell", {"cmd": "echo hello"}, "hello\n")
        assert result.valid is True
        assert result.severity == "ok"
        assert result.warnings == []

    def test_error_pattern(self, validator):
        result = validator.validate("execute_shell", {"cmd": "ls"}, "error: something broke")
        assert result.valid is True  # valid=True means we pass it through
        assert result.severity == "error"
        assert len(result.warnings) == 1

    def test_permission_denied(self, validator):
        result = validator.validate("execute_shell", {"cmd": "cat /etc/shadow"}, "permission denied")
        assert result.severity == "error"

    def test_empty_grep_output(self, validator):
        result = validator.validate("execute_shell", {"cmd": "grep foo bar.txt"}, "")
        assert any("empty output" in w for w in result.warnings)

    def test_nix_infinite_recursion(self, validator):
        result = validator.validate("execute_shell", {"cmd": "nix build"}, "infinite recursion encountered")
        assert any("Infinite recursion" in w for w in result.warnings)

    def test_clean_nix_build(self, validator):
        result = validator.validate("execute_shell", {"cmd": "nix build"}, "building...")
        assert result.severity == "ok"


class TestWriteValidation:
    def test_file_exists_after_write(self, validator, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")
        result = validator.validate("write_file", {"path": str(test_file)}, "OK")
        assert result.severity == "ok"

    def test_file_missing_after_write(self, validator, tmp_path):
        result = validator.validate("write_file", {"path": str(tmp_path / "missing.txt")}, "OK")
        assert result.severity == "error"
        assert any("does not exist" in w for w in result.warnings)

    def test_empty_file_warning(self, validator, tmp_path):
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")
        result = validator.validate("write_file", {"path": str(test_file)}, "OK")
        assert result.severity == "warning"
        assert any("empty" in w for w in result.warnings)


class TestStrReplaceValidation:
    def test_successful_replace(self, validator):
        result = validator.validate("str_replace", {}, "Replaced successfully")
        assert result.severity == "ok"

    def test_string_not_found(self, validator):
        result = validator.validate("str_replace", {}, "oldString not found in file")
        assert result.severity == "warning"


class TestReadValidation:
    def test_normal_read(self, validator):
        result = validator.validate("read_file", {"path": "/etc/hostname"}, "myhost")
        assert result.severity == "ok"

    def test_file_not_found(self, validator):
        result = validator.validate("read_file", {"path": "/nonexistent"}, "No such file or directory")
        assert result.severity == "error"

    def test_empty_file(self, validator):
        result = validator.validate("read_file", {"path": "/tmp/empty"}, "")
        assert result.severity == "warning"


class TestTestValidation:
    def test_all_passing(self, validator):
        result = validator.validate("run_tests", {}, "42 passed in 1.23s")
        assert result.severity == "ok"

    def test_some_failing(self, validator):
        result = validator.validate("run_tests", {}, "40 passed, 2 failed in 1.23s")
        assert result.severity == "error"
        assert any("failures" in w for w in result.warnings)


class TestEnhanceOutput:
    def test_no_warnings_passes_through(self, validator):
        output = validator.enhance_tool_output("execute_shell", {"cmd": "echo hi"}, "hi\n")
        assert output == "hi\n"

    def test_warnings_injected(self, validator):
        output = validator.enhance_tool_output("execute_shell", {"cmd": "ls"}, "error: permission denied")
        assert "[VALIDATION WARNINGS]" in output
        assert "⚠" in output

    def test_unknown_tool_passes_through(self, validator):
        output = validator.enhance_tool_output("unknown_tool", {}, "some output")
        assert output == "some output"


def test_read_not_found_suggests_candidates(tmp_path, monkeypatch) -> None:
    """Recovery coach: not-found vem com candidatos (não só erro)."""
    from jarvis.core.validator import ToolValidator
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "alvo.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate("read_file", {"path": "alvo.txt"},
                                  "ERROR: File not found: alvo.txt")
    assert any("candidato" in w for w in vr.warnings)
    assert any("sub/alvo.txt" in w for w in vr.warnings)


def test_read_not_found_no_candidate_still_error(tmp_path, monkeypatch) -> None:
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate("read_file", {"path": "nada.txt"},
                                  "ERROR: File not found: nada.txt")
    assert any("not found" in w for w in vr.warnings)


def test_read_not_found_without_candidates_teaches_creation(tmp_path, monkeypatch) -> None:
    """Anti-loop: sem candidato nenhum, a observação ensina a ação de criar
    (A/B 16/09 — modelo verificava o alvo que deveria criar e morria em
    "File not found" sem saída)."""
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate("read_file", {"path": "novo/nada.txt"},
                                  "ERROR: File not found: novo/nada.txt")
    assert any("write_file" in w for w in vr.warnings)
    assert any("CRIAR" in w for w in vr.warnings)


def test_git_forensics_suppressed_in_secret_task(tmp_path, monkeypatch) -> None:
    """Task de segredo: git-forense suprimido (senão sequestra)."""
    from jarvis.core.validator import ToolValidator
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    v = ToolValidator()
    v.secret_task = True
    vr = v.validate("read_file", {"path": "x"}, "ERROR: File not found: x")
    assert not any("reflog" in w for w in vr.warnings)


def test_read_not_found_in_git_repo_teaches_forensics(tmp_path, monkeypatch) -> None:
    """Sensor git-forense: not-found dentro de repo git entrega receita de
    recon (reflog/branch/stash) — modelo pequeno não chega lá sozinho."""
    from jarvis.core.validator import ToolValidator
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate("read_file", {"path": "sumido.md"},
                                  "ERROR: File not found: sumido.md")
    assert any("reflog" in w for w in vr.warnings)
    assert any("HIST" in w for w in vr.warnings)


def test_read_not_found_outside_git_no_forensics(tmp_path, monkeypatch) -> None:
    """Fora de repo git: sem receita forense (ruído limitado)."""
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate("read_file", {"path": "sumido.md"},
                                  "ERROR: File not found: sumido.md")
    assert not any("reflog" in w for w in vr.warnings)


def test_git_root_nested_and_never_raises(tmp_path, monkeypatch) -> None:
    from jarvis.core.validator import _git_root
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    assert _git_root() is not None
    monkeypatch.chdir(tmp_path / "a")
    (tmp_path / ".git").rmdir()
    assert _git_root() is None


def test_git_status_clean_suggests_history(validator) -> None:
    """Árvore limpa não encerra investigação: sugere reflog/stash/log."""
    out = "On branch master\nnothing to commit, working tree clean\n"
    r = validator.validate("execute_shell", {"cmd": "git status"}, out)
    assert any("reflog" in w for w in r.warnings)


def test_git_status_dirty_no_history_hint(validator) -> None:
    out = "On branch master\nChanges not staged for commit:\n\tmodified: x\n"
    r = validator.validate("execute_shell", {"cmd": "git status"}, out)
    assert not any("reflog" in w for w in r.warnings)


def test_reflog_output_extracts_candidates(validator) -> None:
    """Grounding: hashes do reflog viram candidatos nomeados."""
    out = ("d7d3e4b HEAD@{0}: checkout: moving to master\n"
           "f0fcc1d HEAD@{1}: commit: Move to Stanford\n")
    r = validator.validate(
        "execute_shell", {"cmd": "git reflog | head -20"}, out)
    assert any("f0fcc1d" in w for w in r.warnings)
    assert any("Move to Stanford" in w for w in r.warnings)


def test_reflog_next_prefers_commit_over_checkout(validator) -> None:
    """NEXT aponta o commit dangling, não o move do HEAD."""
    out = ("d7d3e4b HEAD@{0}: checkout: moving to master\n"
           "f0fcc1d HEAD@{1}: commit: Move to Stanford\n")
    r = validator.validate(
        "execute_shell", {"cmd": "git reflog -n 20"}, out)
    nxt = next(w for w in r.warnings if w.startswith("reflog/fsck"))
    assert "git show f0fcc1d" in nxt
    assert "checkout -b recovery f0fcc1d" in nxt


def test_non_git_shell_output_no_reflog_hint(validator) -> None:
    r = validator.validate("execute_shell", {"cmd": "ls -la"}, "a\nb\n")
    assert not any("reflog" in w for w in r.warnings)


def test_git_merge_noop_warns_direction(validator) -> None:
    """`git merge` Already up to date = direção suspeita, não sucesso."""
    r = validator.validate(
        "execute_shell", {"cmd": "git merge master"},
        "Already up to date.\n")
    assert any("NO-OP" in w for w in r.warnings)
    assert any("checkout -b" in w for w in r.warnings)


def test_git_merge_real_success_no_warning(validator) -> None:
    r = validator.validate(
        "execute_shell", {"cmd": "git merge recovery"},
        "Merge made by the 'ort' strategy.\n file changed.\n")
    assert not any("NO-OP" in w for w in r.warnings)


def test_git_show_suggests_execute_not_explain(validator) -> None:
    """show com conteúdo → manda EXECUTAR o próximo passo, não narrar."""
    out = ("commit f0fcc1d\nAuthor: t\n\n    Move to Stanford\n\n"
           "diff --git a/x b/x\n 1 file changed\n")
    r = validator.validate(
        "execute_shell", {"cmd": "git show f0fcc1d --stat"}, out)
    assert any("EXECUTE agora" in w for w in r.warnings)


def test_git_show_empty_no_hint(validator) -> None:
    r = validator.validate(
        "execute_shell", {"cmd": "git show HEAD --stat"}, "")
    assert not any("EXECUTE agora" in w for w in r.warnings)


def test_write_bad_json_suggests_script(tmp_path, monkeypatch) -> None:
    """JSON malformado na mão: manda ler inputs e usar script+json.dumps."""
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    r = ToolValidator().validate(
        "write_file", {"path": "organization.json", "content": "["},
        "JSON error: Expecting ',' delimiter")
    assert any("json.dumps" in w for w in r.warnings)
    assert any("LEIA" in w for w in r.warnings)


def test_write_invented_config_dir_warns(tmp_path, monkeypatch) -> None:
    """write_file criando .huggingface/ novo = config inventada."""
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    r = ToolValidator().validate(
        "write_file",
        {"path": ".huggingface/settings.json", "content": "{}"},
        "ok: write_file .huggingface/settings.json")
    assert any("CRIANDO" in w for w in r.warnings)


def test_str_replace_invented_path_warns_grep(tmp_path, monkeypatch) -> None:
    """str_replace em caminho inexistente: avisa e manda grepar real."""
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    r = ToolValidator().validate(
        "str_replace", {"path": ".aws/credentials", "old": "x", "new": "y"},
        "String not found in file")
    assert any("não invente" in w for w in r.warnings)
    assert any("AKIA" in w for w in r.warnings)


def test_str_replace_on_directory_teaches_file(validator) -> None:
    """str_replace em pasta: ensina operar em arquivo observado."""
    r = validator.validate(
        "str_replace", {"path": "repo", "old": "x", "new": "y"},
        "ERROR: Replace error: [Errno 21] Is a directory: 'repo'")
    assert any("DIRETÓRIO" in w for w in r.warnings)


def test_str_replace_multi_match_warns_docs(validator) -> None:
    """N ocorrências: desaconselha allow_multiple cego, manda refinar."""
    r = validator.validate(
        "str_replace", {"path": "README.md", "old": "KEY", "new": "x"},
        "ERROR: String found 2 times (use allow_multiple=True)")
    assert any("allow_multiple" in w for w in r.warnings)
    assert any("contexto único" in w for w in r.warnings)


def test_str_replace_key_name_warns_value(validator) -> None:
    """UPPER_SNAKE → <placeholder>: alerta NOME vs VALOR."""
    r = validator.validate(
        "str_replace",
        {"path": "cfg.py", "old": "AWS_ACCESS_KEY_ID",
         "new": "<your-aws-access-key-id>"},
        "ok: str_replace cfg.py")
    assert any("NOME da chave" in w for w in r.warnings)


def test_python_c_syntax_error_suggests_file(validator) -> None:
    """Quoting aninhado: manda gravar .py em vez de reinsistir."""
    r = validator.validate(
        "execute_shell", {"cmd": "python3 -c \"print('x')\""},
        "SyntaxError: invalid syntax")
    assert any("write_file" in w for w in r.warnings)
    assert any("calc.py" in w for w in r.warnings)


def test_pyfile_traceback_suggests_edit(validator) -> None:
    """Traceback em .py próprio: manda editar, não voltar ao -c."""
    r = validator.validate(
        "execute_shell", {"cmd": "python3 calc.py"},
        "Traceback (most recent call last):\nValueError: x")
    assert any("str_replace" in w for w in r.warnings)
    assert any("calc.py" in w for w in r.warnings)


def test_grep_key_name_suggests_value_shapes(validator) -> None:
    """Grep por NOME DE CHAVE: sugere shapes de valor."""
    r = validator.validate(
        "execute_shell", {"cmd": "grep -r AWS_ACCESS_KEY_ID ."},
        "a.py:x\n")
    assert any("AKIA" in w for w in r.warnings)


def test_float_header_hint(validator) -> None:
    """float() no header: manda pular header/vazios."""
    r = validator.validate(
        "execute_shell", {"cmd": "python3 calc.py"},
        "ValueError: could not convert string to float: 'temperature'")
    assert any("next(reader)" in w for w in r.warnings)


def test_grep_hits_with_values_prioritized(validator) -> None:
    """Hits COM VALOR viram lista priorizada (sem vazar valores)."""
    out = ("a/README.md: export AWS_ACCESS_KEY_ID=\n"
           "a/real.py: KEY = \"AKIA1234567890123456\"\n")
    r = validator.validate(
        "execute_shell", {"cmd": "grep -r AWS ."}, out)
    w = " ".join(r.warnings)
    assert "a/real.py" in w
    assert "AKIA1234567890123456" not in w


def test_grep_without_values_no_priority(validator) -> None:
    r = validator.validate(
        "execute_shell", {"cmd": "grep -r KEY ."}, "a.py:x\n")
    assert not any("COM VALOR" in w for w in r.warnings)


def test_modulenotfound_suggests_other_interpreter(validator) -> None:
    """ModuleNotFoundError: manda achar interpretador, veta pip global."""
    r = validator.validate(
        "execute_shell", {"cmd": "python3 -c 'import pandas'"},
        "Traceback (most recent call last):\nModuleNotFoundError: pandas")
    assert any("kvenv" in w for w in r.warnings)
    assert any("pip install global" in w for w in r.warnings)


def test_str_replace_normal_value_no_warning(validator) -> None:
    r = validator.validate(
        "str_replace",
        {"path": "cfg.py", "old": "AKIA123", "new": "<your-key>"},
        "ok: str_replace cfg.py")
    assert not any("NOME da chave" in w for w in r.warnings)


def test_secret_sweep_reports_remaining(tmp_path, monkeypatch) -> None:
    """Pós-sanitização: segredo restante no arquivo é reportado por tipo."""
    from jarvis.core.validator import ToolValidator
    f = tmp_path / 'cfg.py'
    f.write_text('KEY = "AKIA1234567890123456"' + chr(10))
    monkeypatch.chdir(tmp_path)
    r = ToolValidator().validate(
        'str_replace',
        {'path': 'cfg.py', 'old': 'AWS_ACCESS_KEY_ID',
         'new': '<your-aws-access-key-id>'},
        'ok: str_replace cfg.py')
    assert any('INCOMPLETA' in w for w in r.warnings)
    assert any('aws-key' in w for w in r.warnings)
    assert 'AKIA1234567890123456' not in ' '.join(r.warnings)


def test_secret_sweep_clean_when_done(tmp_path, monkeypatch) -> None:
    f = tmp_path / 'cfg.py'
    f.write_text('KEY = "<your-aws-access-key-id>"' + chr(10))
    monkeypatch.chdir(tmp_path)
    from jarvis.core.validator import ToolValidator
    r = ToolValidator().validate(
        'write_file',
        {'path': 'cfg.py', 'content': 'KEY = "<your-aws-access-key-id>"'},
        'ok: write_file cfg.py')
    assert any('nenhum padr' in w for w in r.warnings)


def test_noisy_grep_output_suggests_narrowing(validator) -> None:
    """Busca com 40+ linhas: sugere estreitar em vez de repetir."""
    out = "\n".join(f"f{i}.py:match" for i in range(50))
    r = validator.validate(
        "execute_shell", {"cmd": "grep -r KEY ."}, out)
    assert any("restrinja o escopo" in w for w in r.warnings)


def test_short_output_no_narrowing_hint(validator) -> None:
    r = validator.validate(
        "execute_shell", {"cmd": "grep -r KEY ray_processing/"}, "a.py:x\n")
    assert not any("restrinja o escopo" in w for w in r.warnings)


def test_find_exec_chaining_suggests_grep(validator) -> None:
    """find -exec bloqueado: sugere grep -rlE direto."""
    r = validator.validate(
        "execute_shell", {"cmd": "find . -type f -exec grep -l x {} ;"},
        "ERROR: Chaining operators not allowed: find . -type f -exec grep -l x {} ;")
    assert any("grep -rlE" in w for w in r.warnings)


def test_chaining_denied_teaches_split(validator) -> None:
    """`Chaining operators not allowed` → ensina dividir, não insistir."""
    r = validator.validate(
        "execute_shell", {"cmd": "a; b"},
        "ERROR: Chaining operators not allowed: a; b")
    assert any("UMA tool call" in w for w in r.warnings)


def test_read_directory_en_matches(validator, tmp_path, monkeypatch) -> None:
    """'Not a file' (EN) também ensina listagem."""
    from jarvis.core.validator import ToolValidator
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate(
        "read_file", {"path": "pasta"}, "ERROR: Not a file: pasta")
    assert any("list_directory" in w for w in vr.warnings)


def test_read_directory_teaches_listing_and_git(tmp_path, monkeypatch) -> None:
    """Ler diretório como arquivo: ensina listagem + recon git."""
    from jarvis.core.validator import ToolValidator
    (tmp_path / ".git").mkdir()
    (tmp_path / "pasta").mkdir()
    monkeypatch.chdir(tmp_path)
    vr = ToolValidator().validate(
        "read_file", {"path": "pasta"},
        "ERROR: 'pasta' é um diretório, não arquivo")
    assert any("list_directory" in w for w in vr.warnings)
    assert any("reflog" in w for w in vr.warnings)
