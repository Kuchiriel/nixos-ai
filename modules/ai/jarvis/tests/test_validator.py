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
