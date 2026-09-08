"""Unit tests da busca Obsidian do MCP (path configurável, erro observável)."""

from __future__ import annotations


class TestObsidianVaultSearch:
    def test_missing_vault_is_observable_error(self, tmp_path, monkeypatch):
        from jarvis import mcp_server as M
        monkeypatch.setenv("JARVIS_OBSIDIAN_VAULT", str(tmp_path / "nope"))
        out = M._vault_read_from_obsidian("q")
        assert len(out) == 1 and "error" in out[0]

    def test_search_uses_configured_vault_fixed_string(self, tmp_path, monkeypatch):
        from jarvis import mcp_server as M
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "nota.md").write_text("conteudo com (parenteses) + especiais")
        monkeypatch.setenv("JARVIS_OBSIDIAN_VAULT", str(vault))
        out = M._vault_read_from_obsidian("conteudo com (parenteses)")
        # -F: query tratada como literal (regex quebraria e voltava []).
        assert any(r.get("name") == "nota" for r in out)
