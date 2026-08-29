# 📚 nixos-ai Documentation

> **Last updated:** 2026-08-29
> **Status:** Active development

## 🏗️ Architecture Overview

```mermaid
architecture-beta
    group system(cloud)[NixOS System]

    group ai(cloud)[AI Stack] in system
        service jarvis(server)[JARVIS Agent]
        service llama(server)[llama.cpp Server]
        service qdrant(database)[Qdrant Vector DB]
        service embeddings(server)[Embeddings Server]

    group ide(cloud)[IDE Integration] in system
        service roo(code)[Roo Dev]
        service vscodium(code)[VSCodium]
        service mcp(server)[MCP Servers]

    group desktop(cloud)[Desktop] in system
        service hyprland(server)[Hyprland WM]
        service waybar(code)[Waybar]
        service rofi(code)[Rofi Launcher]

    jarvis:B --> T:llama
    jarvis:B --> T:qdrant
    jarvis:B --> T:embeddings
    roo:B --> T:mcp
    mcp:B --> T:jarvis
    jarvis:B --> T:hyprland
    waybar:B --> T:jarvis
```

## 📁 Documentation Structure

```
docs/
├── README.md                    # This file — docs index
├── architecture/                # System architecture
│   ├── system-overview.md       # High-level architecture
│   ├── agent-harness.md         # JARVIS agent design
│   ├── mcp-integration.md       # MCP server integration
│   └── context-engineering.md   # Context management
├── benchmarks/                  # Performance benchmarks
│   ├── README.md                # Benchmark methodology
│   ├── results/                 # Raw benchmark data
│   └── performance-evidence.md  # Evidence audit
├── development/                 # Developer guides
│   ├── getting-started.md       # Quick start
│   ├── repl-guide.md            # REPL usage
│   └── testing.md               # Test suite
└── archive/                     # Historical documents
    └── ...                      # Old docs moved here
```

## 🎯 Quick Navigation

| Topic | Document | Status |
|-------|----------|--------|
| **System Architecture** | [architecture/system-overview.md](architecture/system-overview.md) | ✅ Current |
| **Agent Harness** | [architecture/agent-harness.md](architecture/agent-harness.md) | ✅ Current |
| **MCP Integration** | [architecture/mcp-integration.md](architecture/mcp-integration.md) | ✅ Current |
| **Context Engineering** | [architecture/context-engineering.md](architecture/context-engineering.md) | ✅ Current |
| **Benchmark Methodology** | [benchmarks/README.md](benchmarks/README.md) | ✅ Current |
| **REPL Guide** | [development/repl-guide.md](development/repl-guide.md) | ✅ Current |
| **Getting Started** | [development/getting-started.md](development/getting-started.md) | ✅ Current |

## 📊 System Status

| Component | Status | Details |
|-----------|--------|---------|
| JARVIS Agent | ✅ Running | 20 MCP tools, REPL with 5 modes |
| llama.cpp | ✅ Running | Qwen3.6-35B-A3B, RTX 4050 |
| Qdrant | ✅ Running | 1143 code chunks indexed |
| Roo Dev | ✅ Running | Connected to local LLM |
| Telegram Bot | ✅ Running | @jarvis_lab_bot |
| Waybar | ✅ Running | Agent status indicator |

## 🔗 External Resources

- [AGENTS.md Spec](https://github.com/lnx-agents/AGENTS.md) — Linux Foundation standard
- [MCP Protocol](https://modelcontextprotocol.io/) — Model Context Protocol
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — Local LLM inference
- [Roo Code](https://roocode.com/) — AI coding assistant

## 📝 Contributing

See [AGENTS.md](../AGENTS.md) for project rules and conventions.
