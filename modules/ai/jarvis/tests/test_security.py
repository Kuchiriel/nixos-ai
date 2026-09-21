

class TestPythonFileAllowed:
    def test_run_jail_file(self):
        from jarvis.core.security import command_allowed
        assert command_allowed("python3 /tmp/jarvis-ch/sum.py") is True
        assert command_allowed("python /tmp/x.py") is True

    def test_block_inline_and_flags(self):
        from jarvis.core.security import command_allowed
        assert command_allowed("python3 -c 'print(1)'") is False
        assert command_allowed("python3 -m pytest") is False
        assert command_allowed("python3") is False

    def test_block_outside_jail(self):
        from jarvis.core.security import command_allowed
        assert command_allowed("python3 /etc/passwd") is False


def test_run_shell_unbalanced_quotes_no_crash():
    """Aspas desbalanceadas viram exit 127, nunca exceção (L2 real)."""
    from jarvis.core.security import run_shell
    r = run_shell('echo "aberto')
    assert r.returncode == 127
    assert "quoting" in r.stderr.lower() or "aspas" in r.stderr.lower() or "ERROR" in r.stderr


def test_strip_redundant_chmod_run():
    """Idiom fundido vira só o run (L8: &&-fixação morria no ban)."""
    from jarvis.core.security import strip_redundant_chmod_run
    assert strip_redundant_chmod_run(
        "chmod +x d.sh && ./d.sh") == "./d.sh"
    assert strip_redundant_chmod_run(
        "chmod +x d.sh && ./d.sh 45.32.67.89") == "./d.sh 45.32.67.89"
    assert strip_redundant_chmod_run(
        "chmod +x d.sh; ./d.sh") == "./d.sh"
    # Basenames diferentes: NÃO casa (ban vale).
    assert strip_redundant_chmod_run(
        "chmod +x a.sh && ./b.sh") is None
    # Mais chaining no resto: NÃO casa.
    assert strip_redundant_chmod_run(
        "chmod +x a.sh && ./a.sh && ./b.sh") is None
    assert strip_redundant_chmod_run("ls -la") is None


def test_chaining_ignores_quoted_operators():
    """Operador dentro de aspas é literal (L8v40: sketch python3-c com `;`
    foi barrado — seguir a instrução virou punição)."""
    from jarvis.core.security import has_chaining_operators as hco
    assert hco('python3 -c "import json; open(\'a\',\'w\')"') is False
    assert hco("echo \"a && b\"") is False
    assert hco("grep 'a|b' f.log") is False
    assert hco("chmod +x x.sh && ./x.sh") is True
    assert hco("ls /tmp; echo done") is True
    assert hco("echo `whoami`") is True
    # Aspa não fechada NÃO é chaining (shlex barra depois com msg de
    # quoting — diagnóstico certo p/ sintoma certo).
    assert hco('echo "unclosed && ./x') is False


def test_run_shell_kills_tree_on_timeout():
    """Timeout mata a ÁRVORE (killpg), não só o filho (L8r: script com
    auto-invocação recursava órfão após timeout). Varredura /proc pura
    (stdlib): pgrep não existe no sandbox Nix (procps ausente — rebuild
    20/09 falhou aqui)."""
    from jarvis.core.security import run_shell
    r = run_shell("bash -c 'sleep 60 & wait'", timeout=2)
    assert r.returncode == -1
    assert "timed out" in r.stderr
    strays = []
    for _pid in filter(str.isdigit, __import__("os").listdir("/proc")):
        try:
            with open(f"/proc/{_pid}/cmdline", "rb") as _f:
                _cl = _f.read().replace(b"\x00", b" ").decode(
                    "utf-8", "replace")
        except OSError:
            continue
        if "sleep 60" in _cl:
            strays.append((_pid, _cl.strip()))
    assert not strays, f"stray process sobreviveu ao timeout: {strays}"


def test_echo_to_json():
    """echo/printf com redirect direto p/ *.json no mesmo segmento
    (v27/b3/w2: representação que mais falha; pós-escalada vira ban)."""
    from jarvis.core.security import echo_to_json
    assert echo_to_json("echo '{\"a\":1}' > a.json") is True
    assert echo_to_json("printf '%s' x >> out.json") is True
    assert echo_to_json("echo hi | jq -R . > a.json") is False
    assert echo_to_json("jq -n '{a:1}' > a.json") is False
    assert echo_to_json("echo hello") is False


def test_synth_grammars_escape_free_and_mapped():
    """Biblioteca GBNF sem escape `\\` (fork prism rejeita — spike 20/09) e
    suggest mapeia família (H-grammar)."""
    from jarvis.core.security import SYNTH_GRAMMARS, suggest_synth_grammar
    assert set(SYNTH_GRAMMARS) == {"grep", "jqread", "date", "chmod"}
    for g in SYNTH_GRAMMARS.values():
        assert '\\"' not in g
    assert suggest_synth_grammar("grep -c 'x' a.log") == "grep"
    assert suggest_synth_grammar("jq '.a' f.json") == "jqread"
    assert suggest_synth_grammar("date -u +%Y") == "date"
    assert suggest_synth_grammar("chmod +x f.sh") == "chmod"
    assert suggest_synth_grammar("python3 -c 'x'") is None
    assert suggest_synth_grammar("") is None


def test_run_shell_empty_command_is_error_not_crash():
    """cmd vazio (Ciclo 6: execute_shell c/ cmd='' → Popen([]) →
    IndexError cru, run perdido APÓS trabalho). ERROR legível."""
    from jarvis.core.security import run_shell
    for cmd in ("", "   "):
        r = run_shell(cmd)
        assert r.returncode == 127
        assert r.stderr.startswith("ERROR")
