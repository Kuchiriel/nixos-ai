"""Linter estrutural da convergência p/ o Agent Runtime Kernel (ADR-005).

Filosofia (mesma de test_architecture_invariants.py): falhar ALTO quando a
arquitetura divergir do contrato, nunca passar silenciosamente com drift.

Fase 1: trava o estado ATUAL fragmentado com tetos explícitos. Cada fase da
reconstrução APERTA estes tetos (3 loops → 2 → 1). TARGET marcado em cada teste.
"""
from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
JARVIS = SRC / "jarvis"

# Arquivos que hoje contêm loop cognitivo próprio (for-range sobre turnos).
# TARGET F8: só jarvis/runtime/agent_runtime.py.
_COGNITIVE_LOOPS = {
    "jarvis/core/agent.py": "Agent.run",
    "jarvis/cli/dev.py": "_run_agent_loop",
    "nightwatch/harness.py": "Harness.execute_task",
}


def _has_turn_loop(path: Path) -> bool:
    text = path.read_text()
    return "for turn in range(" in text or "for attempt in range(" in text


def test_cognitive_loops_are_known_and_bounded() -> None:
    """Teto: nenhum NOVO loop cognitivo pode surgir sem atualizar este teste.

    TARGET: 1 (runtime/agent_runtime.py). Hoje: 3. Se este teste falha porque
    um 4º arquivo ganhou loop de turnos, a reconstrução REGREDIU.
    """
    found = {rel for rel in _COGNITIVE_LOOPS if _has_turn_loop(SRC / rel)}
    assert found == set(_COGNITIVE_LOOPS), (
        f"loops cognitivos mudaram: {found} — atualizar plano de convergência")
    assert len(found) == 3, f"esperado 3 loops na Fase 1, achado {len(found)}"


def test_llm_chokepoint_is_single_client() -> None:
    """Todo loop cognitivo chama o LLM via LLMClient (nunca backend direto).

    TARGET: 1 call-site (runtime). Hoje: agent+dev+harness via LLMClient —
    o choke point EXISTE, precisa ser PRESERVADO durante a extração.
    """
    import re
    users: set[str] = set()
    for rel in list(_COGNITIVE_LOOPS) + ["jarvis/core/router.py", "jarvis/core/rag.py",
                                         "jarvis/core/memory.py", "jarvis/core/vault.py"]:
        text = (SRC / rel).read_text()
        if "LLMClient" in text:
            users.add(rel)
    # os 3 loops + 3 providers legítimos usam LLMClient; router delega p/
    # MCPClient/HybridSearch e NUNCA toca LLM direto (verificado 26/09).
    # backend direto = 0 em todos os loops.
    for rel in _COGNITIVE_LOOPS:
        text = (SRC / rel).read_text()
        assert "LlamaCppBackend(" not in text and "PrismMLBackend(" not in text, (
            f"{rel} instancia backend LLM direto — choke point violado")
    assert users == {"jarvis/core/agent.py", "jarvis/cli/dev.py", "nightwatch/harness.py",
                      "jarvis/core/rag.py", "jarvis/core/memory.py",
                      "jarvis/core/vault.py"}, f"usuários de LLMClient mudaram: {users}"


def test_registry_covers_both_dialects() -> None:
    """ToolRegistry cobre a UNIÃO dos dialetos (nada se perde na leitura)."""
    from jarvis.core import devtools
    from jarvis import mcp_server
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    dev_names = {e["function"]["name"] for e in devtools.DEV_TOOLS}
    mcp_names = {e["name"] for e in mcp_server.JARVIS_TOOLS}
    from jarvis.runtime.registry import _CANONICAL_ALIASES

    def canon(n: str) -> str:
        return _CANONICAL_ALIASES.get(n, n.removeprefix("jarvis_"))

    for n in dev_names:
        assert canon(n) in reg.tools, f"DEV_TOOLS.{n} fora do registry"
    for n in mcp_names:
        assert canon(n) in reg.tools, f"JARVIS_TOOLS.{n} fora do registry"


def test_known_divergences_are_tracked() -> None:
    """Lista FECHADA de divergências SILENT (worklist da Fase 4).

    F2 mergeou str_replace no transporte (alias declarado old_string→old +
    passthrough de allow_multiple): ela SAIU do silent e entrou no declarado.
    Resta semantic_search (mesmo nome, executores E params diferentes —
    HybridSearch no MCP vs Qdrant próprio em devtools; merge = F4).
    Qualquer NOVA entrada ou sumiço sem merge = falha.
    """
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    silent = {d.canonical for d in reg.dialect_report()}
    assert silent == {"semantic_search"}, f"silent mudou: {silent}"
    assert "str_replace" in reg.declared_aliases(), (
        "alias declarado de str_replace sumiu — transporte voltou a forkar")


def test_resolve_translates_str_replace() -> None:
    """Transporte MCP → canônico: renames sem esmagar chaves existentes."""
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    canon, targs = reg.resolve("jarvis_str_replace", {
        "path": "f", "old_string": "A", "new_string": "B"})
    assert canon == "str_replace"
    assert targs == {"path": "f", "old": "A", "new": "B"}
    # explícito canônico vence alias (nunca esmaga)
    _, t2 = reg.resolve("jarvis_str_replace", {
        "path": "f", "old": "X", "old_string": "A", "new_string": "B"})
    assert t2["old"] == "X" and t2["new"] == "B"
    # desconhecido passa intacto (executor decide o erro)
    c3, t3 = reg.resolve("jarvis_nope", {"a": 1})
    assert (c3, t3) == ("nope", {"a": 1})


def test_mcp_str_replace_roundtrip(tmp_path) -> None:
    """REGRESSÃO F2: jarvis_str_replace via MCP estava MORTO (KeyError/
    args-ausentes — o executor esperava old/new, o transporte enviava
    old_string/new_string). Prova viva no caminho real."""
    import json
    from jarvis.mcp_server import call_tool

    f = tmp_path / "mcp.txt"
    f.write_text("AAA-BBB", encoding="utf-8")
    out = json.loads(call_tool("jarvis_str_replace", {
        "path": str(f), "old_string": "AAA", "new_string": "CCC"}))
    assert out.get("ok") is True, out
    assert f.read_text(encoding="utf-8") == "CCC-BBB"


def test_single_schema_emission() -> None:
    """Uma emissão de schema: 1 entrada por ferramenta canônica, sem prefixo."""
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    emitted = reg.to_openai_tools()
    names = [e["function"]["name"] for e in emitted]
    assert len(names) == len(set(names)), "schema emitido tem duplicata"
    assert not any(n.startswith("jarvis_") for n in names), (
        "schema canônico não usa prefixo jarvis_")
    assert len(names) == len(reg.tools)
