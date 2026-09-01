# 🏗️ System Architecture

> High-level overview of the nixos-ai system.

## System Diagram

```mermaid
flowchart TB
    subgraph User["👤 User Interface"]
        Rofi["Rofi Launcher"]
        Waybar["Waybar Status"]
        Terminal["Terminal (foot)"]
        Telegram["Telegram Bot"]
    end

    subgraph IDE["💻 IDE Layer"]
        VSCodium["VSCodium"]
        RooDev["Roo Dev Extension"]
    end

    subgraph MCP["🔌 MCP Servers"]
        JarvisMCP["jarvis (17 tools)"]
        Context7["context7"]
        Tavily["tavily-search"]
        NixOS["nixos-mcp"]
        Playwright["playwright"]
    end

    subgraph Agent["🤖 Agent Layer"]
        JARVIS["JARVIS Agent"]
        REPL["jarvis dev (REPL)"]
        DevTools["devtools.py"]
        Memory["Episodic Memory"]
        Vault["Persistent Vault"]
        RAG["RAG (Qdrant)"]
    end

    subgraph Runtime["⚡ Runtime"]
        LLaMA["llama.cpp Server"]
        Qdrant["Qdrant Vector DB"]
        Embed["Embeddings Server"]
        Rerank["Rerank Server"]
    end

    subgraph Hardware["🖥️ Hardware"]
        GPU["RTX 4050 6GB"]
        CPU["i7-13620H"]
        RAM["32GB DDR5"]
        SSD["NVMe Gen4"]
    end

    User --> IDE
    User --> Terminal
    User --> Telegram
    IDE --> RooDev
    RooDev --> MCP
    Terminal --> REPL
    REPL --> JARVIS
    JARVIS --> DevTools
    JARVIS --> Memory
    JARVIS --> Vault
    JARVIS --> RAG
    MCP --> JARVIS
    JARVIS --> LLaMA
    RAG --> Qdrant
    RAG --> Embed
    LLaMA --> GPU
    LLaMA --> CPU
    Qdrant --> RAM
    Embed --> GPU

    style User fill:#e1f5fe
    style IDE fill:#f3e5f5
    style MCP fill:#fff3e0
    style Agent fill:#e8f5e9
    style Runtime fill:#fce4ec
    style Hardware fill:#f5f5f5
```

## Data Flow

```mermaid
sequenceDiagram
    participant U as User
    participant R as REPL/Roo Dev
    participant J as JARVIS
    participant L as llama.cpp
    participant Q as Qdrant

    U->>R: "Analise este código"
    R->>J: Tool call (read_file)
    J->>J: devtools.read_file()
    J-->>R: File content
    R->>J: Tool call (semantic_search)
    J->>Q: Hybrid search
    Q-->>J: Related code snippets
    J-->>R: Search results
    R->>J: Tool call (execute_shell)
    J->>J: command_allowed() check
    J->>J: shlex.split() + run
    J-->>R: Command output
    R->>L: Chat completion
    L-->>R: Response + tool_calls
    R-->>U: "Encontrei o bug na linha 42..."
```

## NixOS Configuration Layers

```mermaid
flowchart LR
    subgraph Flake["flake.nix"]
        Inputs["inputs (nixpkgs, home-manager)"]
        Overlays["overlays (aiModels, jarvis)"]
        Packages["packages (jarvis, jarvis-voice)"]
    end

    subgraph NixOS["NixOS Modules"]
        Config["configuration.nix"]
        Services["modules/services/"]
        System["modules/system/"]
        AI["modules/ai/"]
    end

    subgraph Home["Home Manager"]
        HM["home-manager/"]
        Waybar["waybar.nix"]
        Hyprland["hyprland/"]
        Rofi["rofi.nix"]
        AgentsMD["agents-md.nix"]
        JarvisModes["jarvismodes.nix"]
    end

    Inputs --> Config
    Overlays --> Packages
    Config --> Services
    Config --> System
    Config --> AI
    Config --> HM
    HM --> Waybar
    HM --> Hyprland
    HM --> Rofi
    HM --> AgentsMD
    HM --> JarvisModes

    style Flake fill:#e3f2fd
    style NixOS fill:#e8f5e9
    style Home fill:#fff3e0
```

## Service Topology

```mermaid
flowchart TB
    MUI["multi-user.target"]
    JT["jarvis.target"]

    subgraph Infra["Infrastructure"]
        Qdrant["qdrant.service"]
        LLaMA["llama-cpp-server.service"]
        Embed["llama-cpp-embeddings.service"]
    end

    subgraph Consumers["Consumers"]
        Voice["jarvis-voice.service"]
        TG["jarvis-telegram.service"]
        Heal["jarvis-heal.service"]
        Gaming["jarvis-gaming-watcher.service"]
        Fan["llama-fan-control.service"]
    end

    MUI --> JT
    JT --> Qdrant
    JT --> LLaMA
    JT --> Embed
    JT --> Voice
    JT --> TG
    JT --> Heal
    JT --> Gaming
    JT --> Fan

    style MUI fill:#e3f2fd
    style JT fill:#e8f5e9
    style Infra fill:#fff3e0
    style Consumers fill:#fce4ec
```

---
**Ver também:** [[../../HANDOFF]] | [[../../AGENTS.md]] | [[../../README]]
