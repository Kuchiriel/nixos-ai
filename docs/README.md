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

> Renderização: esse diagrama usa a sintaxe `architecture-beta` do Mermaid. Em alguns editores/Render engines ainda não é suportada de forma estável; se não renderizar, o mesmo sistema está descrito nos diagramas `flowchart` de `architecture/system-overview.md` e `architecture/mcp-integration.md`.

## 📁 Documentation Structure

> Entrypoints: cada diretório tem `INDEX.md` com wikilinks; mapas de
> primeira leitura: [[architecture/SYSTEM-MAP|architecture/SYSTEM-MAP.md]] (sistema) e o tree abaixo.

```
docs/
├── README.md                         # Este arquivo — índice da documentação
├── architecture/                     # Documentação técnica viva (fonte de verdade)
│   ├── INDEX.md                      # Índice do diretório (wikilinks coerentes)
│   ├── SYSTEM-MAP.md                 # 🗺️ Mapa de primeira leitura (repos + camadas + código)
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
│   ├── platform-assessment.md        # Avaliação completa da plataforma
│   ├── ARCHITECTURE.mmd              # Diagrama Mermaid independente da arquitetura (artefato reutilizável)
│   └── SELF-IMPROVEMENT-LOOP.mmd     # Diagrama Mermaid do loop de auto-melhoria (artefato reutilizável)
├── benchmarks/                       # Evidências de performance
│   ├── INDEX.md                      # Índice do diretório
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
│   ├── INDEX.md                      # Índice do diretório
│   ├── getting-started.md            # Quick start
│   ├── repl-guide.md                 # Guia do REPL (jarvis dev)
│   ├── testing.md                    # Suíte de testes e convenções
│   ├── env-vars-reference.md         # Variáveis de ambiente
│   └── repl-improvements-backlog.md  # Backlog de melhorias do REPL
├── models/                           # Catálogos e docs de modelos
│   ├── INDEX.md                      # Índice do diretório
│   ├── api-catalog-2026-09-17.md     # 14 modelos free + cascata
│   └── gpu-flows-2026-09-17.md       # Fluxos GPU grátis
└── archive/                          # Documentação histórica (não editar)
    ├── README.md                     # Critério de arquivamento + inventário
    ├── benchmarks/                   # Benchmarks históricos (pré-Qwen3.6)
    ├── diagnostics/                  # Diagnósticos resolvidos
    ├── legacy-components/            # Arquitetura legada substituída
    ├── research/                     # Pesquisa que informou decisões
    ├── forensics/                    # Documentos de investigação/episódios pontuais (não guia operacional)
    └── _trash/                       # NÃO indexar no RAG
```

## 🎯 Quick Navigation

| Tópico | Documento | Status |
|--------|-----------|--------|
| **Arquitetura geral** | [architecture/system-overview.md](architecture/system-overview.md) | ✅ Revisado (MCP tools + notas de validação) |
| **MCPs e ferramentas** | [architecture/mcp-integration.md](architecture/mcp-integration.md) | ✅ Revisado (escopo de ferramentas alinhado ao código) |
| **Harness (Nightwatch)** | [architecture/agent-harness.md](architecture/agent-harness.md) | ✅ Revisado (diagramas inline coherence check) |
| **Engenharia de contexto** | [architecture/context-engineering.md](architecture/context-engineering.md) | ✅ Revisado (frontmatter/cross-refs) |
| **RAG e memória** | [architecture/rag-improvements.md](architecture/rag-improvements.md) | ✅ Revisado (frontmatter/cross-refs) |
| **Camadas de memória** | [architecture/ADR-002-memory-layers.md](architecture/ADR-002-memory-layers.md) | ✅ Revisado (frontmatter/status) |
| **Decisão de plataforma** | [architecture/ADR-001-agent-platform.md](architecture/ADR-001-agent-platform.md) | ✅ Revisado (frontmatter) |
| **Benchmarks** | [benchmarks/README.md](benchmarks/README.md) | ✅ Revisado (frontmatter/metodologia/índice) |
| **Auditorias ativas** | [audit/INDEX.md](audit/INDEX.md) | ✅ Revisado (frontmatter e cross-refs) |
| **Quick start** | [development/getting-started.md](development/getting-started.md) | ✅ Revisado (frontmatter + caminhos) |
| **Guia de testes** | [development/testing.md](development/testing.md) | ✅ Revisado (status e estrutura) |
| **REPL** | [development/repl-guide.md](development/repl-guide.md) | ✅ Revisado (frontmatter) |

## 📊 System Status

> ⚠️ Estes status são documentação estática revisada em 2026-09-09. Eles refletem o que o código-fonte e os docs dizem, não necessariamente o que está rodando na máquina agora. Verificar serviços com `jarvis status`.

| Componente | Status documentado | Detalhes / o que precisa de validação |
|-----------|--------------------|---------------------------------------|
| JARVIS Agent | ✅ Documentado | REPL (`jarvis dev`) e MCP `jarvis-mcp` declarados no código. MCP lista publicamente **22 ferramentas** em `JARVIS_TOOLS` (`mcp_server.py`). Persona expande o catálogo por capability (`persona.py`).
| llama.cpp | ✅ Documentado | Qwen3.6-35B-A3B é o modelo referência nos docs; precisão de versão/quants e flags de runtime precisa de conferência no serviço/nix em vigor.
| Qdrant | ✅ Documentado | Coleção/código aparece nos docs como indexado; contagem exata de chunks e state do cluster exigem verificação em runtime.
| Embeddings | ✅ Documentado | `nomic-embed-text-v2-moe` referenciado nos configs e docs; porta/config real deve ser confirmada.
| Reranker | ✅ Documentado | `bge-reranker-v2-m3` referenciado; porta real deve ser confirmada.
| Roo Dev | ✅ Documentado | Integrazione MCP definida no docs; efetividade em runtime a validar.
| Telegram Bot | ✅ Documentado | `@jarvis_lab_bot` aparece nos docs; existência e estado exigem verificação.
| Testes | ✅ Documentado | Suite reportada como `859 passed, 0 failed, 26 skipped, 5 xpassed` (2026-09-03) nos docs/`. Número e passagem devem ser reproduzidos com o comando do `development/testing.md` para garantir.

## 🔗 External Resources

- [AGENTS.md Spec](https://github.com/lnx-agents/AGENTS.md) — Linux Foundation standard
- [MCP Protocol](https://modelcontextprotocol.io/) — Model Context Protocol
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — Local LLM inference
- [Roo Code](https://roocode.com/) — AI coding assistant
- [Qdrant](https://qdrant.tech/) — Vector database

## 📝 Contributing

Ver [AGENTS.md](../AGENTS.md) para regras do projeto e convenções.
Ver [BUFFY.md](../../BUFFY.md) para protocolo de qualidade e evidência.

## 🧭 Estado desta documentação (honestidade)

Esta pasta `docs/` foi revisada em 2026-09-09 com foco em:
1. **Alinhar o que o índice/docs prometem ao que o código-fonte diz**, especialmente em contagens e escopo de ferramentas MCP/REPL.
2. **Separar diagramas conceituais de afirmações validadas por execução**; alguns números e fluxos ainda dependem de teste/observação em runtime.
3. **Nunca remover documento**; o que estiver fora de sincronia com a realidade vigente precisa ser arquivado, não apagado.

**O que foi revisado agora, com razoável confiança estática:**
- `architecture/mcp-integration.md`: descrição de ferramentas, diagrama de clientes/servidores/ferramentas e diagrama de segurança foram alinhados ao código (`mcp_server.py`, `devtools.py`, `persona.py`).
- `architecture/system-overview.md`: número de ferramentas MCP e notas de validação atualizados.
- `development/testing.md`, `development/getting-started.md`, `development/repl-guide.md`, `benchmarks/README.md`, `audit/INDEX.md`, `architecture/platform-assessment.md`, `architecture/jarvis-comparison.md`, `architecture/ADR-002-memory-layers.md`, `architecture/ADR-003-persona-layers.md`, `architecture/ADR-004-routing-policy.md`, `architecture/context-engineering.md`, `architecture/monorepo-schema.md`: frontmatter/status/cross-refs ajustados para coerência.

**O que ainda não tenho como validar só com leitura de código/docs (deixado para validação externa):**
- Contagem exata de ferramentas ativas em cada persona em runtime.
- Estado de serviços (running/stop), contagem real de chunks no Qdrant, portas efetivas de embeddings/reranker.
- Parte de itens abertos de auditorias que dependem de teste E2E ou teste com LLM online.
- Validação de renderização de diagramas Mermaid por engine real (o diagrama `architecture-beta` do README é suspeito em alguns editores).

**Histórico/legado (ainda preservado, não é fonte viva):**
- `docs/archive/` contém documentação histórica e duplicados antigos; o README do archive explica o critério.
- Alguns documentos de benchmarks e auditorias mantêm números de sessões passadas por rastreabilidade, não como estado atual.
