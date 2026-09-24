### clean.sh (4KB, #!/usr/bin/env bash)
Faxina SEGURA do NixOS: nunca deixa o sistema sem rollback. |  | Regras duras:

### fast_tune.sh (1KB, #!/usr/bin/env bash)
fast_tune.sh — Busca binária direcional para tuning do llama.cpp |  | Uso:

### home-manager/scripts/gaming-toggle.sh (1KB, #!/usr/bin/env bash)
Gaming mode toggle — for rofi and keybinding | Usage: gaming-toggle.sh [on|off|toggle|status]

### llm-tune.sh (2KB, #!/usr/bin/env bash)
══════════════════════════════════════════════════════════════════════════════ | llm-tune.sh — Tuning unificado do llama.cpp | ══════════════════════════════════════════════════════════════════════════════

### modules/ai/jarvis/src/jarvis/cli/launcher.sh (32KB, #!/usr/bin/env bash)
═══════════════════════════════════════════════════════════════════════════ | NixOS-AI Launcher v3.1 — Cyberpunk GUI | Yad + Nerd Font icons, sem markup Pango nos botões

### modules/ai/llama-ik-wrapper.sh (0KB, #!/bin/sh)
Wrapper for ik_llama.cpp fork (MoE offload: -n-cpu-moe/--cpu-moe + CUDA). | LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment | em modules/services/llama-cpp.nix — ver profile `chat` em modules/ai/models.nix.

### modules/ai/llama-prism-wrapper.sh (0KB, #!/bin/sh)
Wrapper for PrismML llama.cpp fork (Ternary Bonsai Q2_0 kernels + CUDA). | LD_LIBRARY_PATH (nix store libs + driver) é definido pelo systemd Environment | em modules/services/llama-cpp.nix — ver profile `bonsai` em modules/ai/models.nix.

### modules/ai/llama-wackmall-wrapper.sh (0KB, #!/bin/sh)
Wrapper for llama.cpp wackmall build with Expert Hot Store | Auto-detected CUDA libraries and forwarded all arguments

### rebuild-host.sh (2KB, #!/usr/bin/env bash)
Rebuild do sistema NixOS a partir do flake local. | Valida avaliação ANTES de executar o switch. | Uso: ./rebuild-host.sh [--host-only] [--debug]

### rebuild-lab.sh (0KB, #!/usr/bin/env bash)
Rebuild do sistema NixOS a partir do flake local. | Uso: ./rebuild.sh

### scripts/a-b-compare.sh (2KB, #!/usr/bin/env bash)
A/B comparison: baseline vs n-gram speculative decoding

### scripts/archive/benchmark-root-duplicate.sh (4KB, #!/usr/bin/env bash)
benchmark.sh — Benchmark E2E com gerenciamento de servidor | Zero dependência de python. Usa grep/awk pra extrair timings. | 

### scripts/archive/clean-project.sh (0KB, #!/bin/bash)
clean-project.sh — Remove código morto e backups commitados | Executar ANTES de commitar para manter o repo limpo

### scripts/archive/continuous-improvement-legacy.sh (6KB, #!/usr/bin/env bash)
continuous-improvement.sh — Loop de melhoria contínua para nixos-ai |  | Este script roda automaticamente em loop, verificando:

### scripts/archive/fix-qdrant.sh (2KB, #!/usr/bin/env bash)
fix-qdrant.sh — Reparo one-shot do Qdrant após o upgrade NixOS 24.11 → 26.05. |  | Contexto: o storage do Qdrant foi criado com a versão 1.12.x (nixpkgs 24.11).

### scripts/archive/ga-benchmark-duplicate.sh (4KB, #!/usr/bin/env bash)
══════════════════════════════════════════════════════════════════════════════ | ga-benchmark.sh — Algoritmo Genético para Tuning do llama.cpp | ══════════════════════════════════════════════════════════════════════════════

### scripts/archive/grid-benchmark-duplicate.sh (2KB, #!/usr/bin/env bash)
══════════════════════════════════════════════════════════════════════════════ | grid_benchmark.sh — Grid search focado nos genes mais sensíveis | ══════════════════════════════════════════════════════════════════════════════

### scripts/archive/llama.sh (0KB, (sem shebang))
(sem doc de header)

### scripts/archive/mount_manjaro.sh (0KB, (sem shebang))
(sem doc de header)

### scripts/archive/nightwatch-anchor-old.sh (5KB, #!/usr/bin/env bash)
══════════════════════════════════════════════════════════════ | Nightwatch Anchor Script — Ancoragem pra loop autônomo | ══════════════════════════════════════════════════════════════

### scripts/archive/run-ab-test-duplicate.sh (3KB, #!/usr/bin/env bash)
run-ab-test.sh — A/B benchmark: baseline vs n-gram spec | Runs everything sequentially. Server lifecycle managed inline.

### scripts/archive/run-tune-wrapper.sh (0KB, #!/usr/bin/env bash)
run_tune.sh — Self-contained runner for fast_tune | Activates nix dev environment and runs the optimizer

### scripts/archive/test-aider-benchmark-duplicate.sh (7KB, #!/usr/bin/env bash)
test-aider-benchmark.sh — Benchmark E2E do aider com nosso modelo | Tarefas de dificuldade crescente: leitura → edição → multi-step → shell

### scripts/archive/test-aider-duplicate.sh (3KB, #!/usr/bin/env bash)
test-aider.sh — Benchmark do aider com nosso modelo local | Testa diferentes configs e mede comportamento

### scripts/bench-one.sh (3KB, #!/usr/bin/env bash)
Simple benchmark - one config at a time, no complex bash

### scripts/charger-watch.sh (1KB, #!/usr/bin/env bash)
charger-watch.sh — anuncia plug/desplug do carregador na voz do JARVIS. | Uso: ./scripts/charger-watch.sh [intervalo_segundos] | Poll em /sys/class/power_supply/ACAD/online (1=plugado, 0=desplugado).

### scripts/ctx-usage.sh (1KB, #!/usr/bin/env bash)
ctx-usage.sh — Agrega uso real do LLM local a partir do journal. | Uso: ./scripts/ctx-usage.sh [--since "7 days ago"] | Métricas: reqs, média/max de tokens gerados, TG médio, erros.

### scripts/jarvis-cli.sh (10KB, #!/usr/bin/env bash)
jarvis-cli.sh — CLI wrapper for all JARVIS MCP tools |  | Usage:

### scripts/jarvis-gaming-mode.sh (3KB, #!/usr/bin/env bash)
═══════════════════════════════════════════════════════════════════ | JARVIS GAMING MODE | 

### scripts/mlock-benchmark.sh (7KB, #!/usr/bin/env bash)
mlock-benchmark.sh — Compare EHS-25 baseline vs EHS-25 + --mlock | Measures: TG tok/s, ms/token, minor/major page faults, disk I/O, RSS, VRAM

### scripts/monitor-nightwatch.sh (2KB, #!/usr/bin/env bash)
Nightwatch Monitor — checks for errors and reports status | Run periodically to ensure nightwatch is working correctly

### scripts/night-anchor.sh (4KB, #!/usr/bin/env bash)
═══ night-anchor.sh ═══ | Keeps a CLI session alive during overnight work. | Saves state, logs progress, and can resume from where it left off.

### scripts/nix-validate.sh (7KB, #!/usr/bin/env bash)
nix-validate.sh — Multi-layer validation for Nix/NixOS configurations. |  | Validation layers (in order):

### scripts/overnight-agent-24-09.sh (5KB, #!/usr/bin/env bash)
overnight-agent-24-09.sh — SEU overnight (não o do Muse): harvest Codacus | (transcripts → ~/Books/codacus → RAG) + digest p/ RTX 4050 6GB + varredura | OCR do resto do Drive → MORNING-REPORT-AGENT.md. Pacing pesado anti-429.

### scripts/overnight-harness-24-09.sh (3KB, #!/usr/bin/env bash)
overnight-harness-24-09.sh — fila determinística da madrugada (complementa | o overnight.py do Muse: L9/kb/DPO já cobertos lá; aqui: OCR pendências da | perícia + relatório de disco + reindex RAG).

### scripts/proper-benchmark.sh (8KB, #!/usr/bin/env bash)
proper-benchmark.sh — 10-run benchmark with CPU/GPU clock monitoring | Validates methodology and measures hardware state during inference

### scripts/quick-bench.sh (5KB, #!/usr/bin/env bash)
quick-bench.sh — Fast A/B benchmark for different llama.cpp configs | Each config: warmup 5 reqs, then 5 measured runs

### scripts/roo-nightwatch-setup.sh (4KB, #!/usr/bin/env bash)
══════════════════════════════════════════════════════════════ | Roo Code Nightwatch Setup Helper | Verifica se auto-approve está configurado para modo autônomo.

### scripts/rvc-env.sh (1KB, #!/usr/bin/env bash)
RVC voice-clone env — FONTE CANÔNICA para shells interativos (bash+zsh). | Source este arquivo em vez de exportar manualmente: | source /home/nixos/projects/nixos-ai/scripts/rvc-env.sh

### scripts/rvc-spike-bootstrap.sh (2KB, #!/usr/bin/env bash)
Reconstrói o ambiente RVC do spike (efêmero em /tmp) após reboot. | Uso: ./scripts/rvc-spike-bootstrap.sh | Ao final, exporta as envs que jarvis.core.voice_clone precisa.

### scripts/safe-nixos-apply.sh (4KB, #!/usr/bin/env bash)
safe-nixos-apply.sh — wrapper de ativação segura para uso por agente autônomo. |  | Uso: ./safe-nixos-apply.sh <build|test|switch> [hostname]

### scripts/setup-hackmd.sh (1KB, #!/usr/bin/env bash)
═══ Setup HackMD API Token ═══ | 1. Go to https://hackmd.io/settings/api | 2. Create a new API token

### scripts/sync-vault.sh (1KB, #!/bin/bash)
Sync important docs to Obsidian vault (not everything) | Run: ./scripts/sync-vault.sh

### scripts/systematic-benchmark.sh (7KB, #!/usr/bin/env bash)
systematic-benchmark.sh — Test multiple configurations to find optimal tok/s | Each config: warmup 30s, then measure 5 runs of 100 tokens

### scripts/thermal-curve.sh (8KB, #!/usr/bin/env bash)
thermal-curve.sh — Measure thermal degradation over 5 minutes of continuous inference

### scripts/voice-selftest.sh (1KB, #!/usr/bin/env bash)
Self-test autônomo do pipeline de voz (sem microfone). | TTS Kokoro sintetiza comandos → STT transcreve → voice_loop roteia. | Uso: ./scripts/voice-selftest.sh

### scripts/acceptance_bench.py (4KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/bench-final.py (5KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/benchmark-official.py (29KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/corpus_inventory.py (5KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/eval-judge.py (4KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/eval-model.py (11KB, (sem shebang))
(sem doc de header)

### scripts/fetch-resume.py (2KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/harness-suite.py (5KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/ingest_books.py (5KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/moe-profiler.py (13KB, #!/usr/bin/env python3)
Run inference and capture expert activations

### scripts/ncmoe-sweep.py (17KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/read_chatgpt.py (6KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/reindex_code.py (3KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/ux-autonomy.py (7KB, (sem shebang))
(sem doc de header)

### scripts/ux-suite.py (6KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/ux_driver.py (4KB, #!/usr/bin/env python3)
(sem doc de header)

### scripts/ux_world.py (2KB, #!/usr/bin/env python3)
(sem doc de header)


# INVENTORY-DRAFT (primeira passada automática, 24/09)
> EXTRAÇÃO AUTOMÁTICA de headers (63 scripts). Próximo ciclo: p/ cada script
> documentar — stdin | stdout | stderr | side-effects (arquivos/rede/serviços)
> | pipe-safe (s/n) | idempotente (s/n) | binários que usa.
> ACHADOS 24/09: (1) 4º binário descoberto: llama-wackmall/build (usado pelos
> benches históricos c/ mmproj — testar vs ik/upstream!); (2) mlock-benchmark.sh
> já existe com metodologia completa (page-faults/RSS/VRAM) — mlock no host falha
> por RLIMIT_MEMLOCK, este script documenta a comparação; (3) proper-benchmark =
> 10 runs + clock monitoring; systematic = warmup 30s (meus braços usam warmup
> curto — adotar 30s p/ arms térmicos); (4) gates/ + harness-challenges.json =
> o "harbor" da casa.
