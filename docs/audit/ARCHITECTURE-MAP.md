# ARCHITECTURE-MAP — nixos-ai (mapa real, medido 2026-11-19)

> Fase 2 da missão contínua. Fontes: `pyproject.toml`, `opencode.json`, Nix
> modules, árvore `src/jarvis/`, `opencode.db` (somente leitura), Qdrant.
> Não é um desenho ideal — é o que **existe e roda** no host.

## 1. Entrypoints (de `modules/ai/jarvis/pyproject.toml`)
`jarvis`, `jarvis-mcp`, `jarvis-cli` equivalente, `jarvis-{stt,speak,voice,rag,
intent,emotion,waybar,webui,launcher}` — 12 console scripts.
O MCP é o ponto de entrada para agentes: `/home/nixos/.config/opencode/opencode.json`
declara **um** servidor local `mcp.jarvis` (launcher → `jarvis.mcp_server`), que
expõe 18 ferramentas (`coord_*`, `jarvis_rag_*`, `jarvis_recall`,
`jarvis_lessons`, `jarvis_rehydrate`, `jarvis_browser`, `vault_*` etc.).

## 2. Pacotes Python (`src/jarvis/`)
| pacote | papel observado | módulos grandes (linhas) |
|---|---|---|
| `cli/` | REPL `dev.py` (4204), `main.py` (1871) | comandos + handoff |
| `core/` | `agent.py` (3282), `devtools.py` (2103), `voice.py` (1306), `rag.py` (1107), `persona.py` (813), `validator.py` (812) | runtime + memória + RAG |
| `mcp_server.py` | 2671 linhas, 18 tools | ponte agente↔sistema |
| `providers/` | `telegram.py` (1499) + backends LLM | INPUT/OUTPUT externo |
| `runtime/`, `mission/`, `control_plane/`, `playbooks/`, `benchmarks/`, `webui/` | suporte, missões, eventos, testes, UI | — |

**Ponto de atenção P2**: `cli/dev.py` com 4204 linhas é o alvo da convergência
`dev.py → agent_loop.py` (ADR-003 BLOCKED). `core/agent.py` 3282 e
`mcp_server.py` 2671 também concentram responsabilidades demais.

## 3. Serviços declarados (Nix, amostra)
`jarvis-gaming-watcher.service`, `jarvis-heal.service`,
`jarvis-idle-worker.service`, `jarvis-keys-env.service`,
`jarvis-telegram.service`, `jarvis-vault-summarize.service`,
`jarvis-vault.service`, `jarvis-webui.service`.
Timers incluem `vpn-guard.timer` (anti-duas-VPNs), `backlog-nudge` na mesa.

## 4. Fluxo de dados observado (ground truth)
```
AGENTE (opencode, sessão)
  └─ MCP jarvis (18 tools) ──> jarvis.mcp_server (2671 linhas)
        ├─ coord_*             -> bus GitHub issue #100 + roster local
        ├─ jarvis_recall       -> Qdrant 'memories' (3.009 pts)
        ├─ jarvis_rag_search   -> Qdrant 'code_index' (275.724) / books (11.379)
        ├─ jarvis_lessons      -> lições persistidas (error-only no celular)
        ├─ vault_*             -> ~/.local/state/jarvis/vault (570 notas)
        ├─ jarvis_browser      -> Playwright (headless/visível/attach CDP)
        └─ jarvis_rehydrate    -> estado + memórias + lessons (no MCP atual: NÃO exposto)
REPL (jarvis dev) ──> cli/dev.py ──> core/agent.py ──> providers/LLM
NIGHTWATCH ──> task_queue (por projeto/nível) ──> harness ──> checker fixo (444)
opencode.db (1,9 GB) ──> session/message/session_message (V2: conteúdo em data)
```
**Fio desligado medido**: `jarvis_rehydrate` existe no plugin e no código, mas
**não aparece na lista de 18 tools do MCP** (`mcp search rehydrate` → nada).
O agente que retoma usa `ta-state` no celular, não o tool canônico.

## 5. Persistência e fontes de verdade
| dado | canônico | medido |
|---|---|---|
| Código/ config | git `main` (`57c91765`) | 2.931 commits |
| Sessões | `opencode.db` (`session`, `session_message`) | 723 tituladas, 259 compactações |
| Memória episódica | `~/ai-mesh/memory/episodic/*.jsonl` | 352 + 5 linhas, só erros |
| Conhecimento vetorial | Qdrant 22 coleções | code_index 275.724 pts |
| Notas duráveis | `~/.local/state/jarvis/vault` | 570 .md, 570 hashes únicos |
| Estado da frota | `~/projects/.agents/roster.json` + bus #100 | 6 agentes |
| Índice da casa | `~/ai-mesh/index/house.json` | 12 domínios |

## 6. Riscos arquiteturais medidos
1. **A/B inválido** desde `3f063d20` (Task.project sem sufixo) — corrigido em `9f5678e8`;
   números antigos de L1/L2/L3 suspeitos.
2. **Compactação degenerada** 27/259 (10,4%) no host — guard portado (`57c91765`),
   mas o hook só avisa; não substitui o resumo do core.
3. **Contexto duplicado**: AGENTS.md 1684 linhas (400 ainda injetadas no handoff).
4. **Nomes de projeto divergentes**: `dungeon-mtp` vs `dungeon-mtp-l2` (filas por nível).
5. **Worktrees**: `.worktrees/coord-mcp` ativo; `/tmp/ack-patch-wt` prunable.
6. **42 alterações não commitadas** no host (`.bak` de patches + trabalho de outros agentes).

## 7. Decisões registradas
- ADR-003 (personas): BLOCKED até convergência `dev.py→agent_loop.py`.
- ADR-004 (routing): parcialmente fechada; registry é política, hot path segue BLOCKED.
- Qdrant órfão: exportado, não apagado; produção é somente leitura.

## 8. Próxima investigação (Fase 3)
Contratos reais de `memory.py`, `rag.py`, `vector_store.py`, `knowledge_schema.py`,
`vault.py` e `vault_cipher.py` → `KNOWLEDGE-SYSTEM-AUDIT.md`.
