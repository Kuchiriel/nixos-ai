# HANDOFF — Lightweight Index do Projeto

> Este é um INDEX (~100 linhas). O mapa real está no RAG + memória.
> Use `jarvis rag-search` e `jarvis recall` a cada prompt.
> Atualizado: 2026-08-30

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

## Comandos essenciais
```bash
# Context (A CADA PROMPT)
./scripts/jarvis-cli.sh rag-search "query"
./scripts/jarvis-cli.sh recall "query"
./scripts/jarvis-cli.sh lessons "error"

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
