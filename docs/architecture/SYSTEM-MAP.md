# 🗺️ System Map — nixos-ai (regenerado 18/09)

> Entrypoint de documentação. Este mapa é o índice de primeira leitura;
> cada seção aponta para a doc detalhada. Regenerado do disco — use
> `jarvis rag search` p/ conteúdo semântico.

## Topologia de repositórios (git real, verificado 18/09)

| Repo | Papel | HEAD | Remote |
|---|---|---|---|
| `~/projects/nixos-ai` (ESTE) | Config NixOS + JARVIS | 1d9e803 | (raiz: applio-lab) |
| `~/projects` | monorepo pai | c9824ea | applio-lab |
| `~/projects/applio-lab` | subrepo; remote do raiz | ce3e4b5+ | github/Kuchiriel/applio-lab |
| `~/projects/guia-renamer-pro` | subrepo gitlink | ce3e4b5 | github/Kuchiriel/guia-renamer |
| `~/projects/OTServer_UPGRADE` | repo próprio | 694db273 | github/Kuchiriel/otserver-upgrade |
| `~/projects/red-teaming` | subrepo | 9f18359 | (sem remote) |
| `~/projects/Corretor` | subrepo | 0f77805 | (sem remote) |
| `~/Books` | biblioteca + notas RAG | 69a6e7f | (sem remote) |
| `~` (home) | dotfiles + vaults | b0ec6e4 | (sem remote) |

## Camadas do sistema (cada uma com doc)

- **Arquitetura geral** → [[ARCHITECTURE.mmd|ARCHITECTURE.mmd]] + [[system-overview|system-overview.md]] + [[agent-harness|agent-harness.md]]
- **Memória (3 camadas)** → [[ADR-002-memory-layers|ADR-002-memory-layers.md]] — episódica (Qdrant `memories`) ≠ RAG (`code_index`) ≠ vault (síntese)
- **Roteamento de modelos** → [[ADR-004-routing-policy|ADR-004-routing-policy.md]] + [[llama-cpp-tuning|llama-cpp-tuning.md]] — router :8080, tiers bonsai/fast/strong
- **Personas** → [[ADR-003-persona-layers|ADR-003-persona-layers.md]]
- **Plataforma de agentes** → [[ADR-001-agent-platform|ADR-001-agent-platform.md]] + [[nightwatch-components|nightwatch-components.md]]
- **Context engineering** → [[context-engineering|context-engineering.md]] + [[rag-improvements|rag-improvements.md]]
- **MCP** → [[mcp-integration|mcp-integration.md]]
- **Schema do monorepo** → [[monorepo-schema|monorepo-schema.md]]
- **Técnicas SLM** → [[slm-techniques|slm-techniques.md]]
- **Self-improvement** → [[SELF-IMPROVEMENT-LOOP.mmd|SELF-IMPROVEMENT-LOOP.mmd]]

## Serviços (runtime)

- router/chat :8080 (bonsai default) · embeddings :8081 · rerank :8082 · Qdrant :6333 (coleções: code_index, memories, books)
- envfs (shebang /bin/bash) · rebuild via `./rebuild-host.sh`

## Conhecimento (substrate)

- Inventário: `$JARVIS_STATE_DIR/sanitize/inventory/corpus.jsonl` (317 entradas, 8 tipos)
- Backup Qdrant: `$JARVIS_STATE_DIR/sanitize/backup/20260918T173625Z/` (597 pts, sha verificado)
- Sanitização pré-RAG: `modules/ai/jarvis/src/jarvis/core/doc_sanitize.py` + `doc_sources.py`
- Notas RAG: `~/Books/harness/` (13 digests) · `~/Books/memory/` (backup integral) · `~/Books/session-2026-09-18/`
- Livros/áudio: `~/Books/` (1.1G, fora do git)

## Onde mora o quê (código)

- Agent loop/harness: `modules/ai/jarvis/src/jarvis/core/agent.py`
- Sanitize: `core/doc_sanitize.py` · Qdrant client: `providers/vector_store.py`
- Indexer/RAG híbrido: `core/rag.py` · Memória: `core/memory.py` · Vault: `core/vault.py`
- Segurança: `core/security.py` · Router: `core/router.py` · MCP: `mcp_server.py`
- Módulos NixOS: `modules/services/` · Host: `hosts/nitro-v15/configuration.nix`
