"""Security Classification — classify files by sensitivity level.

MCU JARVIS understands: "don't want this winding up in the wrong hands"
Our JARVIS should classify files as: public, private, confidential, secret

This enables proactive security warnings when sensitive files are accessed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SecurityLevel:
    """Security classification level."""
    name: str
    description: str
    color: str  # For UI display
    icon: str   # For quick identification


# Security levels
PUBLIC = SecurityLevel("public", "Public - safe to share", "🟢", "🌐")
PRIVATE = SecurityLevel("private", "Private - personal use only", "🟡", "🔒")
CONFIDENTIAL = SecurityLevel("confidential", "Confidential - restricted access", "🟠", "🔐")
SECRET = SecurityLevel("secret", "Secret - never share", "🔴", "🗝️")

# File patterns that indicate security level
SECRET_PATTERNS = [
    r"\.env$",
    r"\.env\.",
    r"secret",
    r"token",
    r"api[_-]?key",
    r"password",
    r"credential",
    r"private[_-]?key",
    r"\.pem$",
    r"\.key$",
    r"id_rsa",
    r"id_ed25519",
]

CONFIDENTIAL_PATTERNS = [
    r"license",
    r"licen[cs]",
    r"hwid",
    r"hardware[_-]?id",
    r"machine[_-]?id",
    r"\.lic$",
    r"activation",
    r"serial",
    r"registration",
]

PRIVATE_PATTERNS = [
    r"config\.json$",
    r"config\.yaml$",
    r"config\.yml$",
    r"settings",
    r"preferences",
    r"mudream_config",
    r"wurm_config",
    r"\.jarvismodes$",
    r"\.roomodes$",
    r"nightlog",
    r"todo",
    r"handoff",
    r"vault",
    r"memory",
    r"remember",
]

# Directories that are always secret
SECRET_DIRS = [
    ".ssh",
    ".gnupg",
    ".config/sops",
    "licencas",
]

# Directories that are always confidential
CONFIDENTIAL_DIRS = [
    "credentials",
    "secrets",
    ".env",
]


@dataclass
class ClassificationResult:
    """Result of file security classification."""
    path: str
    level: SecurityLevel
    reason: str
    patterns_matched: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "level": self.level.name,
            "description": self.level.description,
            "icon": self.level.icon,
            "reason": self.reason,
            "patterns": self.patterns_matched,
        }


def classify_file(file_path: str | Path) -> ClassificationResult:
    """Classify a file's security level based on name and content patterns."""
    path = Path(file_path)
    name = path.name.lower()
    parent_dirs = [p.lower() for p in path.parts]
    reasons = []
    patterns_matched = []

    # Check if in secret directory
    for secret_dir in SECRET_DIRS:
        if secret_dir.lower() in parent_dirs:
            reasons.append(f"In secret directory: {secret_dir}")
            patterns_matched.append(f"dir:{secret_dir}")

    # Check if in confidential directory
    for conf_dir in CONFIDENTIAL_DIRS:
        if conf_dir.lower() in parent_dirs:
            reasons.append(f"In confidential directory: {conf_dir}")
            patterns_matched.append(f"dir:{conf_dir}")

    # Check filename against secret patterns
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            reasons.append(f"Matches secret pattern: {pattern}")
            patterns_matched.append(f"secret:{pattern}")

    # Check filename against confidential patterns
    for pattern in CONFIDENTIAL_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            reasons.append(f"Matches confidential pattern: {pattern}")
            patterns_matched.append(f"confidential:{pattern}")

    # Check filename against private patterns
    for pattern in PRIVATE_PATTERNS:
        if re.search(pattern, name, re.IGNORECASE):
            reasons.append(f"Matches private pattern: {pattern}")
            patterns_matched.append(f"private:{pattern}")

    # Determine final level (highest wins)
    if any("secret" in p for p in patterns_matched):
        return ClassificationResult(
            path=str(path),
            level=SECRET,
            reason="; ".join(reasons) if reasons else "Secret file detected",
            patterns_matched=patterns_matched,
        )
    elif any("confidential" in p for p in patterns_matched):
        return ClassificationResult(
            path=str(path),
            level=CONFIDENTIAL,
            reason="; ".join(reasons) if reasons else "Confidential file detected",
            patterns_matched=patterns_matched,
        )
    elif any("private" in p for p in patterns_matched):
        return ClassificationResult(
            path=str(path),
            level=PRIVATE,
            reason="; ".join(reasons) if reasons else "Private file detected",
            patterns_matched=patterns_matched,
        )
    elif any("dir:" in p for p in patterns_matched):
        # Directory-based classification
        if any("secret" in p for p in patterns_matched):
            return ClassificationResult(str(path), SECRET, "; ".join(reasons), patterns_matched)
        elif any("confidential" in p for p in patterns_matched):
            return ClassificationResult(str(path), CONFIDENTIAL, "; ".join(reasons), patterns_matched)

    # Default to public
    return ClassificationResult(
        path=str(path),
        level=PUBLIC,
        reason="No sensitive patterns detected",
        patterns_matched=[],
    )


def classify_directory(dir_path: str | Path, max_depth: int = 3) -> list[ClassificationResult]:
    """Classify all files in a directory."""
    results = []
    root = Path(dir_path)

    if not root.exists():
        return results

    for item in root.rglob("*"):
        if item.is_file() and item.stat().st_size < 1_000_000:  # Skip files > 1MB
            try:
                result = classify_file(item)
                if result.level != PUBLIC:  # Only report non-public files
                    results.append(result)
            except Exception:
                pass

    return results


def get_security_summary(dir_path: str | Path = ".") -> dict[str, Any]:
    """Get a security summary of a directory."""
    results = classify_directory(dir_path)

    summary = {
        "total_files": len(results),
        "by_level": {
            "secret": [],
            "confidential": [],
            "private": [],
        },
        "warnings": [],
    }

    for result in results:
        if result.level.name == "secret":
            summary["by_level"]["secret"].append(result.to_dict())
            summary["warnings"].append(f"⚠️ SECRET: {result.path} — {result.reason}")
        elif result.level.name == "confidential":
            summary["by_level"]["confidential"].append(result.to_dict())
            summary["warnings"].append(f"🔐 CONFIDENTIAL: {result.path} — {result.reason}")
        elif result.level.name == "private":
            summary["by_level"]["private"].append(result.to_dict())

    return summary


def format_security_summary(summary: dict[str, Any]) -> str:
    """Format security summary for display."""
    lines = ["🔒 Security Classification Summary\n"]

    secret_count = len(summary["by_level"]["secret"])
    conf_count = len(summary["by_level"]["confidential"])
    priv_count = len(summary["by_level"]["private"])

    lines.append(f"🗝️  Secret:        {secret_count} files")
    lines.append(f"🔐 Confidential:  {conf_count} files")
    lines.append(f"🔒 Private:       {priv_count} files")

    if summary["warnings"]:
        lines.append("\n⚠️  Warnings:")
        for warning in summary["warnings"][:10]:  # Show top 10
            lines.append(f"  {warning}")
        if len(summary["warnings"]) > 10:
            lines.append(f"  ... and {len(summary['warnings']) - 10} more")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "."
    summary = get_security_summary(path)
    print(format_security_summary(summary))
