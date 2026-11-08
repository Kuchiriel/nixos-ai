# Inventariar MCPs do sistema (@general subagent)

- **sessão:** `ses_ee94c670effeIk3CyeY5dKf3aD`
- **quando:** 2026-10-07 14:10 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

READ-ONLY. Em /home/nixos/projects: (1) liste todos os servidores MCP configurados — nixos-ai (mcp_server.py? jarvis-mcp-launcher.sh, home.nix MCPs), opencode.json mcp section, .opencode ou skills que expõem tools; (2) para cada um: nome, transporte, o que expõe (tools/resources), quem consome (jarvis CLI? opencode? qual agente?), e se está ATIVO ou morto; (3) identifique MCPs que existem mas nenhum agente sabe usar (sem referência em AGENTS.md, prompts ou playbooks). Devolva tabela + proposta de catálogo único (onde publicar para agentes lerem automaticamente). Terse.

---

## · ?

Mapeando MCPs — catalogando servidores, transportes e consumidores.

---

## · ?

Achados iniciais em mãos — agora vasculhando configs e launchers.

---

## · ?

Núcleo JARVIS mapeado — agora checando os MCPs periféricos.

---

## · ?

Quase fechando o inventário — verificando órfãos e pontos cegos.

---

## · ?

Em `/home/nixos/projects` — só `nixos-ai` configura MCP. `opencode.json` raiz **não tem seção `mcp`** (só `provider/local*`). `.roo/mcp.json` = `{"mcpServers":{}}` vazio (morto, cf. `docs/audits/ENTROPY.md`). `.opencode/agent/` só tem `suite-runner.md` (sem MCP). Skills: nenhuma expõe MCP.

| # | Servidor (onde declarado) | Transporte | Expõe | Quem consome | Estado |
|---|---|---|---|---|---|
| 1 | `jarvis` = `mcp_server.py` via `jarvis-mcp-launcher.sh` — duplamente declarado: `nixos-ai/home-manager/modules/vscode-roo.nix:101` (Roo) + `nixos-ai/home-manager/home.nix:582` (opencode `mcp.jarvis`, `type=local`, `timeout 180s`) | stdio JSON-RPC 2.0 (`python -m jarvis.mcp_server`) | 25 em `JARVIS_TOOLS` público (`execute/read_file/write_file/str_replace/capture+observe_screen/human_input/browser/nix_{eval,check,search}/read_chatgpt/remember/recall/lessons/vault_{list,write}/rag_{search,index}/persona/web_search/vault_{sync_obsidian,sync_hackmd,search_obsidian,status}`) + ocultos em `call_tool()` (`hackmd_*×4`, `make_*×4`, `read_ai_conversation`) | Roo (alwaysAllow 18), opencode, `jarvis-cli.sh` (import direto `call_tool`, sem stdio), WebUI bridge | **ATIVO** — único com launcher, `alwaysAllow`, testes `test_mcp*.py` |
| 2 | `nixos-mcp` (`vscode-roo.nix:89`, `flake.nix:65 mcp-nixos-fast` + `patches/mcp-nixos-channel-cache.patch`, `package.nix:70`) | stdio (`mcp-nixos`, `MCP_NIXOS_CHANNEL_CACHE`) | 2 tools read-only: `nix`, `nix_versions` | Roo direto + JARVIS interno via `providers/mcp.py:MCPClient` (`handle_nixos`, proxy `jarvis_nix_search`) | **ATIVO** |
| 3 | `tavily-search` (`vscode-roo.nix:48`, `npx -y tavily-mcp@latest`, key de `/etc/jarvis-secrets/tavily.env`) | stdio | `tavily_search`, `tavily_extract` | Só Roo (`.roomodes`, `.roo/rules-nightwatch`) | **ATIVO p/ Roo; morto p/ opencode/jarvis-CLI** (`home.nix` opencode não declara) |
| 4 | `context7` (`vscode-roo.nix:59`, `npx -y @upstash/context7-mcp@latest`) | stdio | `resolve-library-id`, `get-library-docs` | Só Roo | **ATIVO p/ Roo; morto p/ opencode** |
| 5 | `playwright` (`vscode-roo.nix:70`, `pkgs.playwright-mcp`) | stdio | browser automation | Só Roo | **ATIVO p/ Roo; removido do opencode de propósito** (`home.nix:617` — redundante c/ `jarvis_browser`) |
| 6 | `github` (`vscode-roo.nix:78`, `github-mcp-server`) | stdio | repo ops | ninguém (`disabled = githubToken==""` default) | **MORTO** (desabilitado) |
| 7 | WebUI bridge (`modules/ai/jarvis/src/jarvis/webui/api.py:203 GET /api/mcp/tools, POST /api/mcp/call`) | HTTP REST+SSE (não-MCP, ponte) | re-expõe `JARVIS_TOOLS` c/ `write` gate + `approve` | nenhum cliente documentado (só `test_webui_mcp_bridge.py`) | **ATIVO sem consumidor** |
| 8 | `llama-server --mcp` (`llama.cpp/tools/server/server-mcp.{cpp,h}` + forks `ik_/wackmall/prism-`) | stdio (C++, upstream) | agregador genérico MCP do llama.cpp | ninguém no JARVIS | **MORTO** (só fixtures/testes upstream) |
| 9 | Legado `AI_SYSTEM/tools/test-mcp-tools.sh` (ollama-claude `~/.local/share/ollama-claude/index.js` + `claude_desktop_config.json`) | stdio node | `mcp__ollama_*` | ninguém | **MORTO** (reference-only) |

Órfãos (existem, nenhum agente sabe usar — sem ref em `AGENTS.md` raiz, `nixos-ai/AGENTS.md`, prompts):
`github` (só em `vscode-roo.nix`); `context7`/`tavily-search` p/ opencode (só `.roomodes`/`.roo/rules-*`, ausentes dos dois AGENTS.md centrais); bridge `/api/mcp` (só teste); `llama-server MCP`; tools práticas órfãs: `jarvis_make_*`, `jarvis_hackmd_*`, `jarvis_read_ai_conversation`, `jarvis_persona`, `jarvis_vault_sync_*` — chamáveis, fora do `alwaysAllow` e fora de qualquer playbook. Doc `mcp-integration.md:22 tools` desatualizada (código tem 25+ocultas; `README.md:33 tools` também diverge).

Proposta catálogo único (1 fonte, leitura automática):
1. `nixos-ai/modules/ai/mcp-servers.nix` — única fonte Nix, importada por `vscode-roo.nix` E `home.nix` (opencode). Hoje divergem à mão.
2. `nixos-ai/.agents/mcp-catalog.md` — tabela acima + quando-usar (gatilhos: `mcp,tavily,context7,browser,nix,vault,rag`) — auto-carregado pela regra `Regras de agentes (gatilho→arquivo)` do `nixos-ai/AGENTS.md`.
3. Linha no índice dos dois `AGENTS.md` (raiz + nixos-ai) apontando p/ (2); `roo-nightwatch-setup.sh` estender check aos 6 servers.

---

