# HANDOFF — Mapa Completo do Projeto

> Este é o ÚNICO arquivo que Buffy lê no início de cada sessão.
> Atualizado: 2026-08-30

## Estado Atual (verificado agora)

### Serviços
| Serviço | Status | Porta |
|---------|--------|-------|
| llama-cpp-server | ✅ active | 8080 |
| llama-cpp-embeddings | ✅ active | 8081 |
| llama-cpp-rerank | ❌ inactive | 8082 |
| qdrant | ✅ active | 6333 |
| jarvis-wakeword | ✅ active | — |
| waybar | ✅ active | — |

### Números
- 62 módulos Python
- 87 arquivos Nix
- 54 testes
- 16 scripts
- 100 arquivos .md

## O que FUNCIONA de verdade

1. **LLM** — Qwen3.6-35B MoE rodando em 8080, 32K ctx
2. **RAG** — `jarvis-cli.sh rag-search "query"` retorna resultados
3. **Memory** — `jarvis-cli.sh remember/recall` armazena/recupera
4. **TTS** — `speak()` gera WAV e toca via pw-play
5. **Waybar** — visível na tela
6. **Wakeword** — serviço ativo
7. **Shell** — `jarvis-cli.sh shell "cmd"` executa comandos
8. **File ops** — `jarvis-cli.sh read/write/replace` funcionam
9. **HackMD** — sync funciona (`vault-sync-hackmd`)

## O que NÃO funciona

1. **Nightwatch** — precisa de rebuild (erro `--max-minutes`)
2. **Watchdog** — é só script, não é serviço systemd
3. **Rerank** — serviço inactive
4. **Qdrant port 6333** — health check falha (mas serviço active)
5. **Trigger word pipeline** — não validada
6. **Yad launcher** — fecha imediatamente

## O que é NOVO (esta sessão)

1. **watchdog.py** — monitora GPU/RAM/disk, fala via TTS
2. **classify.py** — classifica arquivos por sensibilidade
3. **dependency-graph.json** — mapa de imports Python
4. **CODE-DEPENDENCIES.md** — Mermaid auto-gerado
5. **sync-vault.sh** — sincroniza docs pro Obsidian

## Duplicações que existem

| Módulo | Duplicado em | Ação |
|--------|--------------|------|
| doctor.py (health checks) | — | OK, é o correto |
| watchdog.py (monitoring) | — | OK, é o correto |
| heal.py (auto-repair) | — | OK, é o correto |
| idle.py (background tasks) | — | OK, é o correto |

Antes havia: proactive.py, health_monitor.py (deletados, eram duplicatas)

## Caminhos importantes

| O que | Onde |
|-------|------|
| Código Python | `modules/ai/jarvis/src/jarvis/` |
| Testes | `modules/ai/jarvis/tests/` |
| Módulos Nix | `nixos/modules/`, `modules/services/`, `home-manager/modules/` |
| Scripts | `scripts/` |
| Docs | `docs/` |
| Vault Obsidian | `~/vaults/projects/` |
| JARVIS vault | `~/.local/state/jarvis/vault/` |
| Estado | `~/.local/state/jarvis/` |
| Dependency graph | `~/.local/state/jarvis/dependency-graph.json` |

## Comandos essenciais

```bash
# Testes
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Rebuild
./rebuild-host.sh

# JARVIS tools
./scripts/jarvis-cli.sh <tool> [args]

# Health check
./scripts/jarvis-cli.sh health

# Watchdog one-shot
./scripts/jarvis-cli.sh watchdog

# RAG search
./scripts/jarvis-cli.sh rag-search "query"

# Memory
./scripts/jarvis-cli.sh remember "fact"
./scripts/jarvis-cli.sh recall "query"

# TTS
nix develop --command python3 -c "from jarvis.core.voice import speak; speak('texto')"

# Vault sync
./scripts/sync-vault.sh
```

## Prioridades (em ordem)

1. **Watchdog como serviço systemd** — fala quando tem problema
2. **Nightwatch funcionando** — rebuild para corrigir
3. **Rerank serviço** — investigar por que inactive
4. **Trigger word** — validar pipeline completa

## Regras para Buffy (eu)

1. **NÃO criar arquivos novos** sem verificar se existentes resolvem
2. **USAR JARVIS tools** antes de inventar (recall, rag-search, lessons)
3. **UMA COISA POR VEZ** — fazer funcionar antes de criar próxima
4. **Ler este HANDOFF.md** no início de cada sessão
5. **Atualizar este HANDOFF.md** quando algo muda
