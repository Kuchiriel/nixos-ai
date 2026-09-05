# 📚 nixos-ai Documentation

> **Last updated:** 2026-09-05
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
├── README.md                         # Este arquivo — índice da documentação
├── architecture/                     # Documentação técnica viva (fonte de verdade)
│   ├── system-overview.md            # Arquitetura geral + topologia de serviços
│   ├── mcp-integration.md            # MCP servers: tools, segurança, config
│   ├── agent-harness.md              # Design do harness (nightwatch core)
│   ├── context-engineering.md        # Protocolo de contexto: 4 pilares
│   ├── rag-improvements.md           # RAG: híbrido, chunking, reranker
│   ├── llama-cpp-tuning.md           # Tuning do llama.cpp (ncmoe, flags)
│   ├── slm-techniques.md             # Técnicas SLM aplicadas
│   ├── pillar-diagnostic.md          # Diagnóstico dos 4 pilares
│   ├── ADR-001-agent-platform.md     # ADR: Plataforma de agentes
│   ├── ADR-002-memory-layers.md      # ADR: Camadas de memória
│   ├── jarvis-comparison.md          # MCU vs NixOS JARVIS (análise de paridade)
│   ├── nightwatch-components.md      # Componentes Nightwatch + validação long-run
│   ├── mission-consolidation.md      # Missão: eliminar entropia, unificar pipeline
│   ├── monorepo-schema.md            # Schema de monorepo e prompts de refatoração
│   └── platform-assessment.md        # Avaliação completa da plataforma
├── benchmarks/                       # Evidências de performance
│   ├── README.md                     # Metodologia + índice de resultados
│   ├── ncmoe-sweep.md                # Sweep de --n-cpu-moe
│   ├── performance-evidence-audit.md # Auditoria de evidências
│   ├── gpu-moe-fix-2026-08-28.md     # Fix de GPU MoE
│   └── results/                      # Raw data (subdirs por sessão)
├── audit/                            # Auditorias do sistema
│   ├── INDEX.md                      # Índice cronológico de todas as auditorias
│   ├── current/                      # Auditorias com itens ainda abertos
│   ├── completed/                    # Auditorias completamente resolvidas
│   └── legacy/                       # Inventário do sistema legado
├── development/                      # Guias práticos
│   ├── getting-started.md            # Quick start
│   ├── repl-guide.md                 # Guia do REPL (jarvis dev)
│   ├── testing.md                    # Suíte de testes e convenções
│   ├── env-vars-reference.md         # Variáveis de ambiente
│   └── repl-improvements-backlog.md  # Backlog de melhorias do REPL
└── archive/                          # Documentação histórica (não editar)
    ├── README.md                     # Critério de arquivamento + inventário
    ├── benchmarks/                   # Benchmarks históricos (pré-Qwen3.6)
    ├── diagnostics/                  # Diagnósticos resolvidos
    ├── legacy-components/            # Arquitetura legada substituída
    ├── research/                     # Pesquisa que informou decisões
    └── _trash/                       # NÃO indexar no RAG
```

## 🎯 Quick Navigation

| Tópico | Documento | Status |
|--------|-----------|--------|
| **Arquitetura geral** | [architecture/system-overview.md](architecture/system-overview.md) | ✅ Atual |
| **MCPs e ferramentas** | [architecture/mcp-integration.md](architecture/mcp-integration.md) | ✅ Atual |
| **Harness (Nightwatch)** | [architecture/agent-harness.md](architecture/agent-harness.md) | ✅ Atual |
| **Engenharia de contexto** | [architecture/context-engineering.md](architecture/context-engineering.md) | ✅ Atual |
| **RAG e memória** | [architecture/rag-improvements.md](architecture/rag-improvements.md) | ✅ Atual |
| **Camadas de memória** | [architecture/ADR-002-memory-layers.md](architecture/ADR-002-memory-layers.md) | ✅ Atual |
| **Decisão de plataforma** | [architecture/ADR-001-agent-platform.md](architecture/ADR-001-agent-platform.md) | ✅ Atual |
| **Benchmarks** | [benchmarks/README.md](benchmarks/README.md) | ✅ Atual |
| **Auditorias ativas** | [audit/INDEX.md](audit/INDEX.md) | ✅ Atual |
| **Quick start** | [development/getting-started.md](development/getting-started.md) | ✅ Atual |
| **Guia de testes** | [development/testing.md](development/testing.md) | ✅ Atual |
| **REPL** | [development/repl-guide.md](development/repl-guide.md) | ✅ Atual |

## 📊 System Status

> ⚠️ Este status é HISTORICAL (2026-09-03). Verificar serviços com `jarvis status`.

| Componente | Status | Detalhes |
|-----------|--------|----------|
| JARVIS Agent | ✅ Running | 18 MCP tools, REPL com modos customizáveis |
| llama.cpp | ✅ Running | Qwen3.6-35B-A3B Q4_K_M, RTX 4050 6GB |
| Qdrant | ✅ Running | 1143 code chunks indexados |
| Embeddings | ✅ Running | nomic-embed-text-v2-moe :8081 |
| Reranker | ✅ Running | bge-reranker-v2-m3 :8082 |
| Roo Dev | ✅ Running | Conectado ao LLM local |
| Telegram Bot | ✅ Running | @jarvis_lab_bot |
| Waybar | ✅ Running | Indicador de status do agente |
| Testes | ✅ 859/859 | 0 failures, 26 skipped, 5 xpassed |

## 🔗 External Resources

- [AGENTS.md Spec](https://github.com/lnx-agents/AGENTS.md) — Linux Foundation standard
- [MCP Protocol](https://modelcontextprotocol.io/) — Model Context Protocol
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — Local LLM inference
- [Roo Code](https://roocode.com/) — AI coding assistant
- [Qdrant](https://qdrant.tech/) — Vector database

## 📝 Contributing

Ver [AGENTS.md](../AGENTS.md) para regras do projeto e convenções.
Ver [BUFFY.md](../../BUFFY.md) para protocolo de qualidade e evidência.
