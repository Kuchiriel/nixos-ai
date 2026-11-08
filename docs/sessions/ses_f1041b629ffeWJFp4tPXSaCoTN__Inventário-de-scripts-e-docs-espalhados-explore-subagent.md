# Inventário de scripts e docs espalhados (@explore subagent)

- **sessão:** `ses_f1041b629ffeWJFp4tPXSaCoTN`
- **quando:** 2026-09-30 00:37 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 25 (exportadas: 11)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No repositório /home/nixos/projects/nixos-ai, faça um inventário LEITURA dos artefatos de trabalho espalhados, para um plano de consolidação. NÃO edite nada.

Preciso de:

1. `scripts/` — liste TODOS os scripts com: nome, tamanho em linhas, e uma linha do que faz (leia o docstring/header). Destaque quais são "soltos" (experimentos pontuais de uma sessão) vs "de uso contínuo" ( invocados por timer/systemd/cron/por outros scripts). Verifique quais são referenciados por: systemd units, timers, outros scripts, docs, ou AGENTS.md. Liste os órfãos (nada os referencia).

2. `docs/` — liste os .md com linhas e propósito (1 linha). Destaque: quais são pointers/índices (tipo INDEX.md), quais são handoffs datados, quais são resultado de auditoria. Note duplicações temáticas (ex: mais de um doc sobre harbor, mais de um sobre modelos).

3. `docs/HANDOFF-*.md` — quantos existem, qual o intervalo de datas, quão grandes.

4. Existe alguma estrutura de archive/ em docs/ ou scripts/? O que tem lá?

5. Verifique se existe `~/projects/nixos-ai/.agents/` e liste os arquivos.

6. Procure por scripts referenciados apenas em documentação (mencionados em .md mas sem existir, ou existem mas não são mencionados em lugar nenhum).

Retorne um inventário estruturado e conciso. Não sugira edições, apenas reporte o estado factual.

---

## · ?

I'll start by exploring the repository structure to understand the layout.

---

## · ?

`.agents/` exists. Now let me inventory `scripts/` and `docs/`.

---

## · ?

Now let me get line counts and explore the subdirectories.

---

## · ?

Now let me read the headers/docstrings of all scripts to describe what each does.

---

## · ?

Now let me check references from systemd units, timers, and other scripts.

---

## · ?

Now let me build a comprehensive reference matrix for each script across the repo.

---

## · ?

Now let me read the existing INDEX/INVENTORY artifacts and inventory `docs/`.

---

## · ?

Now let me extract titles/purposes for all docs and check the HANDOFF files.

---

## · ?

Now let me check for docs-referenced-but-missing scripts and the archive structures.

---

## · ?

Inventário completo. Nenhum arquivo foi alterado (git status limpo, 0 untracked).

---

# INVENTÁRIO LEITURA — `/home/nixos/projects/nixos-ai`

**Contexto:** 47 arquivos executáveis em `scripts/` (7.983 linhas), 175 `.md` em `docs/`, 3 `HANDOFF-*.md` datados, 3 estruturas de `archive/` distintas. Zero arquivos untracked — tudo está versionado.

---

## 1. `scripts/` — 47 executáveis

### 1A. Uso contínuo / canônicos (com entrada em `scripts/INDEX.md` §Corrente, 26/09)

| Script | Linhas | O que faz | Último commit |
|---|---|---|---|
| `nix-validate.sh` | 286 | Validação Nix em 6 camadas (sintaxe→flake→host→HM→build→testes), fail-closed | 09-14 |
| `harness-suite.py` | 386 | Bateria interna de desafios progressivos; reusa `ux_driver.py` (PTY real) | 09-26 |
| `loop-close.py` | 172 | Mede→classifica falhas→propõe (não aplica); grava lessons | 09-26 |
| `overnight-loop.sh` | 75 | Noite: bateria→MoE patcha→re-mede→gate com `git reset` se regredir | 09-26 |
| `ux_driver.py` | 200 | 1 task no `jarvis dev` sob PTY real + transcript JSON | 09-26 |
| `bench-llm.sh` | 79 | Benchmark canônico (warmup 2×64 + 3×128, TSV+JSONL); recusa com contenção | 09-24 |
| `self-study.py` | 143 | Modelo estuda as próprias falhas → `SELF-STUDY-<ts>.md` | 09-26 |
| `jarvis-cli.sh` | 355 | Dispatcher fino p/ `jarvis <sub>` (20+ tools) | 08-31 |
| `ctx-usage.sh` | 28 | Uso real de contexto via journal (só leitura) | 09-05 |
| `monitor-nightwatch.sh` | 77 | Acompanha o timer nightwatch (checa timer/log/history) | 08-29 |
| `sync-vault.sh` | 42 | Sync de docs curados → vault Obsidian | 08-30 |
| `reindex_code.py` | 109 | Reindexa `code_index` no Qdrant (idempotente) | 09-18 |
| `ingest_books.py` | 119 | Ingestão de livros/papers/digests → coleção `books` | 09-20 |
| `corpus_inventory.py` | 169 | Manifesto rastreável do corpus (path/hash/git) → JSONL | 09-18 |
| `safe-nixos-apply.sh` | 117 | Apply NixOS com margem (build→test→switch, rollback auto) | 08-22 |
| `eval-model.py` | 300 | 20 tarefas em 6 classes; sandbox real em /tmp | 09-24 |
| `eval-judge.py` | 132 | Honestidade do LLM-judge (offline + `--live`) — **usado por pytest** | 09-10 |
| `voice-selftest.sh` | 53 | TTS→STT→voice_loop autônomo, PASS/FAIL + timings | 09-07 |
| `fetch-resume.py` | 69 | Download com Range/resume/retry (stdlib) | 09-08 |
| `rvc-env.sh` | 31 | **Fonte canônica** do env RVC (sourced por `home.nix` bash+zsh) | 09-16 |
| `rvc-spike-bootstrap.sh` | 44 | Reconstrói env RVC pós-reboot; referenciado em `voice_clone.py` | 09-08 |

### 1B. HARNESS/BENCH de sessão única (sweeps longos, GPU exclusiva) — mas **documentados**

| Script | Linhas | O que faz | Refs |
|---|---|---|---|
| `thermal-curve.sh` | 225 | Curva temp×t/s em 5min de inferência contínua | INDEX, INVENTORY, 3 docs |
| `ncmoe-sweep.py` | 505 | Sweep sistemático de `--n-cpu-moe` (cooldown térmico entre configs) | INDEX, README, 2 docs |
| `vram-split-sweep.py` | 295 | Testa H1/H2/H3 de split GPU/CPU (onde o MoE perde t/s) | INDEX, HANDOFF-25 |
| `mlock-benchmark.sh` | 185 | EHS-25 vs EHS-25+`--mlock` (page faults/IO) | INDEX, INVENTORY, 3 docs |
| `moe-profiler.py` | 430 | Hot-experts por layer (só lê API, não sobe nada) | INDEX, INVENTORY |
| `bench-final.py` | 155 | Benchmark sistemático de configs llama.cpp (supersedido) | INDEX, INVENTORY, 4 docs |
| `memory-arena-lite.py` | 245 | H1 em **uso ativo** 3Fatores (contra recall passivo) | só INDEX |

### 1C. UX / diag — 4 scripts, geração 08–12/09, sem抄

| Script | Linhas | O que faz | Refs |
|---|---|---|---|
| `ux-autonomy.py` | 199 | Suíte P0, 20 tarefas user-fiéis no Agent real | INDEX, INVENTORY, archive |
| `ux-suite.py` | 178 | Bateria user-faithful + verificação do mundo | INDEX, INVENTORY, UX-REALITY-LAB |
| `ux-repl-session.py` | 124 | Usuário simulado no REPL; mede ring-window cortando cedo | só INDEX |
| `ux_world.py` | 98 | Verificadores de estado do mundo (independentes do modelo) | INDEX, INVENTORY, UX-REALITY-LAB |
| `ux-lab-site/server.py` | 79 | Site lab com estado servidor (fixture p/ UX) | — (nome genérico, 21 hits falsos) |

### 1D. Utilitários pontuais ("soltos", mas todos no INDEX como utilitários)

| Script | Linhas | O que faz | Refs |
|---|---|---|---|
| `loop-runner.sh` | 200 | Executor do LOOP-v2 (mecânico, sem julgamento) | INDEX, LOOP-v2 |
| `charger-watch.sh` | 30 | Anuncia plug/unplug do carregador por voz | INDEX, INVENTORY — **duplicado inline** em `modules/services/charger-watch.nix` |
| `jarvis-gaming-mode.sh` | 108 | stop/start serviços p/ gaming | INDEX, INVENTORY, CONTROL-PLANE-AUDIT |
| `night-anchor.sh` | 139 | Heartbeat 60s + estado de sessão noturna | INDEX, INVENTORY |
| `roo-nightwatch-setup.sh` | 117 | Verifica auto-approve do Roo Code p/ modo autônomo | INDEX, INVENTORY |
| `setup-hackmd.sh` | 59 | Grava token HackMD em `/etc/jarvis-hackmd.env` | INDEX, INVENTORY |
| `read_chatgpt.py` | 154 | Lê conversa ChatGPT via Playwright (scroll p/ hydration) | INDEX, `jarvis/core/chatgpt_reader.py` |

### 1E. Soltos de 29/09 — **ausentes de `scripts/INDEX.md`**

| Script | Linhas | O que faz | Única ref |
|---|---|---|---|
| `mission-kit.py` | 217 | Bateria que discrimina **capacidade**, não transferência (verificador externo, 1 capacidade/task) | `docs/TIERS-E-PAPEIS.md` |
| `harbor-lite.sh` | 32 | Bateria Lite fixa de regressão (bytecopy+bin+extract-line) | `docs/harbor/INDEX.md`, `ROADMAP-HARNESS.md` |
| `grade-harbor.py` | 96 | Taxonomia de estratégia sobre trajetórias (cp-shell, text-fight, header-leek…) | `docs/harbor/INDEX.md`, `HANDOFF-29` — **invocado por `harbor-lite.sh`** |
| `ab-prompt.py` | 115 | A/B de prompt com métrica honesta (bytes entregues, não RC) | `docs/TIERS-E-PAPEIS.md` |
| `session-primer.py` | 60 | Reidrata sessão em <100 linhas (anti-redescoberta) | **0 refs** |

### 1F. Orfãos (0 referência em qualquer arquivo do repo)

| Script | Linhas | Observação |
|---|---|---|
| `session-primer.py` | 60 | Criado 29/09, nunca citado. O próprio docstring diz `session-primer.sh` (nome errado) |
| `gates/gate3_sanitize_e2e.py` | 3.036 B | **0 refs.** O `INDEX.md` afirma "gates do harness (G1–G11 + variantes)" mas existe **só 1 gate** |

### 1G. Soltos datados (24–26/09) — superados

| Script | Linhas | O que faz | Refs |
|---|---|---|---|
| `overnight-agent-24-09.sh` | 128 | Harvest YouTube Codacus → RAG + OCR Drive | só INVENTORY |
| `overnight-harness-24-09.sh` | 81 | Fila determinística madrugada (OCR perícia + reindex) | só INVENTORY |

### 1H. Referenciados em .md mas **inexistentes**

| Nome citado | Onde | Realidade |
|---|---|---|
| `fish-credit-probe.py` | `BUFFY.md:1205` | Não existe em lugar nenhum |
| `server-bench.py` | `docs/audit/completed/BENCHMARK-AUDIT-2026-09-01.md:93` | Não existe |
| `rvc-triage.py` | `BUFFY.md:1207` | É `applio-lab/`, não nixos-ai — não existe aqui |
| `quick-bench.sh`, `proper-benchmark.sh`, `systematic-benchmark.sh`, `bench-one.sh`, `a-b-compare.sh`, `benchmark-official.py`, `acceptance_bench.py` | INDEX "Legados", INVENTORY | Arquivados em `scripts/archive/bench-legacy-2026-09-25/` |

### 1I. Falsos positivos a desconsiderar
`gaming-toggle.sh` e `hwprofile.py` são citados com prefixo `scripts/` mas vivem em `home-manager/scripts/` e `modules/ai/jarvis/src/`.

### 1J. Gravações de execução dentro de `scripts/`
- `overnight-24-09/` — **118 arquivos**: 90+ `loop-bonsai-*.json` (resultados), 12 `harbor-{easy,med,hard}-v{1,2,5,6}.json`, `CLAIMS.md`, `LOOP-STATE.md`, `vram-split-sweep.json` (54 KB). Não é código.
- `overnight-26-09/` — 4 arquivos: `runner.sh` (8.952 B, o **driver real** de 26/09), `moe-server.log` (128 KB), `nightwatch.log`, `runner.log`. `runner.sh` é código vivo e é invocado por `loop-runner.sh`; os 3 logs são evidência.
- `__pycache__/` — cache.

### 1K. Referências em Nix (systemd)
**Nenhum unit/timer deste repo invoca `scripts/`.** Todos os `ExecStart` do `modules/` chamam `jarvis <sub>` ou wrappers gerados em Nix:
- `nightwatch-timer.nix` → `jarvis nightwatch --tasks 10` (03:00)
- `audiobook-audit-timer.nix` → `/home/nixos/projects/applio-lab/scripts/nightly-audit.sh` (01:00) — **applio-lab, não nixos-ai**
- `charger-watch.nix` → reimplementa o script via `writeShellScript` (duplicata de `scripts/charger-watch.sh`)

Únicos `.sh` de `scripts/` referenciados por Nix: `rvc-env.sh` e `rvc-spike-bootstrap.sh` (em `home-manager/home.nix`).

### 1L. Encadeamento entre scripts (código real)
```
overnight-loop.sh  → loop-close.py
loop-close.py      → harness-suite.py
harness-suite.py   → ux_driver.py
loop-runner.sh     → harness-suite.py, overnight-26-09/runner.sh
runner.sh (26-09)  → bench-llm.sh, harness-suite.py, self-study.py
harbor-lite.sh     → grade-harbor.py
rvc-spike-bootstrap.sh ↔ rvc-env.sh
```

---

## 2. `docs/` — 175 `.md`

### 2A. Pointers / índices (10 arquivos)
| Arquivo | Linhas | Papel |
|---|---|---|
| `docs/README.md` | 165 | Índice-raiz. **Last updated 2026-09-05** (desatualizado vs. docs de 29/09) |
| `docs/architecture/INDEX.md` | 36 | Índice architecture/ |
| `docs/audit/INDEX.md` | 74 | Índice cronológico auditorias, distingue `current/` de `completed/` |
| `docs/benchmarks/INDEX.md` | 19 | Índice benchmarks/ (8 linhas de tabela) |
| `docs/development/INDEX.md` | 8 | Índice development/ |
| `docs/models/INDEX.md` | 7 | Índice models/ |
| `docs/harbor/INDEX.md` | 135 | **Único doc do diretório** — índice+mapa do Harbor |
| `docs/audit/cycle-9/README.md` | 2 | Manifest do ciclo 9 |
| `docs/archive/README.md` | 108 | Política de arquivo ("nada é apagado") |
| `docs/finetune/README.md` | 9 | Dataset futuro p/ treino |

### 2B. Handoffs datados (3 — ver §3)

### 2C. Resultado de auditoria — 78 arquivos em `docs/audit/` + 2 em `docs/auditoria/`
- `docs/audit/` raiz: 40 arquivos (contratos de Ciclo 5–9, `*-EXPERIMENT.md` de 8–13 linhas, `CYCLE-4..9-REPORT.md`)
- `docs/audit/current/` — 4 (abertos)
- `docs/audit/completed/` — 6 (concluídos)
- `docs/auditoria/` — **2** (LOOP-v3 25/09, SO-LLM-E-ENTROPIA 25/09)

### 2D. Handoff de referência (não datado)
| Arquivo | Linhas | |
|---|---|---|
| `HANDOFF.md` (raiz) | 319 | Handoff canônico antigo, 17 refs |
| `BUFFY.md` (raiz) | 1.214 | Memória viva §1–§42, 11 refs |
| `NIGHTLOG.md` (raiz) | 263 | Log append-only escrito por `safe-nixos-apply.sh` |
| `TODO-MISSAO.md` (raiz) | 109 | Backlog da missão |

### 2E. Docs de root `docs/` sem entrada em NENHUM índice
`HANDOFF-2026-09-25.md`, `HANDOFF-2026-09-26-MANHA.md`, `HANDOFF-2026-09-29.md`, `PROMPT-AGENTE-EXTERNO.md`, `ROADMAP-HARNESS.md`, `SECRETS.md`, `SISTEMA-ESTADO-E-BENCHMARKS.md`, `TIERS-E-PAPEIS.md` — 8 de 10 invisíveis para quem navega por índice.

### 2F. Duplicações temáticas

**Harbor / Harness — 4 eixos sobrepostos:**
| Eixo | Arquivos |
|---|---|
| Definição de harness | `architecture/agent-harness.md` (178), `audit/HARBOR-INTEGRATION.md` (77), `audit/CYCLE-9-{PLAN,REPORT}.md` |
| Roadmap | `ROADMAP-HARNESS.md` (77, 29/09), `harbor/INDEX.md` (135, 29/09) — **ambos 29/09, sobrepõem** |
| Evidência | `benchmarks/MODEL-HARNESS-MATRIX.md` (270), `audit/completed/HARNESS-AUDIT-2026-09-01.md` (168), `archive/research/harness-{audit,gap-analysis}.md` |
| ADR | `architecture/ADR-005-agent-runtime-kernel.md` menciona Harbor |

**Modelos / tiers — dispersos em 3 diretórios + raiz:**
`docs/models/` (5), `docs/TIERS-E-PAPEIS.md` (165, raiz), `docs/benchmarks/{MODEL-HARNESS-MATRIX,ncmoe-sweep,gpu-moe-fix,model-ceiling-l8}.md`, `docs/audit/MODEL-BOUNDARY-CYCLE6.md`, `docs/SISTEMA-ESTADO-E-BENCHMARKS.md` (raiz). **Nenhum `docs/models/INDEX.md` (7 linhas) aponta para `TIERS-E-PAPEIS.md` nem para os de benchmarks.**

**Diretório `audit/` vs `auditoria/`** — dois nomes PT/EN para a mesma função, ambos com docs de 25/09.

**Contexto / memória:** `docs/architecture/context-engineering.md` (153) e `archive/_trash/context-engineering-duplicate.md` (121) — duplicata já no lixo, mas a original segue em `architecture/`.

**Conclusão de arquitetura:** `docs/architecture/mission-consolidation.md` (346 linhas) e `docs/auditoria/SO-LLM-E-ENTROPIA-2026-09-25.md` (104) **já são o plano de consolidação que você quer refazer**. `architecture/SYSTEM-MAP.md` (53) é a fonte de verdade do AGENTS.md raiz.

---

## 3. `docs/HANDOFF-*.md`

**Quantidade: 3. Intervalo: 25/09 → 29/09 (5 dias). Tamanho: 10–137 linhas (total 177).**

| Arquivo | Linhas | Bytes | Conteúdo |
|---|---|---|---|
| `HANDOFF-2026-09-25.md` | 137 | 7.981 | Fim de sessão 25/09; bugs de perda de dados com testes; router+embeddings+reranker ativos; 12 commits sem push |
| `HANDOFF-2026-09-26-MANHA.md` | **10** | 561 | Relatório do overnight sem agente vivo; aponta `scripts/overnight-26-09/runner.log` |
| `HANDOFF-2026-09-29.md` | 30 | 1.573 | Estado multi-projeto: GuiaRenamer (funil, zero respostas) + JARVIS (rebuild 11:35) |

Fora do padrão `docs/`: **`HANDOFF.md` na raiz, 319 linhas** — formato antigo sem data no nome, 17 refs. Convive com os 3 datados sem regra de precedência declarada.

---

## 4. Estruturas de `archive/` — 4, cada uma com regra própria

| # | Caminho | Conteúdo | Regra |
|---|---|---|---|
| 1 | `scripts/archive/` | 14 arquivos | **README próprio (981 B) com 5 regras**: nunca apagar, destino datado, `rg` antes, `.gitignore`+`.ragignore` excluem, veredito em commit |
| 2 | `scripts/archive/bench-legacy-2026-09-25/` | 7 scripts bench pré-`bench-llm.sh` | Citado como exemplo canônico no README |
| 3 | `docs/archive/` | 5 subpastas: `benchmarks/`(7), `diagnostics/`(8), `forensics/`(7), `legacy-components/`(5), `research/`(9) — **36 .md** | `docs/archive/README.md` (108 linhas) |
| 4 | `docs/archive/_trash/` | 4 arquivos: `aider-chat-history.md` (**14.722 linhas / 732 KB**), `context-engineering-duplicate.md`, `JARVIS-COMPARISON.mmd`, `moe-profiling-results.json` (55 KB) | **Sem README, sem regra declarada** |
| 5 | `archive/` (raiz) | `README.md` (2.756 B) + `shell.nix` + `core/` com 8 `.py` (`agent_loop.py`, `orchestrator.py`, `subagent.py`, `workitem.py`, `learning.py`, `ast_cache.py`, `ast_guard.py`, `vision_analyzer.py`, `context.py`, `test_ast_cache.py`) + `CONSOLIDATION-2026-09-03.md` | Terceira política de arquivo, **documento canônico do antigo motor de agentes** |

**Achado de entropia:** `scripts/overnight-24-09/` e `scripts/overnight-26-09/` são arquivos **sem pasta `archive/`**, mas contêm 118 arquivos de evidência e logs. O `.gitignore` (linhas 87-89) só exclui `scripts/archive/` e `scripts/overnight-24-09/loop-*.json`.

**Não existe `.ragignore`** — o `scripts/archive/README.md` (regra 4) afirma que `.ragignore` lista o que é arquivo, mas o arquivo não está no repo.

---

## 5. `.agents/` — existe, 4 arquivos, 138 linhas

| Arquivo | Bytes | Linhas | Título |
|---|---|---|---|
| `harbor-e-harness.md` | 2.407 | 43 | `# Harbor e harness (CARREGUE SÓ SE O GATILHO CASAR)` — **modificado hoje 29/09 08:52** |
| `dados-e-memoria.md` | 1.861 | 36 | `# Dados e memória (…)` |
| `loop-e-bench.md` | 1.590 | 32 | `# Loop e benchmark (…)` — cita `bench-llm.sh`, `harness-suite.py`, `loop-runner.sh`, `memory-arena-lite.py`, `vram-split-sweep.py` |
| `memoria-do-projeto.md` | 1.413 | 27 | `# Memória do projeto (…)` |

Padrão: carga condicional por gatilho (evita sempre carregar tudo). `AGENTS.md`, `CLAUDE.md` e `GEMINI.md` são o **mesmo arquivo** (symlinks, 7.110 B).

---

## 6. Referências documentais vs. existência

### 6A. Documentados mas não existem (3)
- `scripts/fish-credit-probe.py` — `BUFFY.md:1205`
- `scripts/server-bench.py` — `docs/audit/completed/BENCHMARK-AUDIT-2026-09-01.md:93`
- `scripts/rvc-triage.py` — `BUFFY.md:1207` (é de `applio-lab/`)

### 6B. Documentados como "raiz" mas arquivados (7)
`quick-bench.sh`, `proper-benchmark.sh`, `systematic-benchmark.sh`, `bench-one.sh`, `a-b-compare.sh`, `benchmark-official.py`, `acceptance_bench.py` — citados por `scripts/INDEX.md` §Legados e `INVENTORY-DRAFT.md` como se ainda fossem "legados no lugar"; estão em `scripts/archive/bench-legacy-2026-09-25/`.

### 6C. Existentes mas não mencionados em lugar nenhum (2 órfãos)
- `session-primer.py` (60 linhas) — 0 refs
- `scripts/gates/gate3_sanitize_e2e.py` — 0 refs (e o INDEX superdeclara "G1–G11 + variantes" para um diretório com 1 arquivo)

### 6D. Fora do índice oficial, mas citados em docs (5, todos de 29/09)
`mission-kit.py` e `ab-prompt.py` (só `TIERS-E-PAPEIS.md`); `harbor-lite.sh` (`harbor/INDEX.md`, `ROADMAP-HARNESS.md`); `grade-harbor.py` (`harbor/INDEX.md`, `HANDOFF-29`); `eval-model.py`/`harness-suite.py` aparecem em `benchmarks/MODEL-HARNESS-MATRIX.md`.

### 6E. Artefatos soltos na RAIZ (fora de `scripts/`)
| Arquivo | Linhas | Refs | Observação |
|---|---|---|---|
| `ga_engine.py` | 636 | **0** | Motor GA antigo, órfão total |
| `grid_engine.py` | 339 | **0** | Motor grid antigo, órfão total |
| `CONTEXT-ENGINEERING.md` | 66 | **0** | Duplica `docs/architecture/context-engineering.md` |
| `fast_tune.py` | 437 | 1 | Só o próprio nome |
| `llm_tune.py` | 469 | 1 | Só o próprio nome |
| `fast_tune.sh` / `llm-tune.sh` | 39 / 78 | 1 cada | Wrappers dos anteriores |
| `rebuild-host.sh` | 78 | 21 | Canônico (AGENTS.md) |
| `rebuild-lab.sh` | 29 | 3 | Lab secundário |
| `clean.sh` | 91 | 7 | Faxina segura do NixOS |
| `opencode_models.txt` | — | — | 19.814 B de dump de catálogo |

**3 artefatos Python de ~1.400 linhas (`ga_engine.py` + `grid_engine.py` + `fast_tune.py`) estão versionados e sem uma única referência em todo o repositório** — candidatos naturais ao `archive/` que já existe mas nunca recebeu essa família.

---

