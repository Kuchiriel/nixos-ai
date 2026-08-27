"""Post-tool-call validation layer.

Verifies tool execution results BEFORE they reach the model, preventing
the model from acting on incorrect assumptions about tool outcomes.

Principle: MODEL = UNTRUSTED COMPONENT, HARNESS = CONTROL LAYER.

The model may:
- claim success when a command actually failed
- interpret partial output as complete
- hallucinate file contents after write_file
- miss error patterns in shell output

This module catches these cases and injects corrective information.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.core.logging import get_logger

log = get_logger("validator")


@dataclass
class ValidationResult:
    """Result of validating a tool call output."""
    valid: bool
    enhanced_output: str  # original or corrected output
    warnings: list[str]   # issues found
    severity: str         # "ok" | "warning" | "error"


class ToolValidator:
    """Validates tool call results before passing to the model."""

    # Patterns that indicate shell command failure
    SHELL_ERROR_PATTERNS = [
        r"(?i)^error[:\s]",
        r"(?i)^fatal[:\s]",
        r"(?i)^traceback \(most recent",
        r"(?i)^segmentation fault",
        r"(?i)^permission denied",
        r"(?i)^no such file or directory",
        r"(?i)^command not found",
        r"(?i)^nix.*error",
        r"(?i)^build failed",
        r"(?i)^FAILED",
    ]

    # Patterns that indicate test failure
    TEST_FAILURE_PATTERNS = [
        r"(\d+) failed",
        r"FAILED",
        r"ERRORS",
        r"FAILED\b.*\d+",
    ]

    def validate(self, func_name: str, args: dict[str, Any],
                 output: str, exit_code: int | None = None) -> ValidationResult:
        """Validate a tool result. Returns enhanced output with warnings."""

        if func_name == "execute_shell":
            return self._validate_shell(args, output, exit_code)
        elif func_name == "write_file":
            return self._validate_write(args, output)
        elif func_name == "str_replace":
            return self._validate_str_replace(args, output)
        elif func_name == "read_file":
            return self._validate_read(args, output)
        elif func_name == "run_tests":
            return self._validate_tests(output)
        else:
            return ValidationResult(valid=True, enhanced_output=output,
                                    warnings=[], severity="ok")

    def _validate_shell(self, args: dict, output: str,
                        exit_code: int | None) -> ValidationResult:
        """Validate shell command output."""
        warnings = []
        enhanced = output

        # Check for error patterns
        for pattern in self.SHELL_ERROR_PATTERNS:
            if re.search(pattern, output):
                warnings.append(f"Shell output contains error pattern: {pattern}")
                break

        # Check exit code
        if exit_code is not None and exit_code != 0:
            warnings.append(f"Command exited with code {exit_code}")

        # Check for empty output on commands that should produce output
        cmd = args.get("cmd", "")
        if not output.strip() and any(cmd.startswith(p) for p in
                                       ("cat", "head", "tail", "grep", "rg")):
            warnings.append("Command produced empty output — file may not exist or may be empty")

        # Check for NixOS-specific errors
        if "infinite recursion" in output.lower():
            warnings.append("Infinite recursion detected — likely a Nix evaluation error")
        if "attribute" in output.lower() and "missing" in output.lower():
            warnings.append("Missing attribute — check Nix expression syntax")

        severity = "error" if warnings else "ok"
        return ValidationResult(valid=True, enhanced_output=enhanced,
                                warnings=warnings, severity=severity)

    def _validate_write(self, args: dict, output: str) -> ValidationResult:
        """Validate write_file result by checking file exists."""
        warnings = []
        path = args.get("path", "")

        if path:
            full_path = Path(path) if os.path.isabs(path) else Path.cwd() / path
            if not full_path.exists():
                warnings.append(f"write_file: file does not exist after write: {path}")
                severity = "error"
            else:
                # Check file size is reasonable
                size = full_path.stat().st_size
                if size == 0:
                    warnings.append(f"write_file: file is empty after write: {path}")
                    severity = "warning"
                elif size > 1_000_000:  # > 1MB
                    warnings.append(f"write_file: file is unusually large ({size} bytes): {path}")
                    severity = "warning"
                else:
                    severity = "ok"
        else:
            severity = "ok"

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def _validate_str_replace(self, args: dict, output: str) -> ValidationResult:
        """Validate str_replace result."""
        warnings = []

        # If the tool reports the string wasn't found, that's important
        if "not found" in output.lower() or "no match" in output.lower():
            warnings.append("str_replace: oldString was not found in file — replacement may not have happened")
            severity = "warning"
        elif "error" in output.lower():
            warnings.append(f"str_replace reported error: {output[:200]}")
            severity = "error"
        else:
            severity = "ok"

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def _validate_read(self, args: dict, output: str) -> ValidationResult:
        """Validate read_file result."""
        warnings = []
        path = args.get("path", "")

        if "not found" in output.lower() or "no such file" in output.lower():
            warnings.append(f"read_file: file not found: {path}")
            severity = "error"
        elif "permission denied" in output.lower():
            warnings.append(f"read_file: permission denied: {path}")
            severity = "error"
        elif not output.strip():
            warnings.append(f"read_file: file is empty: {path}")
            severity = "warning"
        else:
            severity = "ok"

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def _validate_tests(self, output: str) -> ValidationResult:
        """Validate run_tests output."""
        warnings = []

        for pattern in self.TEST_FAILURE_PATTERNS:
            match = re.search(pattern, output)
            if match:
                warnings.append(f"Tests reported failures: {match.group(0)}")
                severity = "error"
                return ValidationResult(valid=True, enhanced_output=output,
                                        warnings=warnings, severity=severity)

        # Check for collection errors
        if "ERRORS" in output and "error" in output.lower():
            warnings.append("Test collection errors detected")
            severity = "error"
        else:
            severity = "ok"

        return ValidationResult(valid=True, enhanced_output=output,
                                warnings=warnings, severity=severity)

    def enhance_tool_output(self, func_name: str, args: dict,
                            output: str, exit_code: int | None = None) -> str:
        """Validate and enhance tool output. Returns output with warnings injected.

        This is the main entry point — call it after every tool execution.
        """
        result = self.validate(func_name, args, output, exit_code)

        if not result.warnings:
            return output

        # Inject validation warnings into the output so the model sees them
        warning_block = "\n\n[VALIDATION WARNINGS]\n"
        for w in result.warnings:
            warning_block += f"⚠ {w}\n"
        warning_block += "[/VALIDATION WARNINGS]\n"

        log.info("tool_validation", detail={
            "tool": func_name,
            "severity": result.severity,
            "warnings": result.warnings,
        })

        return output + warning_block
