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
        Jarvis["jarvis-mcp (17 tools)"]
        Context7["context7"]
        Tavily["tavily-search"]
        NixOS["nixos-mcp"]
        Playwright["playwright"]
    end

    subgraph JarvisTools["JARVIS Tools"]
        Exec["execute_shell"]
        FileOps["read/write/str_replace"]
        Vision["capture/observe_screen"]
        NixTools["nix_eval/check/search"]
        MemTools["remember/recall/lessons"]
        VaultTools["vault_list/write"]
        RAGTools["rag_search/index"]
        ChatGPT["read_chatgpt"]
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
    subgraph Allowlist["Command Allowlist"]
        Safe["ls, cat, head, tail, grep, find, wc, df, free, ps, git, nix, curl, nvidia-smi"]
    end

    subgraph PipeValidation["Pipe Validation"]
        SafePipe["head, tail, grep, wc, sort, uniq, cut, awk, sed, tr, column, jq"]
    end

    subgraph Blocked["Blocked Patterns"]
        Dangerous["&&, ||, $(), rm, mv, cp, chmod, chown, dd, mkfs"]
    end

    subgraph Approval["Approval Required"]
        WriteCmds["Commands not in allowlist"]
    end

    Allowlist -->|Pass| PipeValidation
    PipeValidation -->|Pass| Execute["Execute via shlex"]
    Blocked -->|Found| Deny["❌ Deny"]
    WriteCmds -->|Ask| User["User Approval"]

    style Allowlist fill:#c8e6c9
    style PipeValidation fill:#c8e6c9
    style Blocked fill:#ffcdd2
    style Approval fill:#fff9c4
```
