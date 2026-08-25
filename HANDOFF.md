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

Todos os serviços Jarvis são controlados por `services.jarvis.enable` (toggle global) e `jarvis.target` (systemd target mestre).

| Serviço | Porta | Estado | systemd | Observação |
|---------|-------|--------|---------|------------|
| llama-cpp-server | 8080 | ✅ Rodando | PartOf jarvis.target | Qwen3.6-35B MoE, 128K ctx |
| llama-cpp-embeddings | 8081 | ✅ Rodando | PartOf jarvis.target | nomic-embed-text-v2, CPU |
| llama-cpp-rerank | 8082 | ✅ Rodando | PartOf jarvis.target | bge-reranker-v2-m3, CPU |
| qdrant | 6333 | ✅ Rodando | PartOf jarvis.target | Vector DB |
| jarvis-gaming-watcher | — | ✅ Rodando | PartOf jarvis.target | Detecção multi-sinal |
| jarvis-idle | — | ✅ Rodando | — | Self-knowledge |
| jarvis-heal | — | ✅ Ativado | PartOf jarvis.target | Self-heal com MAX 5 restarts |
| jarvis-telegram | — | ⏳ Pendente | — | Precisa criar bot + env file |
| litellm | 4000 | ✅ Rodando | — | Cascade local → Groq → Gemini → OpenRouter |

## Configuração llama-cpp (Host)

```
Modelo:     Qwen3.6-35B-A3B MoE (UD-Q4_K_M, ~20.6GiB)
GPU layers: ngl=50 (atenção na GPU)
MoE:        n-cpu-moe=50 (experts na RAM)
Contexto:   131072 tokens (128K, KV cache q4_0)
Threads:    16
VRAM:       ~4.2GB / 6GB (mmproj em CPU)
RAM livre:  ~27 GB
Flags:      --no-mmproj-offload --reasoning-preserve --jinja
```

**Performance medida (benchmark.sh, 5 runs com warmup)**:
- Prefill: ~367 t/s
- Decode: ~32 t/s (estável, 0.7% drift)
- Descoberta: mmproj na GPU causa degradação 32→14 t/s após 1º request
  (solução: --no-mmproj-offload mantém mmproj em CPU, libera 900 MiB VRAM)

## Testes — USE `nix develop`

```bash
# ✅ CORRETO — provisiona jarvis + pytest + hypothesis + PYTHONPATH:
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# ❌ ERRADO — nix-shell com pacotes soltos não tem dependências do jarvis:
# nix-shell -p python3Packages.pytest python3Packages.requests --run "pytest ..."
```

| Categoria | Quantidade | Status |
|-----------|------------|--------|
| Unitários (sem numpy) | ~500 | ✅ Passando |
| Integração (llama+qdrant) | 4 | ✅ Passando |
| E2E Agent (live) | 10 | 4/10 tools usadas |
| PBT (hypothesis) | 31 | ✅ Passando |
| Security | 6 | ✅ Passando |
| Fuzzing/Mutation | 56 | ✅ Passando |
| Sem numpy (voice/wakeword) | 4 | ❌ Falta numpy |
| Bulldozer (jarvis dev) | 6 | ⏳ Precisa CLI |
| Devtools (pós-refactor) | 9 | ✅ Passando |
| **Total executável** | **~500+** | **✅ Passando** |

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
- `core/agent.py` — Agente com tool-calling (11 ferramentas + output truncation + duplicate detection)
- `core/router.py` — Roteamento em cascata (fastpath → doctor → nixos → rag → agent)
- `core/rules.py` — Motor de regras declarativas (substitui RiveScript)
- `core/rag.py` — RAG híbrido (dense + sparse BM25 + RRF + rerank, chunk 2000, mtime cache)
- `core/memory.py` — Memória episódica (Qdrant: remember/recall/lessons/forget)
- `core/vault.py` — Memória de longo prazo (markdown git-syncado)
- `core/voice.py` — STT (faster-whisper) + TTS (Kokoro-82M)
- `core/heal.py` — Self-heal (restart + audit JSONL + lesson, MAX 5 restarts, post-restart verify)
- `core/doctor.py` — Health checks (9 verificações, HTTP check, pgrep -x)
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

### Serviços NixOS (todos com mkIf services.jarvis.enable + PartOf jarvis.target)
- `nixos/modules/jarvis-env.nix` — Master toggle + jarvis.target
- `services/llama-cpp.nix` — llama.cpp (server + embeddings + rerank)
- `services/qdrant.nix` — Qdrant vector DB
- `services/jarvis-heal.nix` — Self-heal daemon (MAX 5 restarts)
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

## Achados da Auditoria Code-First (agosto/2026)

### CORRIGIDO NESTA SESSÃO
- **execute_shell duplicado** — tool existia em agent.py E devtools.py. Removido de devtools.py.
- **Sem output truncation** — execute_shell retornava stdout inteiro (MB). Adicionado TOOL_OUTPUT_MAX_CHARS=8000.
- **Sem duplicate detection** — modelo podia chamar mesma tool infinitamente. Adicionado tracking + warning após 3x.
- **RAG chunk 300→2000** — embeddings perdiam contexto com chunks muito pequenos.
- **RAG sem change detection** — re-indexava tudo sempre. Adicionado mtime cache.
- **Self-heal sem max restarts** — loop infinito de restart possível. Adicionado MAX_RESTARTS=5.
- **Self-heal sem verify** — systemctl retornava 0 mas serviço podia não subir. Adicionado polling pós-restart.
- **Doctor pgrep -f muito amplo** — trocado para pgrep -x (match exato).
- **Doctor check_network frágil** — socket 1.1.1.1:53 bloqueável. Trocado para HTTP check.
- **Memory dedup agressiva** — chave 200 chars causava falsos positivos. Aumentado para 500.
- **RAG sparse_terms sem acentos** — regex [a-zA-Z0-9_] descartava PT-BR. Trocado para \w+.

### Pendências que continuam
- **RAG code_index** — collection NÃO EXISTE no Qdrant (nunca indexado)
- **Thinking overhead** — 88% dos tokens no aider são thinking

### Código morto/legado
- `agent.py.bak` — backup no código ativo (remover)
- `rag.py.bkp` — backup na raiz (remover)
- `legacy_index.py` — requer numpy, 4 testes falham

## Pendências Reais

### Críticas
1. **RAG não indexado** — executar `jarvis rag index` para criar `code_index`
2. **Telegram não ativado** — precisa criar bot no BotFather + `/etc/jarvis-telegram.env`

### Importantes
3. **Limpar legado** — remover agent.py.bak, rag.py.bkp
4. **Validar voz/wakeword no host** — implementado mas não testado E2E
5. **sudo ALL NOPASSWD** — temporário, precisa minimizar

### Melhorias
6. **Forçar tool calling** — testar tool_choice: required no Agent
7. **Proxy thinking** — interceptar aider para desabilitar thinking
8. **Vision no host** — validar grim/slurp no Hyprland real
9. **Push para remote** — remote configurado mas sem autenticação SSH/token

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
8. **services.jarvis.enable** — toggle global com mkIf + jarvis.target
9. **rebuild-host.sh** — sempre validar com nix eval antes do switch
10. **Self-heal MAX 5 restarts** — nunca loops infinitos de restart

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
