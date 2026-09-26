# scripts/INDEX — o que existe, o que usar (26/09/2026)

> Resposta ao "monte de script jogado": cada script tem **uma frase** aqui.
> Detalhe de contrato (stdin/args/stdout/side-effects) em
> `scripts/INVENTORY-DRAFT.md` (24/09). Convenção: script sem entrada aqui
> é legado ou experimental — pergunte antes de usar em produção.

## Corrente (usar)

| Script | Para quê |
|---|---|
| `rebuild-host.sh` | rebuild do host com validação (`--quick`, `--host-only`, `--debug`) |
| `scripts/nix-validate.sh` | validação multi-camada (sintaxe, flake, host, HM, builds, testes) |
| `scripts/harness-suite.py` | bateria interna (`--tier`, `--engine dev\|runtime`, `--only`, `--trials`) |
| `scripts/loop-close.py` | mede→classifica→propõe (`--apply-lessons`, `--file-tasks`) |
| `scripts/overnight-loop.sh` | noite inteira: bateria → MoE patcha → re-mede → gate revert |
| `scripts/ux_driver.py` | 1 task no REPL sob PTY (o que os gates medem) |
| `scripts/bench-llm.sh` | benchmark de modelo (TSV/JSONL; `-R` cuida do router; **recusa com contenção**) |
| `scripts/self-study.py` | modelo estuda as próprias falhas (aresta+lado+gap) |
| `scripts/jarvis-cli.sh` | dispatcher fino p/ `jarvis <sub>` |
| `scripts/ctx-usage.sh` | uso de contexto (só leitura, journal) |
| `scripts/monitor-nightwatch.sh` | acompanha loop autônomo |
| `scripts/sync-vault.sh` | sync do vault |
| `scripts/reindex_code.py` | reindexa código no Qdrant |
| `scripts/ingest_books.py` | ingestão do corpus de livros/papers |
| `scripts/corpus_inventory.py` | inventário do corpus |
| `scripts/safe-nixos-apply.sh` | apply NixOS com margem |
| `scripts/thermal-curve.sh` | curva temp×t/s (5min GPU quente — nunca junto de bench) |
| `scripts/moe-profiler.py` | hot-experts por layer (só lê API) |
| `scripts/ncmoe-sweep.py`, `vram-split-sweep.py`, `mlock-benchmark.sh` | sweeps MoE/VRAM (horas, GPU exclusiva) |
| `scripts/voice-selftest.sh` | self-test do pipeline de voz |
| `scripts/eval-model.py`, `eval-judge.py` | eval de modelo/juiz |
| `scripts/memory-arena-lite.py` | arena de memória (leve) |
| `scripts/fetch-resume.py` | resume de fetch |
| `scripts/ux-suite.py`, `ux-repl-session.py`, `ux_world.py`, `ux-autonomy.py` | harness UX (sessões REPL instrumentadas) |
| `scripts/read_chatgpt.py` | lê conversa compartilhada (legado do MCP reader) |
| `scripts/setup-hackmd.sh`, `scripts/night-anchor.sh`, `scripts/charger-watch.sh`, `scripts/jarvis-gaming-mode.sh`, `scripts/rvc-env.sh`, `scripts/rvc-spike-bootstrap.sh`, `scripts/roo-nightwatch-setup.sh`, `scripts/loop-runner.sh`, `scripts/bench-final.py` | utilitários pontuais (ver INVENTORY-DRAFT antes de usar) |
| `scripts/gates/` | gates do harness (G1–G11 + variantes) |
| `scripts/overnight-24-09/`, `overnight-26-09/` | evidências datadas de noites (não rodar; histórico) |
| `scripts/overnight-*-24-09.sh` | runners antigos (arqueologia; o atual é `overnight-loop.sh`) |

## Legados (não usar p/ novos vereditos)

`quick-bench.sh`, `proper-benchmark.sh`, `systematic-benchmark.sh`,
`bench-one.sh`, `a-b-compare.sh` (pré-`bench-llm.sh`).
