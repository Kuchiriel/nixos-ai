"""(30/09) Resolução de target do LLM discovery — a 4a camada do bug de
gerador. O LLM inventava path, a task morria no patch loop ("No readable
target files"). Aqui travamos o comportamento.
"""
import sys
from pathlib import Path

import pytest

from nightwatch.harness import (
    _normalize_target,
    _resolve_llm_targets,
    _target_is_actionable,
)

ROOT = Path("/home/nixos/projects/nixos-ai")
KNOWN = [
    "modules/ai/jarvis/src/jarvis/core/agent.py",
    "modules/ai/jarvis/src/jarvis/core/rag.py",
    "modules/ai/jarvis/src/jarvis/core/devtools.py",
]


def test_normalize_absolute_to_relative():
    raw = "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/agent.py"
    assert _normalize_target(raw, ROOT) == "modules/ai/jarvis/src/jarvis/core/agent.py"


def test_normalize_strips_backticks_quotes_comma():
    assert _normalize_target("`modules/ai/jarvis/src/jarvis/core/rag.py`", ROOT) == \
        "modules/ai/jarvis/src/jarvis/core/rag.py"
    assert _normalize_target('"AGENTS.md", "X.md"', ROOT) == "AGENTS.md"
    assert _normalize_target("   ", ROOT) == ""


def test_resolve_absolute_real_file():
    raw = ["/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/core/rag.py"]
    assert _resolve_llm_targets(raw, ROOT, KNOWN) == ["modules/ai/jarvis/src/jarvis/core/rag.py"]


def test_resolve_bare_basename_maps_to_full_path():
    assert _resolve_llm_targets(["devtools.py"], ROOT, KNOWN) == \
        ["modules/ai/jarvis/src/jarvis/core/devtools.py"]


def test_resolve_rejects_invented_python_path():
    # path inventado com .py NÃO pode virar CREATE aqui — discovery é
    # "melhorar código existente", não "criar arquivo".
    assert _resolve_llm_targets(["src/nao_existe.py"], ROOT, KNOWN) == []


def test_resolve_rejects_prose_and_dir():
    assert _resolve_llm_targets(["Todos os módulos"], ROOT, KNOWN) == []
    assert _resolve_llm_targets(["core/"], ROOT, KNOWN) == []


def test_resolve_empty_and_dedupe():
    assert _resolve_llm_targets([], ROOT, KNOWN) == []
    dup = ["agent.py", "agent.py"]
    assert _resolve_llm_targets(dup, ROOT, KNOWN) == KNOWN[:1]


def test_target_is_actionable_basics():
    assert _target_is_actionable("modules/ai/jarvis/src/jarvis/core/agent.py")
    assert not _target_is_actionable("modules/ai/jarvis/src/jarvis/core/")  # dir
    assert not _target_is_actionable("Todos os módulos de serviço")  # prose
    assert not _target_is_actionable("`modules/ai/models.nix`")  # backtick
    assert not _target_is_actionable("")  # empty