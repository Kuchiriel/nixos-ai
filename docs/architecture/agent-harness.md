# 🤖 Agent Harness Architecture

> JARVIS agent design, tools, and execution loop.

## Agent Loop

```mermaid
flowchart TB
    Start["User Input"] --> Parse{"Parse"}
    Parse -->|Slash Command| Cmd["Execute Command"]
    Parse -->|Normal Input| LLM["Call LLM"]
    
    LLM --> Response{"Response"}
    Response -->|Text Only| Output["Display Response"]
    Response -->|Tool Calls| Tools["Execute Tools"]
    
    Tools --> Validate{"Validate"}
    Validate -->|Success| Result["Tool Result"]
    Validate -->|Error| Recover["Recovery"]
    
    Result --> LLM
    Recover --> LLM
    
    Cmd --> Output
    Output --> Done["End Turn"]
    
    style Start fill:#e3f2fd
    style LLM fill:#e8f5e9
    style Tools fill:#fff3e0
    style Done fill:#fce4ec
```

## Tool Categories

```mermaid
flowchart LR
    subgraph Core["Core Tools"]
        Read["read_file"]
        Write["write_file"]
        Replace["str_replace"]
        Shell["execute_shell"]
        List["list_directory"]
        Search["semantic_search"]
    end

    subgraph Vision["Vision Tools"]
        Capture["capture_screen"]
        Observe["observe_screen"]
    end

    subgraph NixOS["NixOS Tools"]
        Eval["nix_eval"]
        Check["nix_check"]
        NixSearch["nix_search"]
    end

    subgraph Memory["Memory Tools"]
        Remember["remember"]
        Recall["recall"]
        Lessons["lessons"]
        VaultList["vault_list"]
        VaultWrite["vault_write"]
    end

    subgraph RAG["RAG Tools"]
        RAGSearch["rag_search"]
        RAGIndex["rag_index"]
    end

    subgraph Web["Web Tools"]
        ChatGPT["read_chatgpt"]
    end

    style Core fill:#e3f2fd
    style Vision fill:#e8f5e9
    style NixOS fill:#fff3e0
    style Memory fill:#f3e5f5
    style RAG fill:#fce4ec
    style Web fill:#e0f2f1
```

## Security Layers

```mermaid
flowchart TB
    Input["User/LLM Input"] --> L1["Layer 1: Command Allowlist"]
    L1 -->|Blocked| Deny1["❌ Deny"]
    L1 -->|Allowed| L2["Layer 2: Chaining Detection"]
    L2 -->|Dangerous| Deny2["❌ Deny"]
    L2 -->|Safe| L3["Layer 3: Pipe Validation"]
    L3 -->|Unsafe Pipe| Deny3["❌ Deny"]
    L3 -->|Safe| L4["Layer 4: shlex.split()"]
    L4 --> L5["Layer 5: subprocess.run()"]
    L5 --> Output["Command Output"]

    style L1 fill:#ffcdd2
    style L2 fill:#ffcdd2
    style L3 fill:#ffcdd2
    style L4 fill:#c8e6c9
    style L5 fill:#c8e6c9
    style Deny1 fill:#f44336
    style Deny2 fill:#f44336
    style Deny3 fill:#f44336
```

## Custom Modes

```mermaid
flowchart TB
    subgraph Modes["jarvismodes"]
        Code["code — Editar código"]
        Arch["architect — Projetar sistemas"]
        Night["nightwatch — Loop autônomo"]
        Org["organizer — Organizar arquivos"]
        Res["research — Pesquisa web"]
    end

    subgraph Switching["Mode Switching"]
        slash["/modes — list modes"]
        switch["/mode <slug> — switch"]
    end

    slash --> Modes
    switch --> Modes

    style Modes fill:#e8f5e9
    style Switching fill:#fff3e0
```

## Context Management

```mermaid
flowchart TB
    subgraph Turn["Context por turno (contexto real do servidor)"]
        Server["context_size consultado do llama-server
(_query_server_context_size — nunca assumir)"]
        Compact["auto-compact em 70%"]
        Target["alvo da compactação: 50%"]
    end

    subgraph Shift["Context shift (REPL nunca para)"]
        Sliding["janela deslizante:
compactação preserva system+recente,
derruba o meio antigo"]
        Budget["LLM Budget/overflow honesto (agent.py)"]
    end

    Turn --> Shift
    style Server fill:#e3f2fd
    style Compact fill:#fff3e0
    style Sliding fill:#e8f5e9
```

- O REPL **não para**: contexto estourando → auto-compact (70% → 50%)
  e segue o turno. Sem "contexto cheio, recomece".
- `context_size` vem DO SERVIDOR por turno (não hardcoded por modelo).

## Turn Hooks (fim de turno — o que desconfia antes de aceitar)

Ordem em `_run_agent_loop` (dev.py), todas bounded (contadores no loop):

1. **Promise-catcher (F1)**: "vou criar…" sem tool call → nudge com a
   tool anunciada + formato exato (máx 2×).
2. **Claim-checker (§11)**: declarou que escreveu X sem write_file de X
   na sessão → correção factual (máx 1×).
3. **Reopen-on-UNVERIFIED (25/09)**: com tool activity, `check_completion`
  (completion.py) verifica o MUNDO estruturalmente — arquivos escritos
   existem, .py compila, **instrução lida dentro de arquivo foi executada**
   (check `_unexecuted_read_instructions`). Missing de classe artefato →
   1 reopen com a lista (mesmo feedback que salva 5/12 no harness).
   Trailing-error sozinho NÃO reabre ("por que falhou?" é diagnóstico).
4. LoopDetector: repetição idêntica ×3 → abort honesto (STUCK ≠ done).

---
**Ver também:** [[nightwatch-components|nightwatch-components.md]] | [[mission-consolidation|mission-consolidation.md]]
[[mcp-integration|mcp-integration.md]] | [[context-engineering|context-engineering.md]] | [[ADR-001-agent-platform|ADR-001-agent-platform.md]]
[[ADR-002-memory-layers|ADR-002-memory-layers.md]] | [[system-overview|system-overview.md]]
[[../../HANDOFF|/home/nixos/projects/nixos-ai/AGENTS.md]] | [[../../AGENTS.md|/home/nixos/projects/nixos-ai/AGENTS.md]] | [[../../README|/home/nixos/projects/nixos-ai/docs/README.md]]
