# TOOLS-INDEX (generated — do not hand-edit)

> Regenerate with `python3 dataset/tools/tools_index.py` (canary). AGENTS.md reuse rule: search this index + grep tools/ for the verb BEFORE writing any script.

_174 tools._

- `ab-prompt.py` (nixos-ai/scripts) — """ab-prompt.sh — A/B de prompt com métrica HONESTA (bytes, não RC).
  use: `./scripts/ab-prompt.sh <modelo> <tier|task> [--runs N]`
- `ab_loop.sh` (nixos-ai/scripts) — ab_loop.sh — Loop A/B continuo do dungeon: escada L1/L2/L3 x modelos locais.
- `ab_loop.test.sh` (nixos-ai/scripts) — ab_loop.test.sh - Testa a classificacao de motivo do laboratorio A/B.
  use: `Uso: bash scripts/ab_loop.test.sh`
- `ab_loop_motivo.sh` (nixos-ai/scripts) — ab_loop_motivo.sh - Classifica o motivo de cada resultado do laboratorio A/B.
  use: `Uso: source este arquivo e chame classifica_motivo <rc> <patch_bytes> <run.log> <lane>.`
- `agent-api.py` (nixos-ai/scripts) — """Entrega mensagens numa sessao do opencode — QUALQUER versao da API.
  use: ``/session/:id/message`, `/session/:id/prompt_async`) ou o 2.2.6 (rota nova:`
- `agent-brief.py` (nixos-ai/scripts) — """agent-brief.py — o contexto COMPARTILHADO da frota (1 comando).
  use: `python3 scripts/agent-brief.py            # gera BRIEF.md`
- `agent-bus-pending.py` (nixos-ai/scripts) — """Le pendências do BUS de coordenação via o MCP local (coord_pending).
  use: `python3 scripts/agent-bus-pending.py [--url http://127.0.0.1:8765/mcp]`
- `agent-bus-poll.py` (nixos-ai/scripts) — """Poller do BUS para uma máquina que NÃO é esta (ex.: o opencode do Windows).
- `agent-checkpoint.sh` (nixos-ai/scripts) — agent-checkpoint.sh — checkpoint de 4 camadas em 1 comando (genérico do monorepo).
  use: `./agent-checkpoint.sh --project <path> --era "<título da era>" \`
- `agent-counter.py` (nixos-ai/scripts) — """agent-counter.py — contra-ataque ao agente moralista, com decoy.
  use: `python3 agent-counter.py --target ses_xxx --task "revise o relatorio X"`
- `agent-db-alive.py` (nixos-ai/scripts) — """agent-db-alive.py — a sessão produziu trabalho novo nos últimos N segundos?
  use: `uso: agent-db-alive.py <opencode.db> <janela_s> [session_id]`
- `agent-keepalive.sh` (nixos-ai/scripts) — =====================================================================
- `agent-model.py` (nixos-ai/scripts) — """agent-model — troca o modelo de um agente em runtime e cai no proximo
- `agent-msg.sh` (nixos-ai/scripts) — agent-msg.sh — O CANAL BOT-A-BOT, agora com ROTEAMENTO e ENTREGA por API.
- `agent-pains.sh` (nixos-ai/scripts) — agent-pains.sh — registro automático de "dores" de CLI e lições aprendidas (genérico do monorepo).
  use: `./agent-pains.sh add --kind cli|lesson|tool|env --project <path> \`
- `agent-provider-guard.py` (nixos-ai/scripts) — """agent-provider-guard.py — detecta falhas do PROVIDER de LLM e avisa (ping).
- `agent-roster.py` (nixos-ai/scripts) — """agent-roster.py — ROSTER + TASKS da coordenação multi-agente (02/11).
- `agent-spawn.py` (nixos-ai/scripts) — """agent-spawn.py — cria um agente NOVO (sessao opencode) com o modelo certo,
- `agent_config.py` (nixos-ai/scripts) — agent_config.py — configuração centralizada da frota JARVIS.
- `agent_guard.py` (nixos-ai/scripts) — """agent-guard.py — trava a entrada de intrusao na frota (medido 12/11).
  use: `python3 agent-guard.py --terms              # lista o vocabulario guardado`
- `agents-keepawake.sh` (nixos-ai/scripts) — agents-keepawake.sh — inibe o idle (tela) enquanto houver agente vivo.
  use: `USO: systemd user service (nixos-ai home-manager, agents-keepawake.service)`
- `agents-reload.sh` (nixos-ai/scripts) — agents-reload.sh — empurra mudanças para os agentes LOCAIS, sem reiniciar nada.
  use: ``/model jarvis-raw*` no TUI, com o llama-server servindo os presets).`
- `agents-watcher.sh` (nixos-ai/scripts) — agents-watcher.sh — O WATCHER ÚNICO dos agentes (17/10, dono: "consolide
- `asrd_env.py` (nixos-ai/scripts) — """asrd_env.py — environment for the duplex ASRD subprocess.
- `bench-35b-codacus.py` (nixos-ai/scripts) — """Mede o gate de voz (heldout3) em varios bracos e salva o JSON do resultado.
- `bench-llm.sh` (nixos-ai/scripts) — bench-llm.sh — benchmark padrão da casa (consolida os one-offs de 24/09).
- `bench-v9-v10-heldout3.py` (nixos-ai/scripts) — """Mede o gate v10 (Kaggle) no heldout3, com o MESMO metodo do v9.
- `bus-tail.py` (nixos-ai/scripts) — """bus-tail.py — as ultimas mensagens coord-json do bus, em JSON.
  use: `uso: bus-tail.py [limite]`
- `bus-to-nightwatch.py` (nixos-ai/scripts) — bus-to-nightwatch.py — esteira mínima: lê o bus, cria tarefas no nightwatch
  use: `Uso: bus-to-nightwatch.py [--once] [--interval 60]`
- `check-ctx-drift.py` (nixos-ai/scripts) — """Confere o contexto do registry contra o contexto REAL dos GGUFs.
- `check-plugin-contract.py` (nixos-ai/scripts) — """check-plugin-contract.py — o plugin VIVO é o mesmo código que o FONTE?
- `check-queue-handoff.py` (nixos-ai/scripts) — """check-queue-handoff.py — os ponteiros da fila para o vault existem?
  use: `python3 scripts/check-queue-handoff.py`
- `check-repo-symlinks.py` (nixos-ai/scripts) — """check-repo-symlinks.py — symlink absoluto dentro do repo quebra o eval puro.
  use: `python3 scripts/check-repo-symlinks.py [repo] [--quiet]`
- `check-text-chars.py` (nixos-ai/scripts) — """check-text-chars.py — trava os caracteres que nao devem sair da casa.
  use: `python3 scripts/check-text-chars.py <arquivo>`
- `check-voice-gate-parity.py` (nixos-ai/scripts) — """Prova de paridade: o gate do duplex-asrd e o de voice_gate.py são o mesmo.
  use: `python3 scripts/check-voice-gate-parity.py`
- `checker-chunk-a.py` (nixos-ai/scripts) — """Checker do CHUNK A (SERA/H3): o inimigo SE MOVE em direção ao player.
- `checker-chunk-b.py` (nixos-ai/scripts) — """Checker do CHUNK B (SERA/H3): o inimigo NUNCA entra na parede. 5 testes."""
- `checker-chunk-c.py` (nixos-ai/scripts) — """Checker do CHUNK C (SERA/H3): o inimigo CONTORNA o obstaculo curto.
- `consolidate_sessions_memory.py` (nixos-ai/scripts) — Consolidate opencode session summaries into durable JARVIS episodic memory.
- `consulta-antes-de-agir.py` (nixos-ai/scripts) — consulta-antes-de-agir.py — CLI auxiliar para forçar a consulta prévia.
  use: `python3 scripts/consulta-antes-de-agir.py topico="editar arquivo X"`
- `context-guard.py` (nixos-ai/scripts) — """context-guard — troca modelo/key ANTES do limite (contexto ou cota).
  use: `Uso: context-guard.py [--dry-run|--apply] [--threshold 0.80]`
- `corpus_inventory.py` (nixos-ai/scripts) — """Inventário do corpus de conhecimento (§3/§22 da missão knowledge-substrate).
  use: `~/Books            corpus de conhecimento (binários + notas; inclui versions/)`
- `ctx-usage.sh` (nixos-ai/scripts) — ctx-usage.sh — Agrega uso real do LLM local a partir do journal.
  use: `Uso: ./scripts/ctx-usage.sh [--since "7 days ago"]`
- `dat_probe.py` (nixos-ai/scripts) — """dat_probe.py — sonda do APPEARANCES .dat do CLIENT (protobuf moderno).
  use: `Uso (via nix develop do nixos-ai — PYTHONPATH e stripado no shell):`
- `decomp.py` (nixos-ai/scripts) — """decomp.py — o gargalo é decomposição ou execução?
- `deliver.py` (nixos-ai/scripts) — """deliver.py — entrega canonica (usada pelo hub para nao duplicar caminho).
  use: `uso: deliver.py <agente> <texto> [--note]`
- `dungeon-checker-jogo.py` (nixos-ai/scripts) — """CHECKER do lab "jogo do zero" — escrito ANTES e TRAVADO (444).
- `dungeon-checker-l1.py` (nixos-ai/scripts) — """CHECKER L1 do lab do dungeon — escrito ANTES do agente e TRAVADO (444).
- `dungeon-checker-l2.py` (nixos-ai/scripts) — """CHECKER L2 do lab do dungeon — escrito ANTES do agente e TRAVADO (444).
- `dungeon-checker.py` (nixos-ai/scripts) — """CHECKER do lab do dungeon — escrito ANTES do agente e TRAVADO (444).
- `dungeon-lab-zero.sh` (nixos-ai/scripts) — dungeon-lab.sh — o teste DO ZERO: criar o JOGO INTEIRO do nada.
- `dungeon-lab.sh` (nixos-ai/scripts) — dungeon-lab.sh — o teste DO ZERO do dungeon (15/11, criado do nada).
- `duplex-asrd.py` (nixos-ai/scripts) — """duplex-asrd.py — ASR v4: silero VAD (limites) + whisper.cpp GPU (texto).
- `duplex-conveyor.py` (nixos-ai/scripts) — """duplex-conveyor.py — esteira automatizada para o caminho de voz do duplex.
  use: `./scripts/duplex-conveyor.py            # corpus completo`
- `duplex-cycle.py` (nixos-ai/scripts) — """duplex-cycle.py — esteira completa de qualidade do duplex.
  use: `./scripts/duplex-cycle.py             # full pass`
- `duplex-eval.py` (nixos-ai/scripts) — """duplex-eval.py — harness de eval do modo voz full-duplex (P5, noite 20/10, HB).
- `duplex-restart.sh` (nixos-ai/scripts) — duplex-restart.sh — reinicia o cliente de voz duplex.
  use: `USO: duplex-restart.sh [--port N] [--gate intent|jarvis|on|off] [--force]`
- `duplex-sweep.py` (nixos-ai/scripts) — """duplex-sweep.py — encontra falhas reais nos logs do duplex e destila VSS.
  use: `./scripts/duplex-sweep.py               # varre 7 dias`
- `duplex-ttsd.py` (nixos-ai/scripts) — """duplex-ttsd.py — daemon TTS do modo duplex (18/10, 02:45).
  use: `USO (o cliente faz sozinho; manual p/ debug):`
- `duplex-voice-run.sh` (nixos-ai/scripts) — duplex-voice-run.sh — runner do modo voz duplex (v6.2, madrugada 18/10).
- `duplex-voice.py` (nixos-ai/scripts) — """duplex-voice.py — MODO VOZ FULL-DUPLEX v6 (madrugada 18/10, reescrita).
  use: `runtime no llama-duplex-35b) → fala ≤3 palavras ou <listen> → frases →`
- `eval-judge.py` (nixos-ai/scripts) — """eval-judge.py — mede a honestidade do LLM-judge local (core/judge.py).
- `eval-model.py` (nixos-ai/scripts) — """Model evaluation suite — tarefas representativas do JARVIS.
  use: `Uso: PYTHONPATH=src python3 eval-model.py --base http://127.0.0.1:8080 \`
- `extract_sessions.py` (nixos-ai/scripts) — """extract_sessions.py — extrai as sessões do opencode 1.18.34 (DB v1) para MARKDOWN.
- `fetch-resume.py` (nixos-ai/scripts) — """Download com resume + retry + verificação de tamanho (stdlib only).
  use: `Uso: python3 fetch-resume.py URL DESTINO [--tries 50]`
- `fetch-video-transcript.py` (nixos-ai/scripts) — """fetch-video-transcript.py — baixa a transcrição de um vídeo do YouTube, sem travar.
  use: `python3 scripts/fetch-video-transcript.py https://youtu.be/pnZh5PAF3VE`
- `fleet-dispatch.py` (nixos-ai/scripts) — fleet-dispatch — fecha o loop da frota no host.
- `fleet-milestone.py` (nixos-ai/scripts) — """fleet-milestone — notifica o dono no celular SÓ em marcos da frota.
  use: `Uso: fleet-milestone [--dry-run] [--limit 40]`
- `fleet-watchdog.sh` (nixos-ai/scripts) — fleet-watchdog — promove itens de inbox presos em queue para steer.
- `fleet_model_route.py` (nixos-ai/scripts) — """fleet-model-route v2 — model assignment from AUTHORITATIVE sources.
  use: `Usage: --dry-run (default) | --apply | --agent NAME | --test`
- `gen-lora-data.py` (nixos-ai/scripts) — """gen-lora-data.py — gera dados de treino pro LoRA de timing no 4B-MTP.
  use: `python3 gen-lora-data.py --log /tmp/opencode/duplex-voice.log --out /tmp/opencode/lora-train.jsonl`
- `gguf-ctx.py` (nixos-ai/scripts) — """Le o contexto REAL (treinado) dos modelos GGUF.
- `gguf_audit.py` (nixos-ai/scripts) — """Audit GGUFs: real dims -> KV/token -> ctx fit.
  use: `Usage: gguf_audit.py [modelsdir]  (default ~/models, JSON to stdout)`
- `grade-harbor.py` (nixos-ai/scripts) — """grade-harbor.py — taxonomia de estratégia sobre trajetórias salvas.
  use: `Uso: python3 scripts/grade-harbor.py [/tmp/harbor-work/jobs]`
- `harbor-lite.sh` (nixos-ai/scripts) — harbor-lite.sh — bateria Lite fixa p/ regressão do harness.
  use: `Uso: ./scripts/harbor-lite.sh [bonsai|fast]  (default: bonsai)`
- `harness-suite.py` (nixos-ai/scripts) — """harness-suite.py — desafios progressivos p/ jarvis dev (E2E real).
  use: `python3 scripts/harness-suite.py [--tier easy|medium|hard] [--out FILE]`
- `host-health.sh` (nixos-ai/scripts) — host-health.sh — veredito de SAÚDE DE RAM/SWAP do host (leitura only).
- `hot-swap-model.sh` (nixos-ai/scripts) — hot-swap-model.sh — troca o modelo na porta 8096 sem desligar o hub
  use: `Uso: hot-swap-model.sh <mtp|bonsai>`
- `house-offline.sh` (nixos-ai/scripts) — house-offline.sh — o house offline, num entrypoint unico.
- `hub-state.py` (nixos-ai/scripts) — """hub-state.py — o estado CONSOLIDADO da casa, num JSON so.
- `index_opencode_sessions.py` (nixos-ai/scripts) — Indexa sessões do opencode.db no Qdrant (coleção dedicada `sessions`).
- `ingest_books.py` (nixos-ai/scripts) — """Ingestão do corpus de livros/papers/digests na coleção books (§10–§11).
- `jarvis-cli.sh` (nixos-ai/scripts) — jarvis-cli.sh — CLI wrapper for all JARVIS MCP tools
- `jarvis-gaming-mode.sh` (nixos-ai/scripts) — ═══════════════════════════════════════════════════════════════════
- `jarvis-reflect.py` (nixos-ai/scripts) — """jarvis-reflect.py — Reflexão noturna (P2.7 ROADMAP-INTELIGENCIA).
  use: `USO:   jarvis reflect [--date YYYY-MM-DD] [--dry-run]`
- `jarvis-registry.sh` (nixos-ai/scripts) — jarvis-registry.sh — lê o registry de modelos (fonte única: modules/ai/models.nix)
- `judgment-bench.py` (nixos-ai/scripts) — """judgment-bench.py — concordância do modelo com as labels do dono.
- `judgment-dataset.py` (nixos-ai/scripts) — """judgment-dataset.py — as labels do dono viram dataset no formato do Laya.
- `kaggle-kernel-watch.sh` (nixos-ai/scripts) — kaggle-kernel-watch — acompanha um kernel Kaggle até COMPLETE/ERROR e puxa o output.
  use: `USAGE: kaggle-kernel-watch.sh --slug <owner/kernel> [--out <dir>] [--interval <s>]`
- `kaggle-scicom-antihalluc-kernel.py` (nixos-ai/scripts) — """RECONSTRUIDO do transcript (09/11, coord-naming) — kernel Kaggle do dataset
- `key-rotate.py` (nixos-ai/scripts) — """key-rotate — troca a credencial ATIVA de um provider no OpenCode (sem expor valor).
- `lab.sh` (nixos-ai/scripts) — lab.sh — PONTO DE ENTRADA UNICO do laboratorio A/B (dungeon x modelos).
- `llama-swap.sh` (nixos-ai/scripts) — llama-swap.sh — troca o modelo LOCAL RESIDENTE em idle (hot-swap da casa).
- `llm-swap.sh` (nixos-ai/scripts) — llm-swap.sh — sobe o modelo do braco A/B na porta que o nightwatch espera.
- `loop-close.py` (nixos-ai/scripts) — """loop-close.py — semente do laço que se fecha (F-supervisor, 26/09).
  use: `python3 scripts/loop-close.py --tier easy --rounds 1 [--apply-lessons]`
- `loop-runner.sh` (nixos-ai/scripts) — loop-runner.sh — executor do LOOP-v2 (o agente raciocina; isto executa).
  use: `Uso:  nohup ./scripts/loop-runner.sh <ciclos> <modelo> [tier] [rounds]`
- `measure-rehydrate-ab.py` (nixos-ai/scripts) — """measure-rehydrate-ab.py — A/B da injeção de resgate (M2/M3, 02/11).
  use: `./scripts/measure-rehydrate-ab.py [--model <id>] [--question "<pergunta>"]`
- `measure-repeat-rule-cost.py` (nixos-ai/scripts) — """measure-repeat-rule-cost.py — custo, em fala real, das regras de repetição.
  use: `python3 scripts/measure-repeat-rule-cost.py`
- `measure-voice-rule-cost.py` (nixos-ai/scripts) — """measure-voice-rule-cost.py — custo em FALA REAL de uma regra candidata de gate.
- `measure-voice-signals.py` (nixos-ai/scripts) — """measure-voice-signals.py — separa alucinação de fala real por sinais que o gate NÃO usa.
- `medir-acuracia-por-token.py` (nixos-ai/scripts) — """Mede ACURACIA POR TOKEN no laboratorio A/B (1M ctx vs especialista).
  use: `usage.prompt_tokens da resposta da LLM), mas nao chega na linha.`
- `medir-gate-adapter.py` (nixos-ai/scripts) — """Mede o gate no heldout3 com um LoRA, com TIMEOUT e n_predict HONESTOS,
- `medir-gate-api.py` (nixos-ai/scripts) — """Mede o gate no heldout3 com o BRAÇO DE 1M DE CONTEXTO (api), na mesma
- `medir-gate-token.py` (nixos-ai/scripts) — """Sobe o MTP com um LoRA especifico e mede o gate no heldout3, com
- `medir-token-por-braco.py` (nixos-ai/scripts) — """Mede o TOKEN REAL por braco, com o servidor do proprio braco no ar, e
- `memory-arena-lite.py` (nixos-ai/scripts) — """MemoryArena-lite: o H1 no formato de USO ATIVO (25/09).
  use: `uso ativo. Então o INCONCLUSIVE do H1 não era "memória não importa": era`
- `migrate-tools-en.py` (nixos-ai/scripts) — """migrate-tools-en.py — tool descriptions PT→EN (29/09, harness em inglês).
- `mission-kit.py` (nixos-ai/scripts) — """mission-kit.py — bateria que discrimina CAPACIDADE, não transferência.
- `mlock-benchmark.sh` (nixos-ai/scripts) — mlock-benchmark.sh — Compare EHS-25 baseline vs EHS-25 + --mlock
- `model-catalog.py` (nixos-ai/scripts) — """model-catalog.py — o catalogo REAL de modelos + medidor de rate-limit.
- `moe-profiler.py` (nixos-ai/scripts) — MoE Expert Activation Profiler for llama.cpp
  use: `Run inference and capture expert activations`
- `monitor-nightwatch.sh` (nixos-ai/scripts) — Nightwatch Monitor — checks for errors and reports status
  use: `Run periodically to ensure nightwatch is working correctly`
- `ncmoe-sweep.py` (nixos-ai/scripts) — ncmoe-sweep.py — Systematic sweep of --n-cpu-moe values for Qwen3.6-35B-A3B.
  use: `python3 ncmoe-sweep.py [--coarse] [--fine] [--configs N1,N2,...] [--runs N]`
- `night-anchor.sh` (nixos-ai/scripts) — ═══ night-anchor.sh ═══
  use: `./scripts/night-anchor.sh start    # Start anchor (background heartbeat)`
- `night-comms.py` (nixos-ai/scripts) — """night-comms.py — a PASSADA DE MADRUGADA da comunicação entre agentes.
- `night-watch.py` (nixos-ai/scripts) — """night-watch — vigilancia noturna da frota (15/11, crouton-alpha).
- `nix-validate.sh` (nixos-ai/scripts) — nix-validate.sh — Multi-layer validation for Nix/NixOS configurations.
  use: `./scripts/nix-validate.sh              # Full validation`
- `nv-gate.py` (nixos-ai/scripts) — """nv-gate — transparent rate-limit gate for the NVIDIA free tier (integrate.api.nvidia.com).
- `oc-db.py` (nixos-ai/scripts) — """oc-db.py — leitura do DB do opencode 2.2.6 (fonte unica da casa).
- `opencode-resume.sh` (nixos-ai/scripts) — opencode-resume.sh — reabre uma sessão do opencode que foi fechada
  use: `./scripts/opencode-resume.sh --list                 # lista as recentes`
- `opencode-session.sh` (nixos-ai/scripts) — opencode-session.sh — roda o TUI do opencode e GUARDA a janela ao fechar.
  use: `./scripts/opencode-session.sh            # sessão nova no cwd atual`
- `opencode-sessions.py` (nixos-ai/scripts) — """opencode-sessions — registro e reabertura das sessões opencode.
- `overnight-agent-24-09.sh` (nixos-ai/scripts) — overnight-agent-24-09.sh — SEU overnight (não o do Muse): harvest Codacus
- `overnight-harness-24-09.sh` (nixos-ai/scripts) — overnight-harness-24-09.sh — fila determinística da madrugada (complementa
- `overnight-harness-loop.py` (nixos-ai/scripts) — """Overnight harness-improvement loop (30/09).
- `overnight-loop.sh` (nixos-ai/scripts) — overnight-loop.sh — a semente germinando (F-supervisor, 26/09).
  use: `Uso: ./scripts/overnight-loop.sh [--max-tasks 3] [--max-minutes 150]`
- `pipeline.py` (nixos-ai/scripts) — """pipeline.py — estrategista (MoE) diagnostica, executor (bonsai) executa.
  use: `0/3), enquanto o MoE acerta o diagnóstico mas perde o último passo.`
- `prova_checkers.py` (nixos-ai/scripts) — """Prova que os checkers da escada PASSAM para uma solucao correta.
- `provider_matrix.py` (nixos-ai/scripts) — """provider_matrix.py — audit de TODOS os LLM providers do dono (keys de
- `rag-eval.py` (nixos-ai/scripts) — """rag-eval.py — recall@k e MRR do RAG híbrido contra perguntas de resposta conhecida.
  use: `python3 scripts/rag-eval.py --top-k 8 --rerank both`
- `reindex_code.py` (nixos-ai/scripts) — """Reindexa o code_index (coleção canônica) a partir do código vivo.
- `restart-ab.sh` (nixos-ai/scripts) — restart-ab.sh — reinicia o loop A/B com seguranca.
  use: `bash "$REPO/scripts/llm-swap.sh" release >/dev/null 2>&1`
- `restore-sessions.sh` (nixos-ai/scripts) — restore-sessions.sh — relança as sessões opencode capturadas no snapshot, no layout original
  use: `./scripts/restore-sessions.sh [--dry-run] [--file <snapshot.tsv>]`
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
- `silero_vad_iterator.py` (nixos-ai/scripts) — This is copied from silero-vad's vad_utils.py:
- `smart_turn_probe.py` (nixos-ai/scripts) — import numpy as np
- `spawn-visible.sh` (nixos-ai/scripts) — spawn-visible — cria um agente em ABERTO no TUI do Linux (não headless).
- `spk-enroll.py` (nixos-ai/scripts) — """spk-enroll.py — matricula a voz do dono para o gate de audio da voz.
- `spk-separability.py` (nixos-ai/scripts) — """spk-separability.py — mede se o gate de audio (matricula do dono) SEPARA vozes.
- `sync-vault.sh` (nixos-ai/scripts) — Sync important docs to Obsidian vault (not everything)
  use: `Run: ./scripts/sync-vault.sh`
- `task-screener.py` (nixos-ai/scripts) — """task-screener.py — tria as tarefas do painel e diz quais valem a pena.
- `thermal-curve.sh` (nixos-ai/scripts) — thermal-curve.sh — Measure thermal degradation over 5 minutes of continuous inference
- `tui-e2e.sh` (nixos-ai/scripts) — tui-e2e.sh — prova que um comando/slash do TUI roda LOCAL (zero turno de
  use: `./scripts/tui-e2e.sh --command "/jailbreak status"`
- `uhrs-capture.py` (nixos-ai/scripts) — """uhrs-capture.py — o item da tela vira label do dono (sem digitar nada).
- `uhrs-practice.py` (nixos-ai/scripts) — """uhrs-practice.py — treino do rubric de relevancia (e as primeiras labels do dono).
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
- `voice-pipeline-probe.py` (nixos-ai/scripts) — """voice-pipeline-probe.py — mede o pipeline de voz da CASA nos gatilhos.
  use: `python3 scripts/voice-pipeline-probe.py --samples 10 --max-seconds 8`
- `voice-selftest.sh` (nixos-ai/scripts) — Self-test autônomo do pipeline de voz (sem microfone).
  use: `Uso: ./scripts/voice-selftest.sh`
- `voice-trigger-fixtures.py` (nixos-ai/scripts) — """voice-trigger-fixtures.py — gera os parquets do trigger bench (durable).
- `voice-up.sh` (nixos-ai/scripts) — voice-up.sh — ERGUE A LANE DE VOZ em 1 comando (sequência sancionada
  use: `USO: voice-up.sh [--router-off]`
- `voice-watchdog.sh` (nixos-ai/scripts) — voice-watchdog.sh — verifica a pilha de voz e delega start/stop a duplex-voice.service (systemd e' o dono unico; sem orfaos).
- `voice_gate.py` (nixos-ai/scripts) — """Gate de voz: a lógica anti-alucinação do duplex-asrd, extraída verbatim.
- `voice_text_rules.py` (nixos-ai/scripts) — """voice_text_rules.py — regras de higiene de texto do asrd, num lugar só.
- `vram-split-sweep.py` (nixos-ai/scripts) — """Sweep de split GPU/CPU: onde o MoE (e o denso) perdem velocidade.
- `wake-fix-inbox.py` (nixos-ai/scripts) — """wake-fix-inbox — promove itens pendentes do inbox para delivery=steer.
  use: `Uso: wake-fix-inbox [--agent CODINOME] [--dry-run]`
- `wakeword-eval.py` (nixos-ai/scripts) — """wakeword-eval.py — mede o wakeword da casa sobre o corpus de voz.
- `watch-updates.py` (nixos-ai/scripts) — """watch-updates.py — avisa a casa quando algo novo aparece nas fontes que importam.
- `websearch.py` (nixos-ai/scripts) — """websearch.py — busca tavily p/ o duplex. Uso:
  use: `python3 websearch.py "query"  → RESPOSTA sintetizada + snippets"""`
- `whisper_streaming.py` (nixos-ai/scripts) — import numpy as np
- `xref_audit.py` (nixos-ai/scripts) — """xref_audit.py — N<->N audit: docs <-> code references.
- `yt-insights.py` (nixos-ai/scripts) — """yt-insights.py — coleta transcrições de vídeos do YouTube para o RAG offline do celular.
- `yt-push-phone.sh` (nixos-ai/scripts) — yt-push-phone.sh — empurra as transcrições curadas dos vídeos do YouTube para o
  use: `./yt-push-phone.sh --dry-run`
