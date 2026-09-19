

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


def test_run_shell_kills_tree_on_timeout():
    """Timeout mata a ÁRVORE (killpg), não só o filho (L8r: script com
    auto-invocação recursava órfão após timeout)."""
    import subprocess as _sp
    from jarvis.core.security import run_shell
    r = run_shell("bash -c 'sleep 60 & wait'", timeout=2)
    assert r.returncode == -1
    assert "timed out" in r.stderr
    p = _sp.run(["pgrep", "-f", "[s]leep 60"], capture_output=True, text=True)
    assert p.returncode != 0, "stray process sobreviveu ao timeout"
