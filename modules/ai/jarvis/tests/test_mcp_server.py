"""MCP server surface: no shadow tools (eliminação 21/09)."""
from jarvis.mcp_server import JARVIS_TOOLS, call_tool


def _names():
    return {t.get("name") for t in JARVIS_TOOLS}


def test_no_shadow_tools():
    """Removidos: proactive_check, system_health, classify_* (chamáveis
    mas invisíveis, sem testes, sem chamadores)."""
    for n in ("jarvis_proactive_check", "jarvis_system_health",
              "jarvis_classify_file", "jarvis_classify_directory"):
        assert n not in _names()
        assert call_tool(n, {}).startswith("ERROR: unknown tool")


def test_declared_knowledge_tools_dispatch():
    """Declaradas despacham (não 'unknown tool') mesmo sem args."""
    for n in ("jarvis_rag_search", "jarvis_recall", "jarvis_lessons"):
        out = call_tool(n, {"query": "", "top_k": 1})
        assert "unknown tool" not in out


def test_mutation_policy_deny(monkeypatch, tmp_path):
    """JARVIS_MCP_MUTATION=deny bloqueia write/str_replace (paridade Agent)."""
    import os
    from jarvis.mcp_server import call_tool
    monkeypatch.setenv("JARVIS_MCP_MUTATION", "deny")
    out = call_tool("jarvis_write_file",
                    {"path": str(tmp_path / "x.txt"), "content": "x"})
    assert out.startswith("ERROR:") and "approval" in out
    assert not (tmp_path / "x.txt").exists()


def test_mutation_policy_auto_default(monkeypatch, tmp_path):
    """Default auto: escreve no jail (comportamento preservado)."""
    import os
    from jarvis.mcp_server import call_tool
    monkeypatch.delenv("JARVIS_MCP_MUTATION", raising=False)
    out = call_tool("jarvis_write_file",
                    {"path": str(tmp_path / "y.txt"), "content": "y"})
    assert not out.startswith("ERROR: unknown tool")
