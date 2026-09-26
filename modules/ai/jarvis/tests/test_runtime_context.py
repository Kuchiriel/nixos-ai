"""ContextAssembler único — Fase 3 (ADR-005).

Prova: builders geram bytes idênticos ao inline antigo + assembler registra
provenance + sites de montagem travados (2 hoje, TARGET 1 na F8).
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def test_environment_block_golden() -> None:
    from jarvis.runtime.context import environment_block

    out = environment_block()
    assert out.startswith("\n\nENVIRONMENT:\n- OS: ")
    assert "\n- Python: " in out and "\n- CWD: " in out and "\n- User: " in out
    assert "\n- Now: 20" in out  # data/hora/timezone estáticas (F-pesquisa)


def test_lessons_block_golden_and_outage() -> None:
    from jarvis.runtime.context import lessons_block

    class Mem:
        def lessons(self, query, *, top_k=3):
            assert query == "arrume o qdrant" and top_k == 3
            return "\nPAST LESSONS (avoid these mistakes):\n- x\n"

    out = lessons_block(Mem(), "arrume o qdrant")
    assert out == "\n\nAVOID (past errors):\nPAST LESSONS (avoid these mistakes):\n- x\n"
    assert lessons_block(None, "q") == ""

    seen: list = []

    class Broken:
        def lessons(self, query, *, top_k=3):
            raise ConnectionError("qdrant down")

    assert lessons_block(Broken(), "q", emit=lambda e, **k: seen.append((e, k))) == ""
    assert seen and seen[0][0] == "lessons_unavailable"
    assert seen[0][1]["detail"]["error"] == "ConnectionError"


def test_persona_and_profile_blocks() -> None:
    from jarvis.runtime.context import persona_section, user_profile_block

    class P:
        name = "N"; role = "R"; system_prompt_additions = "ADD"

    assert persona_section(P()) == "\n\nPERSONA ATIVA: N (R)\nADD"
    assert persona_section(None) == ""
    assert persona_section(P()) != ""
    # user_profile é best-effort: nunca quebra, retorna str
    assert isinstance(user_profile_block(), str)


def test_assembler_provenance() -> None:
    from jarvis.runtime.context import ContextAssembler, environment_block

    asm = ContextAssembler()
    asm.add("identity", lambda: "You are JARVIS.")
    asm.add("empty", lambda: "")
    asm.add("environment", environment_block)
    system, prov = asm.assemble()
    assert system.startswith("You are JARVIS.")
    assert "ENVIRONMENT:" in system
    assert prov["sections"] == ["identity", "environment"]
    assert prov["count"] == 2


def test_assembly_sites_bounded() -> None:
    """Sites de montagem de system prompt conhecidos (TARGET F8: 1).

    agent.py monta via builders do runtime (F3); dev.py ainda tem seu
    template próprio (F8 o converte). 3º site = o próprio runtime/context.py.
    """
    agent = (SRC / "jarvis/core/agent.py").read_text()
    dev = (SRC / "jarvis/cli/dev.py").read_text()
    assert "runtime.context import" in agent or "runtime/context" in agent or \
        "from jarvis.runtime.context import" in agent
    assert "SYSTEM_PROMPT_TEMPLATE" in dev
    # nenhum OUTRO arquivo monta system prompt de agente
    others = []
    for p in list((SRC / "jarvis/core").glob("*.py")) + list((SRC / "jarvis/cli").glob("*.py")):
        if p.name in ("agent.py", "context.py") or p.parent.name == "cli" and p.name == "dev.py":
            continue
        try:
            t = p.read_text()
        except Exception:
            continue
        if "SYSTEM_PROMPT_TEMPLATE" in t or 'system_content = "You are JARVIS' in t:
            others.append(p.name)
    assert others == [], f"novo site de montagem: {others}"


def test_dev_prompt_byte_identical_to_template() -> None:
    """F8: _build_system_prompt == SYSTEM_PROMPT_TEMPLATE.format (bytes).

    Com partes cheias E vazias (separadores preservados). Se o template
    mudar, este teste quebra junto — atualizar os dois.
    """
    from jarvis.cli.dev import (
        SYSTEM_PROMPT_TEMPLATE,
        _TOOL_DISCIPLINE,
        _build_system_prompt,
    )

    cases = [
        ("MAPA", "MEM", "CTX", "\n\nPERSONA ATIVA: j (r)\nADD", "DISC", "CAT"),
        ("MAPA", "", "", "", "", ""),
        ("", "", "", "", "", ""),
    ]
    for repo, mem, ctx, pers, disc, cat in cases:
        expected = SYSTEM_PROMPT_TEMPLATE.format(
            repo_map=repo, memory_context=mem, agent_context=ctx,
            persona_block=pers, tool_discipline=disc, tools_catalog=cat)
        got = _build_system_prompt(repo, mem, ctx, pers, disc, cat)
        assert got == expected, f"divergiu com persona={pers!r:.20}"
