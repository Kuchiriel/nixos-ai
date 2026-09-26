# nixos-ai

Configuração NixOS declarativa e reprodutível com sistema de IA local integrado.

**Hardware**: Acer Nitro V15 (RTX 4050 6GB / 32GB RAM) + VM de laboratório (CPU puro).

**Stack principal**: NixOS 26.05 + llama.cpp + Qdrant + Python 3.13 + Hyprland.

> 👋 **Trazendo p/ outra máquina?** Comece por [Instalação](#instalação)
> (VM primeiro, sem wipe) + [`docs/SECRETS.md`](docs/SECRETS.md) (onde
> mora cada chave) + `jarvis hwprofile` (qual modelo cabe no teu hardware).

---

## Estado do Sistema

| Componente | Estado | Evidência |
|-----------|--------|-----------|
| NixOS declarativo (hosts, módulos, services) | ✅ Funcional | `nix flake check` passa; 2 hosts: `nitro-v15` (bare metal) e `nixos-lab` (VM) |
| Modelos declarativos (fetchurl + hash) | ✅ Funcional | `modules/ai/models.nix` — 9 modelos com hash verificado |
| llama.cpp (host, CUDA) | ✅ Funcional | Ternary-Bonsai-8B Q2_0 via PrismML (2.15GB, 71.6 t/s TG) |
| llama.cpp (VM, CPU) | ✅ Funcional | Qwen3-4B Q4_K_M (2.5GB) |
| Qdrant (vetores) | ✅ Funcional | Módulo NixOS declarativo, `enable = true` |
| Embeddings (nomic) | ✅ Funcional | nomic-embed-text-v2-moe Q8_0 (512MB, CPU) |
| Reranker (bge) | ✅ Funcional | bge-reranker-v2-m3 Q4_K_M (438MB, CPU) |
| CLI (`jarvis`) | ✅ Funcional | ~40 subcomandos: status, ask, agent, rag, doctor, heal, voice, etc. |
| Agent (tool-calling) | ✅ Implementado | allowlist + aprovação + audit JSONL; testes unitários passam |
| Agent Runtime Kernel | ✅ Funcional | 1 loop cognitivo (`jarvis/runtime/`), adapters finos, linter anti-drift; ver `docs/audit/RECONSTRUCTION-REPORT.md` |
| MCP server (jarvis-mcp) | ✅ Implementado | 33 tools: shell, files, browser (CDP headless), vision, NixOS, memory, vault, RAG |
| RAG híbrido (Qdrant) | ✅ Implementado | dense + sparse BM25 + RRF + reranker; `jarvis rag` / `jarvis index` |
| Memória episódica | ✅ Implementado | `jarvis remember` / `jarvis recall` via Qdrant |
| Vault (markdown) | ✅ Implementado | `jarvis vault summarize` / `jarvis vault list` |
| Doctor (diagnóstico) | ✅ Funcional | `jarvis doctor` — verifica llama.cpp, Qdrant, rede, sockets |
| Heal (auto-reparo) | ✅ Implementado | `jarvis heal` — restart allowlist, cooldown, lição na memória |
| Telegram bot | ✅ Implementado | long-polling, `/ask` `/agent` `/status` |
| Dev agent (REPL) | ✅ Implementado | `jarvis dev` — ferramentas de código, modos customizáveis |
| Circuit breaker + fallback remoto | ✅ Implementado | CLOSED/OPEN/HALF_OPEN; filtro de segurança para dados sensíveis |
| Event bus (asyncio) | ✅ Implementado | pub/sub por tópico, retry, DLQ, stats; integrado no harness, idle, heal |
| Vision (screenshot) | ✅ Implementado | grim/slurp (Wayland); `jarvis screenshot full\|region\|window` |
| Triggers (automações) | ✅ Implementado | disk/cpu alerts com cooldown e idempotência |
| Segurança (anti-chaining) | ✅ Implementado | shlex.split, DANGEROUS_CHAINING, DANGEROUS_COMMANDS, safe pipes |
| Property-based tests (hypothesis) | ✅ Funcional | 31 testes adversariais para parsers e regex |
| Fuzzing + mutation testing | ✅ Funcional | 56 testes de stress |
| Nightwatch (loop autônomo) | ✅ Funcional | supervisor com branch isolation + review + checkpoint + loop de auto-melhoria (`scripts/loop-close.py` + `overnight-loop.sh` com gate de revert) |
| Multi-agent / sub-agents | 🧪 Experimental | multi_agent.py com AgentPersona + Orchestrator + handoff via Event Bus; 14 testes; sem integração LLM real |
| Voz (STT/TTS/wakeword) | ✅ Funcional | faster-whisper (morno ~1s) + Kokoro + openwakeword + modo fique-acordado; `jarvis voice`, `jarvis speak`, `jarvis stt` |
| Audiobook | ✅ Implementado | audiobook.py com 27 testes — EPUB/PDF/TXT + OCR fallback + SFX + chapter detection + TTS (Kokoro) + LLM search |
| Obsidian / HackMD | ✅ Implementado | hackmd.py com 8 testes (token, headers, reports, API errors) |
| Multi-AI Reader | ✅ Implementado | multi_ai_reader.py com 8 testes (ChatGPT/Gemini/Claude dispatch, HTML extraction) |
| Emotion (detecção) | 🧪 Experimental | emotion.py — keywords, zero LLM; funcional para TTS prosódia |
| Idle mode (self-knowledge) | 🧪 Experimental | idle.py existe; modo idle com tarefas devidas; não validado em produção |
| Profiling de hardware | ✅ Funcional | `jarvis hwdetect` / `jarvis hwprofile` — detecta RAM/VRAM/CPU/GPU e calcula flags |
| Benchmarks | ✅ Funcional | benchmark.sh, eval-rag, regression; resultados em `logs/benchmark/` |
| Validação Nix multi-camada | ✅ Funcional | `scripts/nix-validate.sh` — sintaxe, avaliação, build, testes |

---

## O que é

nixos-ai é um monorepo que contém:

1. **Configuração NixOS** — módulos declarativos para 2 hosts (bare metal + VM)
2. **Sistema de IA local** — `jarvis`: CLI + MCP server + agent + RAG + memória
3. **Infraestrutura de harness** — nightwatch (autonomia), dev agent (REPL), modos customizáveis
4. **Scripts de operação** — rebuild, benchmark, validação, diagnóstico

O objetivo é ter um sistema de IA que funcione inteiramente local, de forma declarativa e reproduzível no NixOS.

---

## Arquitetura

```
flake.nix
├── hosts/nitro-v15/          ← Bare metal (RTX 4050, 32GB RAM)
├── hosts/nixos-lab/          ← VM (CPU puro)
├── modules/ai/
│   ├── models.nix            ← Fonte única de verdade dos modelos
│   ├── package.nix           ← Pacote Python (jarvis + jarvis-voice)
│   ├── jarvis/src/
│   │   ├── cli/              ← CLI: jarvis <subcommand>
│   │   ├── core/             ← Lógica: agent, rag, memory, heal, vision, voz, etc.
│   │   ├── runtime/          ← Kernel: 1 loop (AgentRuntime), registry, sessão, vereditos
│   │   ├── providers/        ← Adaptadores: llm, vector_store, telegram, mcp
│   │   └── mcp_server.py     ← MCP server (33 tools)
│   └── nightwatch/           ← Supervisor autônomo (queue, branches, review)
├── modules/services/         ← Serviços NixOS (llama-cpp, qdrant, telegram, etc.)
├── nixos/modules/            ← Módulos base (audio, hyprland, bluetooth, etc.)
├── home-manager/             ← Desktop (hyprland, waybar) + daemons IA
├── scripts/                  ← Operação (ver scripts/INDEX.md p/ o mapa)
└── docs/                     ← Arquitetura, auditorias, benchmarks (+ SECRETS.md)
```

---

## Modelos

Definidos em `modules/ai/models.nix` (fetchurl + sha256 verificado):

| Modelo | Uso | Tamanho | Host |
|--------|-----|---------|------|
| Qwen3-4B Q4_K_M | Chat (VM) | 2.5GB | CPU |
| Ternary-Bonsai-8B Q2_0_g64 | Chat (host) | 2.15GB | RTX 4050 |
| nomic-embed-text-v2-moe Q8_0 | Embeddings | 512MB | CPU |
| bge-reranker-v2-m3 Q4_K_M | Reranker | 438MB | CPU |
| Kokoro-82M | TTS | <1GB | CPU |
| faster-whisper-small | STT | ~500MB | CPU/iGPU |
| openwakeword v0.5.1 | Wakeword | ~10MB | CPU |

Troca de modelo: edite `modules/ai/models.nix` → `./rebuild-host.sh`.

---

## CLI

```bash
# Core
jarvis status                 # saúde de serviços
jarvis ask "pergunta"         # roteador: caminho mais barato
jarvis agent "tarefa"         # agente tool-calling
jarvis chat "pergunta"        # resposta direta via llama.cpp

# RAG
jarvis rag "busca"            # busca híbrida no código
jarvis index <dir>            # indexa diretório no Qdrant

# Diagnóstico
jarvis doctor                 # diagnóstico completo
jarvis metrics                # métricas dos logs JSONL
jarvis heal                   # auto-reparo

# Memória
jarvis remember "fato"        # grava na memória episódica
jarvis recall "busca"         # recupera eventos
jarvis lessons "erro"         # lições relevantes
jarvis vault summarize        # resumo de longo prazo

# Perfil
jarvis profile show           # mostra preferências
jarvis profile set tone friendly

# Voz
jarvis voice                  # loop STT → roteador → TTS
jarvis stt <wav>              # transcreve áudio
jarvis speak "texto"          # sintetiza voz

# Hardware
jarvis hwdetect               # detecta hardware
jarvis hwprofile              # calcula flags SOTA + melhor modelo

# Automação
jarvis screenshot full|region|window
jarvis triggers run|status

# Desenvolvimento
jarvis dev                    # REPL interativo com ferramentas de código
jarvis handoff --task "..."   # contexto para IAs web
jarvis telegram               # canal Telegram
```

---

## MCP Server (18 tools)

| Tool | Descrição |
|------|-----------|
| jarvis_execute | Executa comando shell |
| jarvis_read_file | Lê arquivo |
| jarvis_write_file | Escreve arquivo |
| jarvis_str_replace | Substitui string em arquivo |
| jarvis_capture_screen | Captura screenshot (grim/slurp) |
| jarvis_observe_screen | Analisa screenshot com vision |
| jarvis_nix_eval | Avalia expressão Nix |
| jarvis_nix_check | Verifica NixOS |
| jarvis_nix_search | Busca no nixpkgs |
| jarvis_read_chatgpt | Lê conversa compartilhada do ChatGPT |
| jarvis_remember | Grava memória episódica |
| jarvis_recall | Recupera memórias |
| jarvis_lessons | Busca lições relevantes |
| jarvis_vault_list | Lista notas do vault |
| jarvis_vault_write | Escreve nota no vault |
| jarvis_rag_search | Busca híbrida no RAG |
| jarvis_rag_index | Indexa código no Qdrant |

**Configuração Roo Dev**: `~/.config/VSCodium/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json`

---

## Custom Modes

### `.roomodes` (Roo Dev)

| Modo | Descrição |
|------|-----------|
| code | Editar código — edits cirúrgicos |
| architect | Projetar sistemas, trade-offs |
| nightwatch | Loop autônomo 24/7 |
| organizer | Organizar arquivos por conteúdo |
| research | Pesquisa web com citação |

### `.jarvismodes` (Jarvis REPL)

| Modo | Descrição |
|------|-----------|
| code | Default coding mode |
| architect | System design |
| nightwatch | Autonomous loop |
| organizer | File organization |
| research | Web research |

---

## Instalação

### Rota recomendada p/ outra máquina (sem wipe)

> Requisitos: NixOS 26.05 com flakes. Fora do NixOS, este repo não instala
> (é configuração de sistema, não app portátil). Sem chaves, tudo local
> funciona — chaves só p/ fallback remoto e Telegram (ver abaixo).
>
> ⚠️ **Não** dê `switch` p/ `nixos-lab` no teu hardware físico (é config
> de VM convidada). A ordem segura é: avaliar → testar em VM → adotar.

```bash
# 1. Clone (não precisa de chave p/ clonar)
git clone https://github.com/Kuchiriel/nixos-ai.git
cd nixos-ai

# 2. Avalie sem tocar no sistema (só build, nada ativa)
nix flake check
nix build .#jarvis         # pacote Python (CLI + MCP)

# 3. Teste numa VM NixOS convidada (seguro: nada do teu sistema muda)
#    Rode .#nixos-lab DENTRO da VM, nunca switch no teu host físico.

# 4. Segredos (só quando quiser fallback remoto/Telegram — ver docs/SECRETS.md)
sudo cp docs/secrets-templates/litellm.env.example /etc/litellm.env
sudo chmod 600 /etc/litellm.env && sudoedit /etc/litellm.env

# 5. Qual modelo cabe no teu hardware? (consultivo: ele sugere, tu decides)
jarvis hwdetect     # o que a máquina tem (RAM/VRAM/CPU/GPU)
jarvis hwprofile    # melhor modelo + flags (edite modules/ai/models.nix)

# 6. Validação (o sistema se verifica sozinho)
jarvis doctor       # 10 checks: LLM, embeddings, Qdrant, wakeword, disco...
jarvis ask "que dia é hoje"   # fumaça do roteador

# 7. REPL e agentes externos
jarvis dev          # REPL com ferramentas de código
# opencode: chaves de nuvem (opcional) entram sozinhas via
# opencode-auth-sync.sh a partir do env (GROQ_API_KEY, GEMINI_API_KEY...)
```

Adotar de verdade = criar teu próprio host (copiar `hosts/nixos-lab`
como base, ajustar `hardware-configuration.nix` + `models.nix` p/ teu
hardware) e só então `nixos-rebuild switch --flake .#teu-host`.

### VM de Laboratório

```bash
nixos-rebuild switch --flake .#nixos-lab
```

### Bare Metal (Acer Nitro V15)

> ⚠️ O disko apaga **completamente** os 2 NVMe. Faça backup antes.

```bash
# 1. Clone
git clone https://github.com/Kuchiriel/nixos-ai.git
cd nixos-ai

# 2. Edite device IDs em hosts/nitro-v15/disko.nix
#    ls /dev/disk/by-id/nvme-*

# 3. Disko (wipe completo)
sudo nix --extra-experimental-features 'nix-command flakes' \
  run github:nix-community/disko -- --mode disko --flake .#nitro-v15

# 4. Instalação
sudo nixos-install --flake .#nitro-v15

# 5. Reboot e login
sudo reboot

# 6. Pós-boot: variáveis de ambiente
sudo tee /etc/litellm.env > /dev/null <<'EOF'
GROQ_API_KEY=sua_chave
GEMINI_API_KEY=sua_chave
EOF
sudo chmod 600 /etc/litellm.env

sudo tee /etc/jarvis-telegram.env > /dev/null <<'EOF'
JARVIS_TELEGRAM_TOKEN=SEU_TOKEN
JARVIS_TELEGRAM_CHAT_ID=SEU_CHAT_ID
EOF
sudo chmod 600 /etc/jarvis-telegram.env

# 7. Validação
jarvis doctor
jarvis hwdetect
```

### Rebuild

```bash
./rebuild-host.sh          # rebuild com validação multi-camada
./rebuild-lab.sh           # rebuild da VM
nix build .#jarvis         # build do pacote Python
nix develop                # shell de desenvolvimento
```

---

## Testes

```bash
# Contagem de testes (reproduzível)
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -q --co 2>&1 | tail -1
# Resultado: ~1600 testes coletados

# Rodar todos
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -q

# Nightwatch E2E (27 testes com filesystem real)
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_nightwatch_real_e2e.py -v

# Validação Nix
nix flake check
```

**Categorias de testes** (100+ arquivos, ~1600 testes):
- Unitários (core, providers, CLI)
- Integration (MCP, RAG, memory)
- E2E (nightwatch, harness, real filesystem)
- Property-based (hypothesis — parsers, regex)
- Fuzzing + mutation (stress tests)
- Security (anti-chaining, command validation)
- Audiobook (OCR, SFX, chapters, TTS)
- Gaming (detection, toggle, services)

---

## Benchmarks

Resultados em `logs/benchmark/` e `docs/benchmarks/`.

```bash
./benchmark.sh --label baseline --repeat 5 --warmup    # benchmark E2E
./scripts/ncmoe-sweep.py                                # sweep de parâmetros MoE
```

**Hardware**: RTX 4050 6GB / 32GB RAM / NVMe Gen4+Gen3.

**Conhecido**:
- RTX 4050 6GB tem limitação de VRAM para modelos grandes
- Thermal throttling em sessions longas (controlado via thermald + fan profile)
- Bonsai 8B denso: full offload (`-ngl 99`), 2.15GB pesos + ~1.2GB KV 32K
- Vision descontinuada no host (sem mmproj p/ Bonsai; `observe_screen` inoperante)
- Throughput sustentado depende de thermal management

---

## Conhecido / Limitações

- **VRAM 6GB**: limita modelos a ~4B dense ou ~35B MoE com offload parcial
- **Thermal throttling**: sessions longas podem degradar performance; `thermald.service` + fan control ativos
- **Troca de modelo por hardware**: `jarvis hwprofile` SUGERE (não aplica sozinho) — o default mora em `modules/ai/models.nix`
- **Multi-agent**: task queue + LoopDetector existem sem orquestração real entre agentes
- **Obsidian/HackMD**: integração existe mas não foi testada end-to-end
- **Fallback remoto**: circuit breaker funcional mas fallback requer API keys configuradas (`docs/SECRETS.md`)
- **VM vs bare metal**: modelos e flags diferem entre hosts; configuração via `models.nix` profiles

---

## Documentação

- [`AGENTS.md`](AGENTS.md) — premissas e regras para IAs que trabalham no repo
- [`HANDOFF.md`](HANDOFF.md) — estado atual do sistema
- [`NIGHTLOG.md`](NIGHTLOG.md) — registro de manutenção autônoma
- [`docs/architecture/`](docs/architecture/) — proposta, avaliação, diagnóstico
- [`docs/benchmarks/`](docs/benchmarks/) — resultados de benchmark
- [`docs/audit/`](docs/audit/) — inventário e auditorias

---

## Roadmap

### Crítico
- [x] Validar nightwatch em execução autônoma real (primeira noite: 26/09, com gate de revert)
- [x] Testar voz (STT/TTS) end-to-end em produção (loop 2.4s, RC 0)
- [ ] Resolver thermal throttling em sessions longas

### Estabilidade
- [x] Testes unitários passam (~1600)
- [x] `nix flake check` passa
- [x] Circuit breaker funcional
- [x] Doctor + heal funcionais
- [ ] Estabilizar E2E tests (2 falhas pre-existentes em harness_e2e)
- [ ] Estabilizar test_memory (1 falha pre-existente)

### Integração
- [x] MCP server funcional (33 tools)
- [x] Roo Dev integration via .roomodes
- [x] Telegram bot funcional
- [x] Integrar wakeword com pipeline de voz completo
- [ ] Integrar Obsidian/HackMD com vault

### Capacidade
- [x] RAG híbrido funcional
- [x] Memória episódica funcional
- [x] Dev agent (REPL) funcional
- [ ] Multi-agent coordination
- [ ] Sub-agents especializados

### Otimização
- [x] Context management baseado em n_ctx real (32K)
- [x] Anti-loop detection no nightwatch
- [x] Failure classification + retry com backoff
- [ ] Otimização de throughput MoE (equilíbrio GPU/CPU)

### Experimental
- [ ] Audiobook reader
- [ ] Emotion detection para TTS
- [ ] Idle mode autônomo
- [ ] HackMD sync
- [ ] Monorepo git strategy

---

## Documentação Relacionada (Obsidian Graph)

| Documento | Descrição |
|-----------|-----------|
| [[HANDOFF]] | Index leve do projeto |
| [[AGENTS.md]] | Regras compartilhadas |
| [[BUFFY.md]] | Profile do agente |
| [[CONTEXT-ENGINEERING]] | Protocolo de contexto |
| [[NIGHTLOG]] | Log de manutenção |
| [[docs/architecture/system-overview]] | Arquitetura geral |
| [[docs/architecture/agent-harness]] | Harness de agentes |
| [[docs/JARVIS-MCU-PARITY]] | Paridade com Jarvis MCU |
| [[docs/benchmarks/README]] | Benchmarks |
