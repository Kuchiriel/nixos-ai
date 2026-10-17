# TOOLS-INDEX (generated — do not hand-edit)

> Regenerate with `python3 dataset/tools/tools_index.py` (canary). AGENTS.md reuse rule: search this index + grep tools/ for the verb BEFORE writing any script.

_60 tools._

- `ab-prompt.py` (nixos-ai/scripts) — """ab-prompt.sh — A/B de prompt com métrica HONESTA (bytes, não RC).
  use: `./scripts/ab-prompt.sh <modelo> <tier|task> [--runs N]`
- `agent-msg.sh` (nixos-ai/scripts) — agent-msg.sh — O CANAL BOT-A-BOT via desktop (consolidado 17/10, dono:
  use: `USO:   agent-msg.sh [--to other|all|nsncd|plain] [--list] "texto"`
- `agents-watcher.sh` (nixos-ai/scripts) — agents-watcher.sh — O WATCHER ÚNICO dos agentes (17/10, dono: "consolide
- `bench-final.py` (nixos-ai/scripts) — """Benchmark multiple llama.cpp configurations systematically."""
- `bench-llm.sh` (nixos-ai/scripts) — bench-llm.sh — benchmark padrão da casa (consolida os one-offs de 24/09).
- `charger-watch.sh` (nixos-ai/scripts) — charger-watch.sh — anuncia plug/desplug do carregador na voz do JARVIS.
  use: `Uso: ./scripts/charger-watch.sh [intervalo_segundos]`
- `corpus_inventory.py` (nixos-ai/scripts) — """Inventário do corpus de conhecimento (§3/§22 da missão knowledge-substrate).
  use: `~/Books            corpus de conhecimento (binários + notas; inclui versions/)`
- `ctx-usage.sh` (nixos-ai/scripts) — ctx-usage.sh — Agrega uso real do LLM local a partir do journal.
  use: `Uso: ./scripts/ctx-usage.sh [--since "7 days ago"]`
- `dat_probe.py` (nixos-ai/scripts) — """dat_probe.py — sonda do APPEARANCES .dat do CLIENT (protobuf moderno).
  use: `Uso (via nix develop do nixos-ai — PYTHONPATH e stripado no shell):`
- `decomp.py` (nixos-ai/scripts) — """decomp.py — o gargalo é decomposição ou execução?
- `duplex-voice.py` (nixos-ai/scripts) — """duplex-voice.py — o MODO VOZ FULL-DUPLEX do JARVIS (17/10).
  use: `USO (no nix develop do nixos-ai — tem faster-whisper/kokoro):`
- `eval-judge.py` (nixos-ai/scripts) — """eval-judge.py — mede a honestidade do LLM-judge local (core/judge.py).
- `eval-model.py` (nixos-ai/scripts) — """Model evaluation suite — tarefas representativas do JARVIS.
  use: `Uso: PYTHONPATH=src python3 eval-model.py --base http://127.0.0.1:8080 \`
- `fetch-resume.py` (nixos-ai/scripts) — """Download com resume + retry + verificação de tamanho (stdlib only).
  use: `Uso: python3 fetch-resume.py URL DESTINO [--tries 50]`
- `fix_refs.py` (nixos-ai/scripts) — """fix_refs.py — mechanical doc-ref repairs (all verified before write).
- `gguf_audit.py` (nixos-ai/scripts) — """Audit GGUFs: real dims -> KV/token -> ctx fit.
  use: `Usage: gguf_audit.py [modelsdir]  (default ~/models, JSON to stdout)`
- `grade-harbor.py` (nixos-ai/scripts) — """grade-harbor.py — taxonomia de estratégia sobre trajetórias salvas.
  use: `Uso: python3 scripts/grade-harbor.py [/tmp/harbor-work/jobs]`
- `harbor-lite.sh` (nixos-ai/scripts) — harbor-lite.sh — bateria Lite fixa p/ regressão do harness.
  use: `Uso: ./scripts/harbor-lite.sh [bonsai|fast]  (default: bonsai)`
- `harness-suite.py` (nixos-ai/scripts) — """harness-suite.py — desafios progressivos p/ jarvis dev (E2E real).
  use: `python3 scripts/harness-suite.py [--tier easy|medium|hard] [--out FILE]`
- `ingest_books.py` (nixos-ai/scripts) — """Ingestão do corpus de livros/papers/digests na coleção books (§10–§11).
- `jarvis-cli.sh` (nixos-ai/scripts) — jarvis-cli.sh — CLI wrapper for all JARVIS MCP tools
- `jarvis-gaming-mode.sh` (nixos-ai/scripts) — ═══════════════════════════════════════════════════════════════════
- `loop-close.py` (nixos-ai/scripts) — """loop-close.py — semente do laço que se fecha (F-supervisor, 26/09).
  use: `python3 scripts/loop-close.py --tier easy --rounds 1 [--apply-lessons]`
- `loop-runner.sh` (nixos-ai/scripts) — loop-runner.sh — executor do LOOP-v2 (o agente raciocina; isto executa).
  use: `Uso:  nohup ./scripts/loop-runner.sh <ciclos> <modelo> [tier] [rounds]`
- `memory-arena-lite.py` (nixos-ai/scripts) — """MemoryArena-lite: o H1 no formato de USO ATIVO (25/09).
  use: `uso ativo. Então o INCONCLUSIVE do H1 não era "memória não importa": era`
- `migrate-tools-en.py` (nixos-ai/scripts) — """migrate-tools-en.py — tool descriptions PT→EN (29/09, harness em inglês).
- `mission-kit.py` (nixos-ai/scripts) — """mission-kit.py — bateria que discrimina CAPACIDADE, não transferência.
- `mlock-benchmark.sh` (nixos-ai/scripts) — mlock-benchmark.sh — Compare EHS-25 baseline vs EHS-25 + --mlock
- `moe-profiler.py` (nixos-ai/scripts) — MoE Expert Activation Profiler for llama.cpp
  use: `Run inference and capture expert activations`
- `monitor-nightwatch.sh` (nixos-ai/scripts) — Nightwatch Monitor — checks for errors and reports status
  use: `Run periodically to ensure nightwatch is working correctly`
- `ncmoe-sweep.py` (nixos-ai/scripts) — ncmoe-sweep.py — Systematic sweep of --n-cpu-moe values for Qwen3.6-35B-A3B.
  use: `python3 ncmoe-sweep.py [--coarse] [--fine] [--configs N1,N2,...] [--runs N]`
- `night-anchor.sh` (nixos-ai/scripts) — ═══ night-anchor.sh ═══
  use: `./scripts/night-anchor.sh start    # Start anchor (background heartbeat)`
- `nix-validate.sh` (nixos-ai/scripts) — nix-validate.sh — Multi-layer validation for Nix/NixOS configurations.
  use: `./scripts/nix-validate.sh              # Full validation`
- `overnight-agent-24-09.sh` (nixos-ai/scripts) — overnight-agent-24-09.sh — SEU overnight (não o do Muse): harvest Codacus
- `overnight-harness-24-09.sh` (nixos-ai/scripts) — overnight-harness-24-09.sh — fila determinística da madrugada (complementa
- `overnight-harness-loop.py` (nixos-ai/scripts) — """Overnight harness-improvement loop (30/09).
- `overnight-loop.sh` (nixos-ai/scripts) — overnight-loop.sh — a semente germinando (F-supervisor, 26/09).
  use: `Uso: ./scripts/overnight-loop.sh [--max-tasks 3] [--max-minutes 150]`
- `pipeline.py` (nixos-ai/scripts) — """pipeline.py — estrategista (MoE) diagnostica, executor (bonsai) executa.
  use: `0/3), enquanto o MoE acerta o diagnóstico mas perde o último passo.`
- `provider_matrix.py` (nixos-ai/scripts) — """provider_matrix.py — audit de TODOS os LLM providers do dono (keys de
- `read_chatgpt.py` (nixos-ai/scripts) — """Read a ChatGPT shared conversation via Playwright.
- `reindex_code.py` (nixos-ai/scripts) — """Reindexa o code_index (coleção canônica) a partir do código vivo.
- `roo-nightwatch-setup.sh` (nixos-ai/scripts) — ══════════════════════════════════════════════════════════════
- `rvc-env.sh` (nixos-ai/scripts) — RVC voice-clone env — FONTE CANÔNICA para shells interativos (bash+zsh).
  use: `~/models/rvc-assets (symlinks predictors/embedders no checkout). O spike`
- `rvc-spike-bootstrap.sh` (nixos-ai/scripts) — Reconstrói o ambiente RVC do spike (efêmero em /tmp) após reboot.
  use: `Uso: ./scripts/rvc-spike-bootstrap.sh`
- `safe-nixos-apply.sh` (nixos-ai/scripts) — safe-nixos-apply.sh — wrapper de ativação segura para uso por agente autônomo.
  use: `Uso: ./safe-nixos-apply.sh <build|test|switch> [hostname]`
- `self-study.py` (nixos-ai/scripts) — """self-study.py — o harness estuda os próprios fracassos (LOOP-v3).
- `session-primer.py` (nixos-ai/scripts) — """session-primer: reidrata sessão em <100 linhas (anti-redescoberta).
  use: `Uso: nix develop --command python3 scripts/session-primer.py`
- `setup-hackmd.sh` (nixos-ai/scripts) — ═══ Setup HackMD API Token ═══
  use: `Usage: ./scripts/setup-hackmd.sh`
- `sync-vault.sh` (nixos-ai/scripts) — Sync important docs to Obsidian vault (not everything)
  use: `Run: ./scripts/sync-vault.sh`
- `thermal-curve.sh` (nixos-ai/scripts) — thermal-curve.sh — Measure thermal degradation over 5 minutes of continuous inference
- `ux-autonomy.py` (nixos-ai/scripts) — """P0 autonomy suite — 20 tarefas user-fiéis no Agent REAL (P0.4 + metas P0).
  use: `Uso: python3 ux-autonomy.py --model bonsai|qwen --out DIR [--only F1,D2]`
- `ux-repl-session.py` (nixos-ai/scripts) — """ux-repl-session.py — usuário simulado no REPL do space (diagnóstico).
  use: `Uso: python3 ux-repl-session.py --space qwen4b --out /tmp/ux-repl.json`
- `ux-suite.py` (nixos-ai/scripts) — """ux-suite.py — bateria user-faithful: prompts humanos curtos + verificação do mundo.
  use: `Uso: python3 scripts/ux-suite.py --out /tmp/ux/report.json [--only T1,T2]`
- `ux_driver.py` (nixos-ai/scripts) — """ux-driver.py — human driver: roda `jarvis dev` como um humano faria.
  use: `python3 scripts/ux-driver.py --task "..." --out /tmp/ux/run1.json`
- `ux_world.py` (nixos-ai/scripts) — """world.py — verificadores objetivos de estado do mundo (benchmark-side).
- `ver-png.sh` (nixos-ai/scripts) — ver-png.sh — abre PNG em FULLSCREEN pro loop de visão (observe_screen)
  use: `Uso: ver-png.sh <arquivo.png> [ttl_segundos]`
- `vision_matrix.py` (nixos-ai/scripts) — """vision_matrix.py — testa cada VLM candidato UM POR UM com screenshot real.
  use: `Uso: python3 vision_matrix.py [imagem]  (default: trade2p-A-mais12s.png)`
- `voice-selftest.sh` (nixos-ai/scripts) — Self-test autônomo do pipeline de voz (sem microfone).
  use: `Uso: ./scripts/voice-selftest.sh`
- `vram-split-sweep.py` (nixos-ai/scripts) — """Sweep de split GPU/CPU: onde o MoE (e o denso) perdem velocidade.
- `xref_audit.py` (nixos-ai/scripts) — """xref_audit.py — N<->N audit: docs <-> code references.
