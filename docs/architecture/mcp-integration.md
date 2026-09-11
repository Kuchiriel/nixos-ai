# 🔌 MCP Integration

> Model Context Protocol servers and their integration with Roo Dev.

## MCP Server Architecture

```mermaid
flowchart TB
    subgraph Clients["MCP Clients"]
        RooDev["Roo Dev (VSCodium)"]
        REPL["jarvis dev (REPL)"]
        FutureCLI["Future CLI tools"]
    end

    subgraph Servers["MCP Servers"]
        Jarvis["jarvis-mcp (22 tools declarados)"]
        Context7["context7"]
        Tavily["tavily-search"]
        NixOS["nixos-mcp"]
        Playwright["playwright"]
    end

    subgraph JarvisTools["JARVIS Tools (REPL + MCP)"]
        Exec["execute_shell / jarvis_execute"]
        FileOps["read/write/str_replace + jarvis_*"]
        Vision["capture/observe_screen + jarvis_*"]
        NixTools["nix_eval/check/search + jarvis_*"]
        MemTools["remember/recall/lessons + jarvis_*"]
        VaultTools["vault_list/write + jarvis_*"]
        RAGTools["rag_search/index + jarvis_*"]
        WebTools["web_search + jarvis_web_search"]
        ChatTools["read_chatgpt/read_ai_conversation + jarvis_*"]
    end

    RooDev --> Jarvis
    RooDev --> Context7
    RooDev --> Tavily
    RooDev --> NixOS
    RooDev --> Playwright
    REPL --> Jarvis
    FutureCLI --> Jarvis

    Jarvis --> JarvisTools

    style Clients fill:#e3f2fd
    style Servers fill:#fff3e0
    style JarvisTools fill:#e8f5e9
```

## Tool Mapping: REPL vs MCP

| Tool | REPL | MCP | Notes |
|------|------|-----|-------|
| read_file | ✅ | ✅ jarvis_read_file | Same implementation |
| write_file | ✅ | ✅ jarvis_write_file | Same implementation |
| str_replace | ✅ | ✅ jarvis_str_replace | Same implementation |
| execute_shell | ✅ | ✅ jarvis_execute | Both use shlex |
| list_directory | ✅ | ❌ | REPL only |
| semantic_search | ✅ | ❌ | REPL only |
| capture_screen | ✅ | ✅ jarvis_capture_screen | Same implementation |
| observe_screen | ✅ | ✅ jarvis_observe_screen | Same implementation |
| nix_eval | ✅ | ✅ jarvis_nix_eval | Same implementation |
| nix_check | ✅ | ✅ jarvis_nix_check | Same implementation |
| nix_search | ✅ | ✅ jarvis_nix_search | MCP proxies mcp-nixos |
| remember | ✅ | ✅ jarvis_remember | Same implementation |
| recall | ✅ | ✅ jarvis_recall | Same implementation |
| lessons | ✅ | ✅ jarvis_lessons | Same implementation |
| vault_list | ✅ | ✅ jarvis_vault_list | Same implementation |
| vault_write | ✅ | ✅ jarvis_vault_write | Same implementation |
| rag_search | ✅ | ✅ jarvis_rag_search | Same implementation |
| rag_index | ✅ | ✅ jarvis_rag_index | Same implementation |
| read_chatgpt | ✅ | ✅ jarvis_read_chatgpt | Same implementation |
| read_ai_conversation | ✅ | ✅ jarvis_read_ai_conversation | Same implementation |
| web_search | ✅ | ✅ jarvis_web_search | Same implementation |

**Observação sobre escopo da contagem**: `jarvis-mcp` lista publicamente 22 ferramentas via `tools/list` (array `JARVIS_TOOLS` em `mcp_server.py`). Diferente do REPL, o MCP também declara ferramentas de sincronização de vault (`jarvis_vault_sync_obsidian`, `jarvis_vault_sync_hackmd`, `jarvis_vault_search_obsidian`, `jarvis_vault_status`) e ferramentas extras não expandidas na matriz de capability do persona (`jarvis_proactive_check`, `jarvis_system_health`, `jarvis_classify_file`, `jarvis_classify_directory`) em `call_tool()`, mas estas últimas não são listadas no schema público de ferramentas do usuário.

## MCP Configuration (VSCodium)

```json
{
  "mcpServers": {
    "jarvis": {
      "command": "nix-shell",
      "args": ["-p", "python3", "--run", "python3 -m jarvis.mcp_server"],
      "env": {}
    },
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    },
    "tavily-search": {
      "command": "nix-shell",
      "args": ["-p", "python3", "--run", "python3 -m tavily_mcp"],
      "env": { "TAVILY_API_KEY": "..." }
    },
    "nixos-mcp": {
      "command": "nix-shell",
      "args": ["-p", "mcp-nixos", "--run", "mcp-nixos"]
    },
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp"]
    }
  }
}
```

## Security Model

```mermaid
flowchart TB
    Input["(LLM ou usuário)"] --> L1["L1: Command Allowlist"]

    L1 -->|blocked| Deny1["❌ deny"]
    L1 -->|allowed| L2["L2: Chaining / dangerous patterns"]

    L2 -->|dangerous| Deny2["❌ deny"]
    L2 -->|safe| L3["L3: Pipe + validator allowlist"]

    L3 -->|unsafe pipe| Deny3["❌ deny"]
    L3 -->|safe pipe| L4["L4: shlex.split + run_shell"]

    L4 --> Out["command output"]

    style L1 fill:#ffcdd2
    style L2 fill:#ffcdd2
    style L3 fill:#ffcdd2
    style L4 fill:#c8e6c9
    style Deny1 fill:#f44336
    style Deny2 fill:#f44336
    style Deny3 fill:#f44336
```

---
**Ver também:** [[system-overview]] | [[agent-harness]] | [[rag-improvements]]
[[context-engineering]] | [[ADR-001-agent-platform]]
[[../../HANDOFF]] | [[../../AGENTS.md]] | [[../../README]]

---
**Nota de validação**: contagem de ferramentas e o diagrama de segurança foram alinhados ao código-fonte (`mcp_server.py`, `devtools.py`, `persona.py`) em 2026-09-09. Números exatos de ferramentas em execução por persona, estado de sincronização de vault e lista de comandos allowlist efetiva precisam de validação por teste/observação em runtime — não são garantidos apenas pela leitura estática.
