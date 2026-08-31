# HANDOFF — Lightweight Index do Projeto

> Este é um INDEX (~150 linhas). O mapa real está no RAG + memória.
> Use `jarvis rag-search` e `jarvis recall` a cada prompt.
> Atualizado: 2026-08-31

## Agent Platform (novo)
| Módulo | O que faz |
|--------|-----------|
| `workspace.py` | Descobre projetos, lê manifests, monta dependency graph |
| `persona.py` | 10 personas (CTO, architect, engineers, QA, etc) |
| `workitem.py` | Kanban/Scrum agnostic, persistente, WIP limits |
| `orchestrator.py` | Decomposição, dispatch, 4 workflows |
| `context.py` | Just-in-time context pipeline (HANDOFF + RAG + memory) |
| `model_policy.py` | Route cheap/medium/strong per workflow stage |
| `platform_bridge.py` | Connects nightwatch to workspace, personas, orchestrator |

## Serviços (status rápido)
| Serviço | Status | Porta |
|---------|--------|-------|
| llama-cpp-server | ✅ | 8080 |
| llama-cpp-embeddings | ✅ | 8081 |
| qdrant | ✅ | 6333 |
| jarvis-wakeword | ✅ | — |
| waybar | ✅ | — |
| jarvis-watchdog | ✅ | — |
| jarvis-idle | ✅ | — |
| jarvis-heal | ✅ | — |

## Caminhos chave
| O que | Onde |
|-------|------|
| Código Python | `modules/ai/jarvis/src/jarvis/` |
| Testes | `modules/ai/jarvis/tests/` |
| Nix modules | `modules/services/`, `nixos/modules/` |
| Scripts | `scripts/jarvis-cli.sh` |
| Vault Obsidian | `~/vaults/projects/` |
| Estado | `~/.local/state/jarvis/` |
| Workspace state | `~/.local/state/jarvis/workspace.json` |
| Work items | `~/.local/state/jarvis/work/items.json` |
| Orchestrator | `~/.local/state/jarvis/orchestrator/` |

## Comandos essenciais
```bash
# Context (A CADA PROMPT)
./scripts/jarvis-cli.sh rag-search "query"
./scripts/jarvis-cli.sh recall "query"
./scripts/jarvis-cli.sh lessons "error"

# Agent Platform
./scripts/jarvis-cli.sh workspace --discover
./scripts/jarvis-cli.sh workspace --project nixos-ai
./scripts/jarvis-cli.sh persona --list
./scripts/jarvis-cli.sh persona --select "fix waybar"
./scripts/jarvis-cli.sh workitem --create "title" "project"
./scripts/jarvis-cli.sh workitem --next
./scripts/jarvis-cli.sh orchestrate --decompose "task" "project"
./scripts/jarvis-cli.sh stats  # execution metrics

# Depois de cada alteração
./scripts/jarvis-cli.sh remember "fiz X em Y"

# Build/Rebuild
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short
./rebuild-host.sh
```

## O que NÃO funciona
1. Nightwatch — dry-run OK, serviço precisa rebuild
2. Rerank — inactive
3. Trigger word — não validada
4. Yad launcher — fecha imediatamente

## Regras
1. RAG search ANTES de inventar
2. Remember DEPOIS de cada alteração
3. UMA COISA POR VEZ
4. Rebuild via rebuild-host.sh (nunca nixos-rebuild direto)
5. Declarativo: tudo via NixOS modules/home.file
6. Usar agent platform (workspace/persona/workitem) pra tarefas
