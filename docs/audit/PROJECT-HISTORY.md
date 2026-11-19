---
title: "Como o nixos-ai nasceu — linha do tempo verificada"
type: history
date: 2026-11-19
scope: nixos-ai/origem
method: git + opencode.db + forense + Qdrant + memory (tudo lido, nada inferido)
---

# Origem cronológica do nixos-ai (verificado, não reconstruído de memória)

## 1. As fontes que foram abertas

| fonte | medição |
|---|---|
| `git log --reverse` | **2933 commits**, de 2024-11-23 a 2026-11-19 |
| `opencode.db` (`session`) | **723 sessões com título**, 2026-08-21 a 2026-11-08 |
| `docs/archive/forensics/FORENSIC-SYSTEM-COHERENCE-2026-09-08.md` | 8 achados, re-verificados contra o código atual em 19/11 |
| Qdrant `/collections` | 22 coleções; `code_index` 275.724 pontos, `offline_survival` 15.913, `books` 11.379, `memories` 3.009 |
| `~/ai-mesh/memory/episodic/` | 352 linhas (termux) + 5 (host) |
| `AGENTS.md` | 1.684 linhas; 1.255 são um protocolo BUFFY embutido |

## 2. Os primeiros commits (origem real)

```
ae8789fa 2024-11-23 here we go again
38e6d2d6 2024-11-25 modularize
b4354883 2024-11-25 categorize
```

Marcos iniciais (filtrados por feat/nixos/jarvis/voice/model/mcp/agent):

```
cad6d8c7 2024-11-29 neovim lsp on nixos
b8eeca1f 2024-12-01 NIXOS_OZONE_WL="1"
b306d04d 2024-12-06 NIXOS_OZONE_WL moved to hyprland config
da39b799 2024-12-16 no nixos stylix module
3157a0c5 2024-12-24 Merge branch 'jj-typo-fix' of github.com:jayjay-w/nixos-config-reborn into jayjay-w-jj-typo-fix
422d0be1 2026-08-19 fix(ai): hardening da stack JARVIS — 4 correções validadas com 248 testes
21a0198d 2026-08-19 fix(agent): injeta chat_template_kwargs enable_thinking=False no payload
196ea2c1 2026-08-19 feat(audiobook): handler real com scan/read/pause/resume/stop/next/prev + TTS
bb29aa76 2026-08-19 perf(agent): otimiza prompts e tool calling para SLMs (4B-35B)
583d30ca 2026-08-19 feat(security): hardening do agente contra prompt injection e tool hallucination
6b5c4452 2026-08-19 docs(security): adiciona threat model e resultados do hardening ao HANDOFF.md
ee874080 2026-08-19 feat(observability): logging JSONL unificado + metrics + doctor proativo
9d0103f6 2026-08-19 feat(profile): perfil de usuario dinâmico + contexto adaptativo
e10a2c7a 2026-08-19 feat(pipeline): event bus + vision + triggers — pipeline orientado a eventos
```

## 3. A era das sessões (opencode.db)

Sessões por mês:

| mês | sessões com título |
|---|---:|
| 2026-08 | 23 |
| 2026-09 | 98 |
| 2026-10 | 180 |
| 2026-11 | 422 |

Arco observado nos prompts (primeiras linhas de cada sessão, em ordem):
- 2026-08-21/22: 23 sessões curtas de teste ("New session").
- 2026-09-05 19:53: primeiro prompt real de engenharia: *"Aja como o Engenheiro DevOps do ecossistema NixOS-AI… leia BUFFY.md como entrypoint"*.
- 2026-09-07/08: **onda de 14 subagentes de auditoria** (CLI/REPL, providers, RAG/MCP, voz, state machines, security boundary, config/env, llama-cpp service, router backend, duplicação de modelo). É aqui que o projeto descobre sua própria dívida técnica.
- 2026-09-13+: virada para produto (voz/RVC/audiobook, GuiaRenamer vendável).
- 2026-10 a 11: consolidação (HANDOFF entry-point, registry de personas/providers, coord MCP, frota multi-agente, A/B do dungeon).

**Interleaving medido (explica a entropia)**: de 2026-10-01 a 10-07 as sessões
são quase todas de **Tibia/OTClient/canary-official** (auditoria de protocolo
1525, sprites, economia Lua, build C++), não de nixos-ai. De 10-27 a 11-02 o
foco é **MT5/trading** e extração de papers. O trabalho de IA acontece em
janelas entre outros domínios — daí configs duplicadas, docs esparramados e
fios desligados: cada volta ao projeto retomava de memória, não de um índice.

## 4. O que a forense de 09/08 encontrou — e o que é verdade hoje

|Cachado (09/08)|Verificação em 19/11|
|---|---|
| F1 `--clone` quebrado por env + sucesso-falso|`scripts/rvc-env.sh` existe; `_run_driver` único — **mantido**|
| F2 patchelf/nix-ld|`nix-ld` referenciado; `LD_LIBRARY_PATH` restante em 5 scripts é guard de runtime legítimo (`bench-llm.sh` detecta mistura de forks, `duplex-voice-run.sh` monta o path correto) — **resolvido** (minha contagem de 16 incluía comentários) |
| F3 3 resolvers de project root → 1|**1 definição** de `find_repo_root` (`core/paths.py:35`); as 22 ocorrências são imports, não duplicatas — **mantido**|
| F4 personas Registry/Executor|`PersonaRegistry` em 15 arquivos; `jarvismodes` em 3 (ADR-003 BLOCKED) — **parcial**|
| F5 MCP RAG recriava coleção|`QdrantStore` em 10 arquivos; 1 `collections/` em mcp_server — **mantido**|
| F6 provider_registry com ZERO consumidores|**9 consumidores** hoje — **resolvido**, mas ADR-004 ainda `Proposed/BLOCKED`|
| F7 suite do Agent pulada no build|0 `pytestmark integration` — **mantido**|
| F8 `lessons("")`/waybar/tiny.en|0 chamadas `lessons("")`, `tiny.en` fora do models.nix — **mantido**|

**Conclusão verificada**: 5 de 8 achados foram realmente corrigidos; F2/F4 são parciais; F6 foi resolvido em código mas a decisão arquitetural (ADR-004) não foi formalizada.

## 4b. Entropia de contexto medida no DB

`session_message` com `type='compaction'`: **259 registros**, dos quais **27
(10,4%) degenerados** (resumo <300 caracteres, 5 deles com 0). Por mês:
set/2026 4 (2 degenerados), out/2026 68 (8), nov/2026 187 (17) — a taxa
piora conforme a frota cresce. É a medição direta do "contexto jogado fora"
que o plugin `memory-termux.js` foi escrito para evitar; o guard funciona
nas sessões do celular, mas as do host ainda compactam degenerate.
**Corrigido em 19/11** (`57c91765`): `summaryIsDegenerate()` +
`fallbackSummary()` portados para `memory.js` do host. Limite honesto: o hook
marca a reinjeção com AVISO, não substitui o resumo gravado pelo core.

## 4c. Vault e memória — o que está fora do DB

- **Vault** (`~/.local/state/jarvis/vault` no host): **570 notas .md** (1.290
  arquivos no total), de 2026-08-30 a 2026-11-17. Nomes com variação de caixa
  (`HANDOFF-...` / `handoff-...`) **não** são duplicatas byte-a-byte (medido:
  570 únicos em 570 arquivos) — falso alarme evitado por hash.
- **Memória episódica**: 352 linhas (termux, 07→19/11) + 5 (host, 18→19/11).
  **Todas são falhas/fixes** — não há registro de decisões que deram certo.
  É um log de "o que não repetir", não um histórico de capacidade.
- **RAG** (Qdrant, 22 coleções): `code_index` 275.724 pontos,
  `offline_survival` 15.913, `books` 11.379, `memories` 3.009, `sessions` 775,
  `vault` 102; 10 coleções `test_*_memories` com 1 ponto (spaces órfãs).

## 5. Dívida estrutural encontrada nesta passada (19/11)

1. **AGENTS.md injetado por inteiro**: `main.py:615` punha 1.684 linhas em todo handoff, enquanto o próprio arquivo pede <150. **Corrigido**: agora 400 linhas + ponteiro (commit `d02c4371`); teste `test_handoff.py` 4/4. Ainda acima da meta declarada.
2. **BUFFY.md é symlink de AGENTS.md** — não é duplicata (verificado por `ls -l`); nenhuma ação.
3. **Routing era política declarada vs mecanismo** (ADR-004). Meu `fleet_model_route` v1 criou um 4º MAP — **corrigido** para v2 lendo `provider_registry.route()` × health medido, com troca conservadora (6 agentes KEEP, 0 churn; commit `e119db50`).
4. **10 coleções Qdrant quase vazias** (`test_*_memories` 1 ponto, `pessoal_memories` 2) geradas por `spaces.py:139` sem registro de space no disco. **Não apagadas** — registradas para decisão do dono.
5. **sync host↔phone**: drift 176 (report-only, `sync-status`), 4 ferramentas com mesmo nome e conteúdo divergente.
6. **A/B inválido desde 3f063d20 (19/11)**: o commit sufixou a fila e `run()` por
   nível mas esqueceu `Task.project` — a task ia para `dungeon-mtp` e o harness
   lia `dungeon-mtp-l2a`, resultando em `discovery_stats.returned=0` e nenhuma
   execução. Afetou TODA a A/B recente por nível (persona, chunk). Corrigido em
   `9f5678e8`; a A/B de chunking voltou a executar de verdade (1 tarefa com
   commit e retry, verdict 3/5). **Números anteriores de L1/L2/L3 são suspeitos.**

## 6. Como reproducei sem atalhos

- `git log --reverse`, `git rev-list --count`, `git show` — 2.931 commits percorridos por filtro, não por amostragem.
- `sqlite3` direto no DB de 1,9 GB (read-only) para 723 sessões.
- `grep -rn "def find_repo_root"` para distinguir **definições** de **usos** (minha primeira medição com `grep -rl` deu 22 falsas duplicatas; corrigi antes de concluir).
- `chromium --dump-dom` para provar que o hub renderiza (o `jarvis_browser extract` havia me dado resultado falso).

> Regra aplicada: "Docs anteriores são pista, não verdade" (forense 09/08). Cada item acima foi re-medido contra código/DB em 19/11.
