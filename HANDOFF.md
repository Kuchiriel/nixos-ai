# HANDOFF — Estado Atual do Sistema (agosto/2026)

## Resumo Executivo

JARVIS on NixOS é uma "ia de bordo" local-first rodando em Acer Nitro V15
(RTX 4050 6GB / 32GB RAM). O sistema está **funcionando no host físico** com
llama-cpp (Qwen3.6-35B MoE), Qdrant, RAG híbrido, memória episódica,
self-heal, modo idle, gaming profile e 533 testes verdes.

## Hardware

| Componente | Especificação | Estado |
|------------|---------------|--------|
| CPU | i7-13620H (6P+8E, 20 threads) | ✅ Funcionando |
| RAM | 32GB DDR5 | ✅ Funcionando |
| GPU | RTX 4050 6GB | ✅ Funcionando (CUDA) |
| iGPU | Intel UHD 770 | ✅ Funcionando (VA-API) |
| Storage | NVMe (Gen4 + Gen3) | ✅ Funcionando (Btrfs + LUKS) |

## Serviços Ativos

| Serviço | Porta | Estado | Observação |
|---------|-------|--------|------------|
| llama-cpp-server | 8080 | ✅ Rodando | Qwen3.6-35B MoE, 128K ctx |
| llama-cpp-embeddings | 8081 | ✅ Rodando | nomic-embed-text-v2, CPU |
| llama-cpp-rerank | 8082 | ✅ Rodando | bge-reranker-v2-m3, CPU |
| qdrant | 6333 | ✅ Rodando | Vector DB (memories + code_index) |
| jarvis-gaming-watcher | — | ✅ Rodando | Detecção multi-sinal |
| jarvis-idle | — | ✅ Rodando | Self-knowledge (benchmark/regression/eval-rag) |
| jarvis-heal | — | ⏳ Pendente | Precisa ativar como daemon |
| jarvis-telegram | — | ⏳ Pendente | Precisa criar bot + /etc/jarvis-telegram.env |
| litellm | 4000 | ✅ Rodando | Cascade local → Groq → Gemini → OpenRouter |

## Configuração llama-cpp (Host)

```
Modelo:     Qwen3.6-35B-A3B MoE (UD-Q4_K_M, ~20.6GiB)
GPU layers: ngl=50 (atenção na GPU)
MoE:        n-cpu-moe=50 (experts na RAM via --load-mode none)
Contexto:   131072 tokens (128K, KV cache q4_0)
Threads:    16 (decode) + 16 (batch)
VRAM:       ~4.8GB / 6GB (1.2GB margem)
Flags:      --no-warmup --prio 2 --prio-batch 3 --kv-unified --ctx-checkpoints 2
```

**Performance medida (benchmark.sh)**:
- Prefill: ~360 t/s
- Decode: ~32 t/s

## Testes

| Categoria | Quantidade | Status |
|-----------|------------|--------|
| Unitários | ~450 | ✅ Passando |
| PBT (hypothesis) | 31 | ✅ Passando |
| Security | 6 | ✅ Passando |
| Fuzzing/Mutation | 56 | ✅ Passando |
| Integração | ~90 | ✅ Passando |
| **Total** | **533** | **✅ Todos passando** |

## Arquitetura da IA

```
Trigger Word (wakeword)
    ↓
Fast Path / Rules (core/rules.py) — zero LLM
    ↓
Doctor (core/doctor.py) — zero LLM
    ↓
NixOS MCP (providers/mcp.py) — zero LLM
    ↓
RAG (core/rag.py) — embedding + BM25 + RRF + rerank
    ↓
Agent (core/agent.py) — LLM tool-calling
    ↓
Tools / MCP
    ↓
Memory (core/memory.py) — Qdrant episódica
    ↓
Self-Heal (core/heal.py) — restart + audit + lesson
    ↓
Validation (core/ast_guard.py) — AST check
```

**Caminhos que bypassam a LLM**: fastpath (regras declarativas), doctor (health checks), nixos (mcp-nixos read-only).

## Componentes Implementados

### Core AI
- `core/agent.py` — Agente com tool-calling (12 ferramentas)
- `core/router.py` — Roteamento em cascata (fastpath → doctor → nixos → rag → agent)
- `core/rules.py` — Motor de regras declarativas (substitui RiveScript)
- `core/rag.py` — RAG híbrido (dense + sparse BM25 + RRF + rerank)
- `core/memory.py` — Memória episódica (Qdrant: remember/recall/lessons/forget)
- `core/vault.py` — Memória de longo prazo (markdown git-syncado)
- `core/voice.py` — STT (faster-whisper) + TTS (Kokoro-82M)
- `core/heal.py` — Self-heal (restart + audit JSONL + lesson)
- `core/doctor.py` — Health checks (9 verificações)
- `core/benchmark.py` — Benchmark da cascata
- `core/eval_rag.py` — Avaliação de qualidade RAG (NDCG/Recall)
- `core/regression.py` — Teste de regressão
- `core/hwdetect.py` — Detecção de hardware
- `core/hwprofile.py` — Profile de otimização por hardware
- `core/idle.py` — Modo idle (self-knowledge)
- `core/user_profile.py` — Perfil de usuário dinâmico
- `core/emotion.py` — Estado emocional para TTS
- `core/audiobook.py` — Handler de audiobooks
- `core/devtools.py` — Ferramentas de desenvolvimento (estilo Aider)
- `core/circuit_breaker.py` — Circuit breaker (fallback remoto)
- `core/health_monitor.py` — Monitor de saúde
- `core/eventbus.py` — Barramento de eventos
- `core/triggers.py` — Triggers declarativos
- `core/vision.py` — Captura de tela
- `core/feedback.py` — Feedback ao usuário
- `core/logging.py` — Logging JSONL
- `core/config.py` — Configuração central (env-driven)
- `core/gaming.py` — Detecção de jogos (multi-sinal: GPU + Hyprland + Steam)
- `core/ast_guard.py` — Validação AST
- `core/ast_cache.py` — Cache de AST

### Providers
- `providers/llm.py` — Cliente LLM (OpenAI-compatible)
- `providers/vector_store.py` — Store vetorial (Qdrant)
- `providers/mcp.py` — Cliente MCP (mcp-nixos)
- `providers/reranker.py` — Reranker (bge-reranker-v2-m3)
- `providers/telegram.py` — Canal Telegram

### Serviços NixOS
- `services/llama-cpp.nix` — llama.cpp (server + embeddings + rerank)
- `services/qdrant.nix` — Qdrant vector DB
- `services/jarvis-heal.nix` — Self-heal daemon
- `services/jarvis-idle.nix` — Idle mode daemon
- `services/jarvis-telegram.nix` — Telegram bot
- `services/jarvis-vault.nix` — Vault summarization
- `services/jarvis-gaming.nix` — Gaming profile detection
- `services/litellm-cascade.nix` — LiteLLM cascade

### Home Manager
- `hyprland/` — Window manager (cyan borders, animations)
- `waybar.nix` — Status bar (GPU/CPU/Memory/Battery)
- `services/jarvis-wakeword.nix` — Wake word detection
- `mpvpaper.nix` — Animated wallpaper (iGPU VA-API)

## Pendências Reais

### Críticas
1. **Telegram não ativado** — precisa criar bot no BotFather + `/etc/jarvis-telegram.env`
2. **jarvis-heal como daemon** — implementado mas não ativado no lab/host
3. **Chave Groq vazada no git history** — usuário deve rotacionar

### Importantes
4. **Validar voz/wakeword no host** — implementado mas não testado E2E no hardware
5. **mpvpaper com VA-API** — funciona sem hwdec (iHD crash no NixOS)
6. **sudo ALL NOPASSWD** — temporário no host, precisa minimizar

### Melhorias
7. **Dashboard waybar expandido** — erros recentes, latência SLM
8. **Alertas Telegram** — notificar quando doctor detecta serviços down
9. **Event Bus daemon** — rodar como systemd user service
10. **Vision no host** — validar grim/slurp no Hyprland real

## Riscos

| Risco | Severidade | Mitigação |
|-------|------------|-----------|
| sudo ALL NOPASSWD | 🔴 Alto | Minimizar escopo no host |
| Serviços sem sandbox | 🟡 Médio | DynamicUser + ProtectSystem |
| --host 0.0.0.0 sem auth | 🟡 Médio | Firewall + auth no host |
| Sem backup/impermanence | 🟡 Médio | Definir estratégia no host |
| Chave Groq exposta | 🟡 Médio | Rotacionar |

## Decisões Consolidadas (NÃO reabrir)

1. **llama.cpp > Ollama** — declarativo, sem daemon desnecessário
2. **Qdrant > ChromaDB/NumPy** — production-ready, hybrid search nativo
3. **rules.py > RiveScript** — não está no nixpkgs, quebraria tese declarativa
4. **models.nix = única fonte de verdade** — nada de download imperativo
5. **KV cache q4_0** — eficiente para 128K contexto em 6GB VRAM
6. **n-cpu-moe 50** — experts na RAM, atenção na GPU
7. **Telegram > ntfy** — bidirecional + aprovação inline

## Comandos para Retomar

```bash
cd /home/nixos/nixos-ai

# Status rápido
git log --oneline -5
systemctl status llama-cpp-server qdrant

# Rebuild
./rebuild-host.sh

# Benchmark
./benchmark.sh

# Testes
nix build .#jarvis --no-link

# Logs
journalctl -u llama-cpp-server -f
journalctl -u qdrant -f

# VRAM
nvidia-smi

# Saúde
jarvis doctor
```
