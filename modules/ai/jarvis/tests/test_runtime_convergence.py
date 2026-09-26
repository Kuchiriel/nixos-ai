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
    """Divergências conhecidas DEVEM estar no report (worklist da Fase 2).

    Se uma some sem merge declarado = alguém unificou sem registrar (ou o
    teste de leitura quebrou). Se uma NOVA aparece, este teste também falha
    (lista fechada) — atualizar junto com o merge real.
    """
    from jarvis.runtime.registry import ToolRegistry

    reg = ToolRegistry.build_default()
    by_canon = {d.canonical for d in reg.dialect_report()}
    # str_replace: devtools(old/new) vs mcp(old_string/new_string) — prova viva
    assert "str_replace" in by_canon, (
        "divergência str_replace sumiu do report sem merge registrado")
    assert len(reg.dialect_report()) >= 1


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
