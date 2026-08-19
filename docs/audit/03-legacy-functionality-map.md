# Mapa de funcionalidades do legado — Fase 3

> Para cada componente: propósito, entrypoint, dependências, consumidores, estado, latência esperada, determinismo, classificação.

## 1. Pipeline de voz (o comportamento central a preservar)

```
[openwakeword "hey jarvis" contínuo]
        │  (arecord hw:1,7 — hardcoded; VAD por RMS relativo ao pico; 12s máx; cooldown 5s;
        │   mata TTS/audiobook em reprodução)
        ▼
[grava .wav → jarvis-brain-process.py → unix socket do daemon]
        ▼
[faster-whisper small (GPU int8_float16→CPU int8) — VAD params: threshold 0.05,
 min_speech 100ms, min_silence 600ms, pad 300ms, lang=pt]
        ▼
[routing_engine.route(): pipeline → rivescript fast path → semantic → executor + RAG]
        ▼
[resposta → TTS: XTTS-v2 (primário, GPU) → Kokoro (fallback, CPU) — lock anti-overlap,
 detecção pt/en, emoção via emoji, chunks 150 chars com prebuffer]
        ▼
[feedback: /tmp/jarvis-status.json + waybar + notify-send + beep]
```

**Classificação: PRESERVAR o comportamento; REIMPLEMENTAR o transporte (sem caminhos hardcoded, device de áudio via PipeWire, sem Ollama).**

## 2. Componente a componente

### 2.1 Roteamento (o cérebro)

| Componente | Arquivo | Latência | Dependências | Classificação |
|---|---|---|---|---|
| Fast path RiveScript | `orchestrator/rivescript_router.py` (1649 ln) + `brain/*.rive` | 50–200 ms | python-rivescript, brain (core/social/technical/user/filters/contexts/generated/accessibility), macros: system, git, file, vision, math, time, type, audiobook, change_voice | **PRESERVAR** (núcleo do mandato "fast paths") — adaptar runtime |
| Semantic router | `orchestrator/semantic_router.py` | ~ms (TF-IDF) / ~1 s (fallback Phi3) | scikit-learn, numpy, Ollama phi3 | **ADAPTAR** — TF-IDF é determinístico e barato; fallback LLM via llama.cpp |
| Meta-router executor | `routing_engine.py` | +1–10 s | LiteLLM/Groq (LLM decide API vs LOCAL) | **REIMPLEMENTAR** — decisão por regras determinísticas + capacidade local; eliminar LLM-para-LLM |
| Pipeline multi-step | `pipeline_orchestrator.py` | variável | LLM + tools | **ADAPTAR** — manter conceito, testar |
| Intent detection | `semantic_router.classify` (SYSTEM/CODING/VISION/CHAT) | ms | TF-IDF/cosine | **PRESERVAR** com testes de benchmark (já existe `intent_benchmark.py`) |

### 2.2 Conhecimento (RAG)

| Componente | Arquivo | Dependências | Classificação |
|---|---|---|---|
| Indexador de código | `core/codebase_indexer.py` (V4.0.5) | Ollama nomic-embed-text, numpy, requests | **REIMPLEMENTAR** — mesmo algoritmo híbrido (semântico + símbolos + filename boost) sobre Qdrant (dense + sparse BM25); embedding via llama.cpp `--embeddings` |
| Busca de contexto | `tools/rag_query.py` | codebase_indexer | **REIMPLEMENTAR** (idem) |
| Busca de símbolos | `codebase_indexer.search_symbols` + `symbols.json` | regex por extensão | **PRESERVAR** (vira payload estruturado do Qdrant) |
| RAG de livros | `core/book_extractor.py` (PDF/EPUB/TXT: PyMuPDF/ebooklib) + `book_indexer.py` | ChromaDB | **ADAPTAR** — extração preservada; destino ChromaDB→Qdrant |
| Índice NumPy | `~/.ai-index/*.npy` | numpy | **DEPRECAR** (migração one-shot p/ Qdrant com teste de paridade) |

### 2.3 Memória

| Componente | Arquivo | Estado | Classificação |
|---|---|---|---|
| Memória episódica (lições) | `core/experience_buffer.py` → `~/.jarvis/experience_buffer.jsonl` | JSONL, busca por keyword | **REIMPLEMENTAR** — schema rico (timestamp/origem/confiança/retention) em Qdrant + busca semântica |
| Memória de sessão | `jarvis/session_memory.py` (StreamingLLM: attention sinks + janela deslizante + sumarização) | `/tmp/jarvis_session.json` — **volátil!** | **REIMPLEMENTAR** — persistir em `~/.local/state/jarvis/` (XDG_STATE_HOME) |
| Histórico de sessão | `.jarvis/sessions.db` (SQLite) | persistente | **ADAPTAR** |
| Progresso de leitura | `.jarvis/reading_state.json` | persistente | **PRESERVAR** |

### 2.4 Percepção

| Componente | Arquivo | Dependências | Classificação |
|---|---|---|---|
| Wakeword | `jarvis/jarvis-wakeword-openwake.py` (V217) | openwakeword (hey_jarvis.onnx), pyaudio/arecord | **ADAPTAR** — device via PipeWire (sem `hw:1,7` hardcoded), mesma lógica de VAD/cooldown/feedback |
| STT | `daemons/jarvis_daemon.py` (faster-whisper small) | ctranslate2/faster-whisper, torch | **PRESERVAR** (faster-whisper) — avaliar whisper.cpp p/ CPU-only na VM; GPU no bare metal |
| Correção STT | "Gemma correction" (citado no daemons/README) | Ollama gemma3:1b | **ADAPTAR** (llama.cpp) ou DEPRECAR (whisper moderno já é robusto) |
| Vision | `vision/*` (screenshot, OCR, moondream via Ollama) | Ollama moondream, tesseract | **ADAPTAR** — moondream tem GGUF e roda no llama.cpp |

### 2.5 Resposta (TTS)

| Componente | Dependências | Classificação |
|---|---|---|
| TTS primário XTTS-v2 (Coqui) | torch, coqpit, ~2 GB VRAM | **SUBSTITUIR** — Coqui descontinuado; Kokoro (82M, CPU, PT-BR) já era o fallback e é o estado-da-arte local em 2026 |
| TTS fallback Kokoro | kokoro-onnx (kokoro-v1.0.onnx + voices.bin), misaki | **PRESERVAR** — vozes af_sky/af_nicole/am_michael/am_adam já configuradas |
| Emoção/speed via emoji | `jarvis/emoji_tone.py`, `emotional_state.py` | **PRESERVAR** |
| Detecção pt/en | `_detect_language` no daemon | **PRESERVAR** |

### 2.6 Orquestração e integrações

| Componente | Classificação |
|---|---|
| Daemon FastAPI (unix socket: /query, /query_audio, /speak, /status, /audiobook/pause/resume) | **REIMPLEMENTAR** em módulo novo (mesmo contrato) |
| IPC file-based (gemini/claude outbox) + neural-coordinator | **DEPRECAR** (fora do local-first) — substituir por sockets próprios se necessário |
| Self-healing (`self-healing.sh`, `self-healing-jarvis.py`) | **ADAPTAR** (com moderação, observável) |
| Indexer em tempo real (`inotify-indexer.sh`) | **ADAPTAR** |
| Alarmes (morning/sleep + timers) | **PRESERVAR** (nixos timers nativos) |
| Waybar/status (`/tmp/jarvis-status.json`) | **ADAPTAR** |
| Claude Code / Gemini CLI auto-responders | **DEPRECAR** — dev-tools, não fazem parte do sistema local |
| `pi` (agente atual do NixOS) | **ADAPTAR** — manter como CLI do novo core |
| `AI_AIRLOCK` | **PRESERVAR como processo** (docs/prompts), não como diretório vazio |

## 3. Dependências por componente (para o plano Nix)

| Runtime | Necessário | Nixpkgs 24.11? | Observação |
|---|---|---|---|
| llama.cpp | LLM + embeddings + vision (GGUF) | ✓ (build 4154, velho) | usar nixpkgs-unstable (10273 já em uso) |
| Qdrant | vector DB | ✓ (services.qdrant 1.12.1) | nativo |
| faster-whisper | STT | ✓ (python-modules) | avaliar whisper-cpp p/ CPU |
| kokoro-onnx | TTS | ✗ 24.11 | package custom ou unstable (verificar) |
| openwakeword | wakeword | ✗ 24.11 | package custom (já feito no módulo atual) |
| piper | TTS alternativo | ✓ | reserva |
| RiveScript (python) | fast paths | ✓ (python3Packages.rivescript) | verificar |
| scikit-learn | TF-IDF router | ✓ | |
| chromadb | — | ✓ | **não usar** (migrar p/ Qdrant) |
| numpy | — | ✓ | só temporariamente (migração) |

## 4. Diferenças legado vs sistema atual (resumo)

| Dimensão | Legado (Manjaro) | Atual (NixOS lab) |
|---|---|---|
| Runtime LLM | Ollama (0.13) | llama.cpp (10273) ✓ |
| Vector DB | NumPy + ChromaDB | Qdrant (vazio) ✓ |
| Wakeword | openwakeword + pipeline completo | módulo quebrado, sem pipeline |
| STT/TTS/Vision | faster-whisper + XTTS/Kokoro + moondream | inexistente |
| RAG | indexador Ollama+NumPy | inexistente |
| Memória | episódica + sessão + atenção | inexistente |
| Agentes externos | Claude/Gemini + LiteLLM + keys free-tier | só `pi` (llama.cpp) |
| Config | sprawl (6+ YAML/JSONC) + hardcoded paths | declarativa, mas com débito (bak, hosts stale) |
| GPU | RTX 4050 (cuda 13) | VM sem GPU (config declarativa p/ bare metal) |
| Release | Manjaro (rolling) | NixOS 24.11 **EOL** |

## 5. Riscos técnicos

1. **NixOS 24.11 EOL** — base insegura; upgrade (25.11 ou 26.05) é pré-requisito de hygiene, mas muda flake/stateVersion (fazer em fase dedicada).
2. **Áudio na VM**: sem mic (sem GPU-P e provavelmente sem device de captura) — wakeword/STT não testáveis de ponta-a-ponta na VM; mitigar com testes unitários (VAD/RMS), fixtures de áudio e hardware real no host.
3. **GPU**: arquitetura precisa de condicionais VM/bare metal (já existe padrão no llama-cpp.nix); RTX 4050 tem 6 GB VRAM → Qwen 7B Q4 cabe parcialmente (`-ngl` parcial), 32B só CPU/parcial.
4. **Modelos**: 32B GGUF (19,9 GB) já baixado na VM — reuso no bare metal via cópia/disko; download no runtime é frágil (mover para provisionamento verificável).
5. **Secrets**: API keys do legado em texto plano — rotacionar, nunca migrar.
6. **LLM-para-LLM** (meta-router usa LLM p/ decidir executor): latência + dependência externa — substituir por regras determinísticas.
7. **Pacotes fora do nixpkgs 24.11** (kokoro-onnx, openwakeword) — exigem package custom; manter em nixpkgs-unstable onde possível.
8. **Chave do cache `nixos-cuda.org` incorreta** na config atual — builds CUDA podem estar sem cache.
9. **RiveScript 1649 ln** acoplado a shell calls — portar com cuidado, testando macro a macro.
10. **Memória de sessão em /tmp** (volátil) — reimplementar persistente; comportamento antigo de perda de contexto não deve ser "preservado".
