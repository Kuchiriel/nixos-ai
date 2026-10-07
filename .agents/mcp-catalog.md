# MCP catalog — quem expõe o quê, quem usa

> Fonte: inventário 07/10 (ver memória). Atualizar quando adicionar/remove server.

| Server | Onde declarado | Expõe | Quem usa | Estado |
|---|---|---|---|---|
| jarvis (`mcp_server.py`) | `home.nix:582` (opencode) + `vscode-roo.nix:101` (Roo) | 25 tools: arquivos, shell, nix, rag, vault, persona, web, browser | opencode, Roo, jarvis-cli | ATIVO |
| nixos-mcp | `vscode-roo.nix:89` | `nix`, `nix_versions` (read-only) | Roo + JARVIS (`jarvis_nix_search`) | ATIVO |
| tavily-search | `vscode-roo.nix:48` | `tavily_search`, `tavily_extract` | só Roo | morto p/ opencode |
| context7 | `vscode-roo.nix:59` | docs de libs | só Roo | morto p/ opencode |
| playwright | `vscode-roo.nix:70` | automação browser | só Roo (removido do opencode de propósito — redundante c/ jarvis_browser) | — |
| github | `vscode-roo.nix:78` | repo ops | ninguém (disabled sem token) | MORTO |
| WebUI bridge | `webui/api.py` (`/api/mcp/*`) | re-expõe JARVIS_TOOLS via HTTP | nenhum cliente | sem consumidor |

Gatilhos: mcp, tavily, context7, browser, nix search, vault, rag, github.
