# Arquitetura nova — Proposta (Fase 4)

> Baseada nas auditorias (docs/baseline.md, docs/audit/*).

## Status de implementação (2026-08-16)

- ✅ **Fase 0** — docs de auditoria commitados; limpeza de código morto (hosts stale, .bak, porta 11434, tmpfiles ollama); cache nixos-cuda corrigido; README/rebuild.sh atualizados.
- ✅ **Fase 1** — base migrada para **NixOS 26.05** (24.11 era EOL); avaliação validada (`nixos-system-nixos-lab-26.05.20260814`); fixes de compat (stylix base16/bright-yellow, nerd-fonts, python3Packages, git settings, zsh initContent, greetd tuigreet, openwakeword format). **Aguardando rebuild do usuário.**
- ✅ **Fase 3 (scaffold)** — pacote `jarvis` em `modules/ai/jarvis` (pyproject + src-layout): `core` (config env-driven, classificador de intenções TF-IDF puro NumPy porta do legado), `providers` (LLMClient OpenAI-compat p/ llama.cpp, QdrantStore REST, interfaces de voz), `cli` (intent/status/chat/rag). Empacotado via `modules/ai/package.nix` + overlay (`pkgs.jarvis`), exposto como `nix build .#jarvis`/`nix run .#jarvis`; pytest roda no checkPhase. Validado contra llama.cpp e Qdrant vivos na VM (chat responde, status ok; embeddings exigem `--embeddings` no servidor — Fase 4).
- ✅ **Fase 4 (RAG sobre Qdrant)** — `core/rag.py` (porta fiel do `extract_facts`/regex/STOP_SYMBOLS V4.0.5, indexador híbrido dense+sparse BM25+payload, busca híbrida nativa do Qdrant com prefetch+RRF ponderado no dense e re-rank com os boosts V4.0.5: extensão alvo, filename sovereignty, palavra em filename/path); `core/legacy_index.py` (loader `.ai-index` + busca legada pura NumPy = ground-truth + migração one-shot + `parity_report`); CLI `jarvis index|migrate|parity`; `providers/vector_store.py` com vetor nomeado `dense`+`bm25` e `search_hybrid` (filtro por `payload.ext` nos prefetches). Servidor dedicado de embeddings (`services.llama-cpp-embeddings`, porta 8081, nomic-embed-text-v2-moe Q8, `--embeddings --pooling mean`; `-b/-ub 4096` p/ rich_content; `JARVIS_EMBED_BASE_URL` separado do chat). **Validado na VM**: migração do `.ai-index` legado real (4617 docs) para o Qdrant e **paridade top-5 vs legado com overlap médio 0.87** (9/10 queries ≥ 0.8, critério ≥ 0.8); indexação do repo (17 arquivos) e `jarvis rag` ponta-a-ponta (filename sovereignty e busca semântica corretas). 52 testes unit + 6 integração verdes; `nix build .#jarvis` OK. **Pendência**: rebuild do usuário para subir `llama-cpp-embeddings` como serviço systemd e consertar o Qdrant (storage corrompido pela troca 1.12→1.17 — limpar `/var/lib/private/qdrant/storage`).

## 1. Princípios (herdados da missão)

- Declarativo, reproduzível, modular, testável; local-first e offline-capable.
- Sem estado em `~/.config`; aplicação ≠ configuração NixOS.
- Fast paths determinísticos antes de LLM; LLM só quando necessário.
- Nenhum acoplamento do core a Qdrant/llama.cpp/Whisper/TTS/OS — interfaces pequenas nos adapters.
- VM é o laboratório; bare metal (Acer Nitro ANV15-51, i7-13620H, 32 GB, RTX 4050) é o alvo final com disko.

## 2. Decisões tecnológicas (com pesquisa 08/2026)

| Decisão | Escolha | Justificativa / fonte |
|---|---|---|
| LLM runtime | **llama.cpp** (nixpkgs-unstable; já 10273 em uso) | Mandato. `llama-server` com API OpenAI-compatível, tool calling nativo (docs/function-calling.md), `--embeddings` e visão (moondream GGUF) no mesmo runtime. Módulo oficial `services.llama-cpp` existe no nixpkgs 24.11 — **usar como base** (opções enable/package/model/extraFlags/port) e preservar o provisionamento de modelo como etapa separada. |
| Multi-modelo | Perfil VM/bare metal já existente; futuramente 2 servidores (chat + embeddings) ou `llama-swap` | Sem necessidade agora; documentar como evolução. |
| Vector DB | **Qdrant** (services.qdrant nativo, 1.12.1 em uso) | Mandato. Hybrid search nativo (dense + sparse BM25/SPLADE, RRF, prefetch, Universal Query API) — mapeia 1:1 o algoritmo híbrido do legado (semântico + símbolos + filename). |
| Embeddings | **nomic-embed-text-v2** (137M, MIT, ctx 8192) via llama.cpp `--embeddings`; avaliar **bge-m3** (multilingue, dense+sparse) se o corpus PT-BR exigir | Pesquisa 2026: nomic-embed-v2 é o padrão local leve; bge-m3 melhor para multilíngue/híbrido. Decisão final com benchmark contra o índice NumPy existente (teste de paridade). |
| STT | **faster-whisper** (nixpkgs) como no legado; whisper.cpp como candidato CPU-only na VM | Legado validou faster-whisper (small, int8); whisper.cpp pode ser mais rápido em CPU. |
| TTS | **Kokoro** (kokoro-onnx) como primário — XTTS (Coqui) **não** migrar (projeto descontinuado) | Pesquisa 2026: Kokoro 82M é o melhor custo/qualidade local (CPU, PT-BR via misaki); vozes af_sky etc. já configuradas no legado. |
| Wakeword | **openwakeword** (hey_jarvis onnx) — package custom Nix | Mantido (MIT, offline, ativo na comunidade HA); Porcupine free-tier morreu em 06/2026. Device de áudio via **PipeWire** (sem `hw:1,7`). |
| Intent/fast path | **RiveScript** (brain/*.rive) + **TF-IDF** determinístico | Mandato "fast path": rota determinística (wakeword → comando conhecido → ação) sem LLM. Fallback LLM só p/ desempate. |
| Executor decision | **Regras determinísticas** (intent → executor/modelo) em vez de LLM-meta-router | Elimina LLM-para-LLM e dependência de nuvem (risco #6 da auditoria). |
| Externos | **Nenhum no core** (sem LiteLLM/Groq/Gemini/Claude) | Local-first. Claude Code/Gemini CLI ficam como ferramentas dev separadas (DEPRECAR no sistema). |
| Memória | Episódica em **Qdrant** (coleção `memories`: texto, timestamp, origem, confiança, relevância, retention) + sessão persistente em `~/.local/state/jarvis/` | Legado usava JSONL keyword-match e `/tmp`; upgrade explícito. |
| Estado | `~/.local/state/jarvis/` (XDG_STATE_HOME) para runtime; modelos em `/var/lib` (módulo oficial llama-cpp tem `ProtectHome`) | Separação estado/configuração. |
| NixOS | **Upgrade de base** (decisão: 25.11 ou 26.05 — 24.11 é EOL desde 2025-12) em fase dedicada | eosl.date/2026: 26.05 "Yarara" é a estável atual; 25.11 EOL 2026-06-30. |

## 3. Estrutura alvo do repositório

```
flake.nix                      ← inputs: nixpkgs (pós-upgrade), nixpkgs-unstable, home-manager, stylix
hosts/
  nixos-lab/                   ← VM (validação)
  (anv15-51/ futuramente)      ← bare metal com disko (só após validação)
nixos/modules/                 ← base (limpa)
modules/services/
  llama-cpp.nix                ← usar services.llama-cpp nativo + serviço de provisionamento de modelo
  qdrant.nix                   ← nativo (remover duplicação do import dinâmico)
  jarvis.nix                   ← daemon JARVIS (backbone)
modules/ai/                    ← pacote Python `jarvis` (overlay/callPackage)
  core/        router, intents, fast_path, memory, tools
  providers/   llama (chat/embed), qdrant, whisper, kokoro, wakeword, vision
  daemon/      FastAPI unix-socket (contrato do legado: /query, /query_audio, /speak, /status)
  cli/         jarvis-cli, pi, audiobook-reader
  tests/       pytest: unit + integração (qdrant, llama, áudio fixtures)
home-manager/modules/
  services/jarvis-wakeword.nix ← corrigido (package correto + pipeline)
  services/jarvis-daemon.nix   ← user service do daemon
docs/        baseline, audit/*, decisions/, migration/, testing/
state (não versionado)  ~/.local/state/jarvis/
```

## 4. Fluxo-alvo (comportamento preservado)

```
wakeword (openwakeword, PipeWire)
  → gravação VAD (RMS relativo, cooldown, kills TTS/audiobook)
  → STT (faster-whisper)
  → ROTEAMENTO:
      1. pipeline multi-step (detector determinístico)
      2. fast path RiveScript (macros: system/git/file/vision/math/time/audiobook/voice)
      3. intent TF-IDF (SYSTEM/CODING/VISION/CHAT)
      4. executor: regras (LOCAL/llama.cpp) + RAG (Qdrant dense+sparse) + memória episódica
  → TTS Kokoro (emoção via emoji, pt/en, lock anti-overlap, prebuffer)
  → feedback: status file + notify + waybar
Observabilidade: journal + /status + métricas simples (latência por estágio, contadores)
```

## 5. Plano incremental (cada fase: investigar → documentar → mudança mínima → implementar → testar → revisar → registrar; commits pequenos e semânticos)

**Fase 0 — Baseline e higiene estrutural (documentação + commits isolados)**
- `docs/` baseline + auditorias (este trabalho) — commit `docs(audit): baseline and audit reports`.
- Remover backups commitados (flake.nix.bak*), hosts stale (slim3, 330-15ARR, nixos-lab/slim3), porta 11434, tmpfiles ollama — commits separados `chore: remove verified dead config`.
- Corrigir chave do cache `nixos-cuda.org`; corrigir/remover `rebuild.sh` (sem commit automático); atualizar README.

**Fase 1 — Base NixOS (decisão com usuário)**
- Decidir 25.11 vs 26.05; upgrade do flake; `nix flake check` + `nixos-rebuild` na VM; corrigir breaking changes.

**Fase 2 — Serviços de IA base**
- Consolidar `llama-cpp` no módulo oficial nixpkgs + serviço de provisionamento de modelo (download com hash, dir `/var/lib/llama-cpp`); manter overlay unstable.
- Qdrant: remover duplicação, definir política de coleções.
- Smoke: `/health` llama + Qdrant API.

**Fase 3 — Pacote Python `jarvis` (scaffold)**
- `pyproject.toml`, layout core/providers/daemon/cli, `pytest` rodando no Nix (`nix build .#jarvis` / shell).
- Interface `VectorStore`, `LLMProvider`, `STTProvider`, `TTSProvider`, `WakewordProvider` (adapter mínimo, sem implementações).

**Fase 4 — Conhecimento (RAG) sobre Qdrant**
- Provider de embeddings (llama.cpp `--embeddings`, nomic-embed-text-v2).
- Indexador híbrido: dense + sparse BM25 + payload (path/facts/symbols/filename) — espelho do algoritmo legado V4.0.5.
- **Script de migração one-shot** do índice NumPy (`.ai-index/*.npy` + `global_meta.json` + `symbols.json`) para Qdrant, com **teste de paridade** (top-k do legado vs novo).
- `rag_query.py` reimplementado como CLI do pacote.

**Fase 5 — Memória**
- Coleção `memories` (episódica: task/error/fix/timestamp/origem/confiança) + retrieval semântico — substitui `experience_buffer.py`.
- Sessão persistente (`~/.local/state/jarvis/session.json`) com atenção/sliding window — substitui `session_memory.py` (que usava `/tmp`).
- Testes: escrita/recuperação/expiração.

**Fase 6 — Fast paths (RiveScript)**
- Portar `brain/*.rive` + `rivescript_router.py` com runtime Nix (sem shell calls hardcoded; tools via adapters).
- Macro a macro com testes (system, git, file, vision, math, time, audiobook, voice).

**Fase 7 — Router**
- `routing_engine` novo: pipeline → fast path → intent TF-IDF → executor por regras + RAG + memória. Testes com fixtures (incl. `intent_benchmark.py` do legado).

**Fase 8 — Percepção (wakeword + STT)**
- Package custom `openwakeword` (corrigir build do módulo atual) + daemon com captura via PipeWire (dispositivo por config, não hardcoded).
- STT faster-whisper com VAD params do legado; fixtures de áudio para testes unitários; smoke na VM (sem mic: testar com áudio sintético).

**Fase 9 — Resposta (TTS Kokoro)**
- Package `kokoro-onnx` (24.11 não tem; unstable ou package custom) + modelos (kokoro-v1.0.onnx, voices.bin) provisionados.
- Emoção/speed, detecção pt/en, lock anti-overlap, prebuffer — herdados do daemon legado.

**Fase 10 — Daemon + CLIs**
- `jarvis.nix` (daemon FastAPI unix-socket, contrato legado) + `jarvis-daemon.service` (user).
- CLIs: `jarvis-cli`, `pi` (adaptar), `jarvis-status`, alarmes (timers nixos).
- Integração wakeword→daemon→TTS de ponta-a-ponta (testável via sockets).

**Fase 11 — AudiobookReader modernizado**
- `book_extractor`/`book_indexer` portados; ChromaDB→Qdrant (coleção `books`); `enhanced_audiobook.py` refatorado (TTS via provider, estado em `~/.local/state`).
- Testes: extração PDF/EPUB, chunking, progresso %, pause/resume.

**Fase 12 — Vision + observabilidade + self-healing mínimo**
- Vision: screenshot/OCR + moondream GGUF via llama.cpp (provedor).
- Métricas de latência por estágio, `/status`, logs estruturados.
- Self-healing restrito a restart de serviços do sistema (systemd nativo).

**Fase 13 — Validação na VM e preparação bare metal**
- Suíte de integração completa rodando na VM (Qdrant + llama.cpp + pacote jarvis).
- `nix flake check`, `nixos-rebuild test/switch` na VM, rollback testado (btrfs).
- Só então: host `anv15-51` com disko (btrfs, NVIDIA declarativa já presente), modelos copiados, validação de GPU offload.

## 6. Critérios de aceite (por fase, resumo)

- RAG: paridade top-k vs índice NumPy legado (≥ 80% overlap nos primeiros 5).
- Fast path: latência < 300 ms; respostas idênticas aos .rive do legado nos casos de teste.
- Wakeword→TTS: smoke com áudio sintético na VM (sem mic); validação real no host.
- Memória: persistência entre reinícios (nada em /tmp).
- `nix flake check` verde; nenhum teste declarado sem execução.
