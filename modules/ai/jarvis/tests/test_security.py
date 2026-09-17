

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
