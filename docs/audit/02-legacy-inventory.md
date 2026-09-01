# Inventário do legado Manjaro/Arch — Fase 2

> Fonte: snapshot do disco LUKS `manjaro-rescue` (btrfs), subvolume `@home` montado em `/mnt/manjaro/kuchiriel` (1.246 arquivos relevantes inventariados; home completo = 463.873 arquivos / 49 GB, incluindo caches/venvs/binários).
> Tratado como **arqueologia**: nada foi copiado para o projeto, nada foi apagado.

## 1. Classificação por tipo (top-level do home)

| Tipo | Itens |
|---|---|
| Código-fonte (projeto IA) | `Projects/AI_SYSTEM/` (~600+ arquivos .py/.sh/.rive/.json) |
| Estado/dados de runtime | `.jarvis/` (memórias, sessões, libros, vozes, sons, venv) |
| Índice vetorial | `.ai-index/` (NumPy: `global_vectors.npy`, `global_meta.json`, `symbols.json`, `file_hashes.json`) |
| Binários pip/venv | `.local/bin/` (99 binários: whisper, chroma, litellm, piper, ct2, frida, gemini-api…) |
| Serviços systemd user | `.config/systemd/user/*.service` (16 unidades, algumas symlinks p/ AI_SYSTEM/daemons) |
| Configs de IA | `.config/litellm/` (config-free-ai.yaml e variantes), `.config/ai-tools/`, `.config/kokoro/`, `.config/jarvis/` |
| Quarentena/protocolo | `AI_AIRLOCK/` (00_README + prompts; subdirs inventory/plan/logs vazios) |
| Modelos | `.local/share/kokoro/` (kokoro-v1.0.onnx 325MB, voices.bin, jarvis-medium.onnx), `.ollama/models` (blobs) |
| Documentação | `GEMINI.md`, `.gemini/`, `.claude/`, `*.md` dentro de AI_SYSTEM (30+ docs) |
| Fora de escopo IA | `Projects/OTServer_UPGRADE`, `tibia_re_discoveries`, frida/radare2, Downloads, mídias |

## 2. Prioridades analisadas (ordem da missão)

### 2.1 `Projects/AI_SYSTEM/` — o sistema de IA (coração do legado)

```
core/          agent_executor, book_extractor, book_indexer, codebase_indexer (RAG V4.0.5),
               code_validator, config (central), critic, experience_buffer, web_search_wrapper
agents/        jarvis_master_engine, jarvis_ship_computer_engine, cascade_critic/planner,
               self-healing-jarvis, gemini/claude auto-responders, inotify-indexer.sh, llm_stream
daemons/       jarvis_daemon.py (Backbone V73 — FastAPI+unix socket), jarvis-afk, unlimited-dev,
               *.service (8 unidades), wakeword-ctl, setup-pipewire-denoise
ipc/           ipc.sh (file-based outbox), claude/gemini-ipc-daemon, neural-coordinator.sh,
               ipc-ai-adapter, ipc-multi-agent-start, SIMPLE-IPC-USAGE.md
llm/           free-ai-manager.sh, prompt-templates/
orchestrator/  brain/ (RiveScript), rivescript_router.py (1649 ln), semantic_router.py,
               routing_engine.py, pipeline_orchestrator.py, ai_orchestrator_module.py,
               neural_* (pattern_factory, variator, command_gen), self_improvement, self_organize
vision/        call_vision_api, ollama_vision_helper (moondream), ocr_helper, jarvis-vision-*.sh
tools/         rag_query.py, generate_rive_semantic_map, intent_benchmark, jarvis-tui, sota_watcher,
               jarvis-calibrate, massive_benchmark, test-full-autonomy
scripts/       audiobook-reader (wrapper venv), jarvis-alarm-morning/sleep, test_voice_pipeline,
               sanitize_texts, setup-audiobook-sounds, tibia-re (fora de escopo)
jarvis/        jarvis-brain-process.py (IPC), jarvis-wakeword-openwake.py (V217),
               jarvis-ear-v2.py (PTT legado), enhanced_audiobook.py (728 ln), jarvis-repl.py,
               jarvis-agent.py, session_memory.py (attention sinks), emoji_tone, emotional_state,
               jarvis-read, jarvis-refine-grammar, jarvis-list-voices
context/       ACTIVE_SESSION.md, SYSTEM_STATUS.md
config/        indexer_config.json, voice.json, voice_pipeline.json, backups/
datasets/      rive/ (brain de bots externos), aiml_source/ (Mitsuku), training_data.jsonl — 36 MB
archive/       consolidados, scripts legados, session_manager.py antigo (referências confirmadas p/ fora)
```

### 2.2 `.jarvis/` — estado persistente de runtime

| Artefato | Papel |
|---|---|
| `experience_buffer.jsonl` | **memória episódica** (task/error_pattern/successful_fix — aprendizagem técnica) |
| `session_memory.json` / `sessions.db` | memória de sessão (histórico user/assistant, SQLite) |
| `books/`, `books_db/chroma.sqlite3`, `chroma_books/` | **AudiobookReader**: índice ChromaDB dos livros |
| `reading_state.json` | progresso de leitura (%/chunk) por livro |
| `voices/` | vozes TTS (XTTS speaker wav, mp3) |
| `sounds/` | feedback sonoro da wakeword (8 categorias) |
| `pids/` | pids dos daemons |
| `audiobook-env/` | venv Python **3.11.14** com chromadb/coqpit/conformer (XTTS) |

### 2.3 `.ai-index/` — RAG de código (NumPy)

`global_vectors.npy` + `global_meta.json` + `symbols.json` + `file_hashes.json` — embedding de arquivos (nomic-embed-text via Ollama) com busca híbrida por similaridade + símbolos + filename boosts.

### 2.4 `AI_AIRLOCK/` — protocolo de entrada controlada de agentes

`00_README.md` define: inventory → sanitization plan → controlled execution → context hardening. **Subdirs vazios** (framework conceitual, pouco executado). Conceito a preservar como processo, não como código.

## 3. Stack de dependências do legado (do pacman + pip + modelos)

**Sistema (pacman):** cuda 13.1.1, cudnn, nvidia-dkms 590, onnxruntime-cpu, `python-faster-whisper 1.2.0`, `python-pytorch 2.9.1`, `python-transformers 4.57`, `python-ctranslate2 4.6.3`, `python-kokoro 0.9.4`, `python-misaki`, pyaudio, portaudio, numpy 2.4, scipy, scikit-learn, ffmpeg 8, nodejs 25, rust.

**pip/user (.local/bin):** chromadb, ctranslate2, faster-whisper, litellm, piper, openwakeword, kokoro-onnx, XTTS (Coqui), requests-unixsocket, pymupdf, ebooklib, fastapi/uvicorn, scipy.

**Ollama (modelos):** qwen2.5-coder:3b, deepseek-r1:1.5b, gemma3:1b, phi3, nomic-embed-text, moondream. Ollama 0.13.0 com `OLLAMA_KEEP_ALIVE=30s`, serviço systemd como user kuchiriel.

**Externos (free-tier, via LiteLLM):** Groq (llama-3.3-70b), Gemini (2.0-flash-exp), Mistral, OpenRouter, Together (DeepSeek-R1-Distill-32B), HuggingFace. Claude (API paga) via Claude Code.
⚠️ **Segurança**: `config-free-ai.yaml` contém **API keys em texto plano** (Groq/Gemini/Mistral). Não migrar; rotacionar.

**Modelos TTS:** Kokoro (kokoro-v1.0.onnx + voices.bin, jarvis-medium), XTTS-v2 (via Coqui TTS, speaker `default_narrator.wav`).

## 4. Candidatos a código morto / descartáveis (confirmar referências antes de remover)

- `*.bak`, `*.bak2`, `*.pre-async-refactor`, `*.verified_sota`, `*.failed_heuristic`, `temp_log_*` — backups internos de refactor (confirmar 0 referências).
- `jarvis-ear-v2.py` + `jarvis-voice.service` — deprecated no próprio legado ("DO NOT USE" no daemons/README).
- `agents/gemini-*`, `claude-auto-responder*`, `ipc/claude-ipc*`, `ipc/gemini-ipc*` — orquestração de CLIs externos (Claude Code/Gemini CLI); fora do sistema local-first.
- `tibia_re_discoveries`, `jarvis_tibia_re`, `get-tibia-email-code`, `tibia-reverse-engineering` — projeto paralelo (Tibia), fora da missão IA.
- `unlimited-dev.py`, `ai-prevent-sleep.service` — hacks de sessão de dev.
- `.config/litellm/config-*.yaml` (6 variantes) — config sprawl; consolidar em 1.
- `waybar_config_*.jsonc` (4+ variantes), `config_final_v9.jsonc`, `config_safe_v6.jsonc` — sprawl de configs.
- `AI_AIRLOCK/01..04` vazios — preservar só o protocolo (README + prompts).

## 5. O que NÃO está no legado (importante para o plano)

- **Sem llama.cpp** (Ollama era o runtime) — mandato da missão: substituir.
- **Sem Qdrant** (NumPy + ChromaDB) — mandato: migrar para Qdrant.
- **Sem testes automatizados** (só scripts de benchmark/manual: `test-voice-system.sh`, `massive_benchmark.py`).
- **Sem separação core/adapters** — tudo acoplado a caminhos absolutos `/home/kuchiriel/Projects/AI_SYSTEM`, hardcoded `hw:1,7`, `localhost:11434`.

---
**Ver também:** [[../../HANDOFF]] | [[../PLATFORM-ASSESSMENT]] | [[../GAP-ANALYSIS-2026-08-29]]
