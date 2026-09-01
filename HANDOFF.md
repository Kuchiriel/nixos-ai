# HANDOFF — Lightweight Index do Projeto

> Este é um INDEX (~150 linhas). O mapa real está no RAG + memória.
> Use `jarvis rag-search` e `jarvis recall` a cada prompt.
> Atualizado: 2026-09-01

## Documentos Relacionados

| Documento | O que é | Quando ler |
|-----------|---------|------------|
| [[AGENTS.md]] | Regras compartilhadas do repo | Toda sessão |
| [[BUFFY.md]] | Profile do agente Buffy (Codebuff) | Toda sessão |
| [[CONTEXT-ENGINEERING]] | Protocolo de contexto 3 camadas | Quando perder contexto |
| [[README]] | Visão geral do projeto | Primeira vez |
| [[NIGHTLOG]] | Log de manutenção noturna | Debug noturno |
| [[TODO-MISSAO]] | Missões pendentes | Planning |

## Arquitetura

| Documento | O que cobre |
|-----------|-------------|
| [[docs/architecture/system-overview]] | Visão geral da arquitetura |
| [[docs/architecture/agent-harness]] | Harness de agentes |
| [[docs/architecture/mcp-integration]] | Integração MCP |
| [[docs/architecture/rag-improvements]] | RAG e memória |
| [[docs/architecture/llama-cpp-tuning]] | Tuning do llama.cpp |
| [[docs/architecture/ADR-001-agent-platform]] | ADR: plataforma de agentes |

## Auditorias

| Documento | Data | Escopo |
|-----------|------|--------|
| [[docs/JARVIS-MCU-PARITY]] | 2026-08-30 | Paridade com Jarvis MCU |
| [[docs/JARVIS-COMPARISON-2026-08-30]] | 2026-08-30 | Comparação com alternativas |
| [[docs/PLATFORM-AUDIT-2026-08-30]] | 2026-08-30 | Auditoria da plataforma |
| [[docs/NIGHTWATCH-AUDIT-2026-08-30]] | 2026-08-30 | Auditoria do Nightwatch |
| [[docs/GAP-ANALYSIS-2026-08-29]] | 2026-08-29 | Análise de gaps |
| [[docs/GAP-ANALYSIS-2026-08-29-ROUND3]] | 2026-08-29 | Round 3 da análise |

## Benchmarks

| Documento | O que mede |
|-----------|------------|
| [[docs/benchmarks/README]] | Índice de benchmarks |
| [[docs/benchmarks/ncmoe-sweep]] | Sweep de ncmoe |
| [[docs/benchmarks/performance-evidence-audit]] | Evidências de performance |
| [[docs/archive/benchmark-definitivo-2026-08-26]] | Benchmark definitivo |

## Agent Platform (módulos)

| Módulo | O que faz |
|--------|-----------|
| `workspace.py` | Descobre projetos, lê manifests, monta dependency graph |
| `persona.py` | 10 personas (CTO, architect, engineers, QA, etc) |
| `workitem.py` | Kanban/Scrum agnostic, persistente, WIP limits |
| `orchestrator.py` | Decomposição, dispatch, 4 workflows |
| `context.py` | Just-in-time context pipeline |
| `model_policy.py` | Route cheap/medium/strong per workflow stage |
| `platform_bridge.py` | Connects nightwatch to workspace |
| `self_test.py` | Auto-eval: black/grey/white box testing |
| `evidence.py` | Task evidence collection |
| `agent_loop.py` | Real LLM agent loop |

## Serviços Systemd

| Serviço | Comando | Status |
|---------|---------|--------|
| jarvis.target | `sudo systemctl start jarvis.target` | ✅ Master |
| qdrant | `sudo systemctl status qdrant` | ✅ 6333 |
| llama-cpp-server | `sudo systemctl status llama-cpp-server` | ✅ 8080 |
| llama-cpp-embeddings | `sudo systemctl status llama-cpp-embeddings` | ✅ 8081 |
| llama-cpp-rerank | `sudo systemctl status llama-cpp-rerank` | ✅ 8082 |
| llama-fan-control | `sudo systemctl status llama-fan-control` | ✅ Auto |
| jarvis-telegram | `sudo systemctl status jarvis-telegram` | ✅ |
| nightwatch | `sudo systemctl status nightwatch` | ✅ 03:00 |
| jarvis-wakeword | `systemctl --user status jarvis-wakeword` | ✅ User |
| mpvpaper | `systemctl --user status mpvpaper` | ✅ User |

## Caminhos Chave

| O que | Onde |
|-------|------|
| Código Python | `modules/ai/jarvis/src/jarvis/` |
| Testes | `modules/ai/jarvis/tests/` |
| Nix modules | `modules/services/`, `nixos/modules/` |
| Scripts | `scripts/jarvis-cli.sh` |
| Vault Obsidian | `~/vaults/projects/` |
| Estado | `~/.local/state/jarvis/` |
| Models/Profiles | `modules/ai/models.nix` |

## Comandos Essenciais

```bash
# Context (A CADA PROMPT)
./scripts/jarvis-cli.sh rag-search "query"
./scripts/jarvis-cli.sh recall "query"
./scripts/jarvis-cli.sh lessons "error"

# Agent Platform
./scripts/jarvis-cli.sh workspace --discover
./scripts/jarvis-cli.sh persona --list
./scripts/jarvis-cli.sh workitem --next
./scripts/jarvis-cli.sh stats

# Build/Rebuild
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short
./rebuild-host.sh

# Systemd
sudo systemctl start jarvis.target
sudo systemctl stop jarvis.target
```

## Regras

1. RAG search ANTES de inventar
2. Remember DEPOIS de cada alteração
3. UMA COISA POR VEZ
4. Rebuild via rebuild-host.sh (nunca nixos-rebuild direto)
5. Declarativo: tudo via NixOS modules/home.file
6. `models.nix` é a única fonte de verdade dos modelos
