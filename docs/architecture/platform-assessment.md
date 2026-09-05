# PLATFORM AUDIT — 2026-08-30

## Context

Based on ChatGPT's deep analysis of the nixos-ai repository, which identified that we were focusing too much on Nightwatch when the platform infrastructure needed attention first.

## Audit Scope

- Flake/NixOS evaluation graph
- Boot/kernel/initrd
- NVIDIA/CUDA/Wayland
- Systemd dependency graph
- Thermal/power management
- llama.cpp profiles and parameters
- VRAM/RAM budgeting
- Home Manager

## Findings

### P0 — Critical Issues

#### 1. Security: PermitRootLogin = "yes" ✅ FIXED

**Before:**
```nix
services.openssh = {
  enable = true;
  settings.PermitRootLogin = "yes";
};
```

**After:**
```nix
services.openssh = {
  enable = true;
  settings.PermitRootLogin = "prohibit-password"; # Segurança: login root só por chave SSH
};
```

**Impact:** Prevents password-based root login over SSH. Root can still login via SSH keys.

#### 2. Systemd Sandboxing ✅ FIXED

**Services hardened:**
- `jarvis-idle-worker`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=512M
- `jarvis-telegram`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=256M
- `nightwatch-timer`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=2G
- `llama-cpp-embeddings`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=512M
- `llama-cpp-rerank`: ProtectSystem=strict, PrivateTmp, NoNewPrivileges, MemoryMax=256M

**Note:** `llama-cpp-server` cannot be sandboxed because it runs as root and needs GPU access.

### P0 — Kernel Parameters Analysis

#### 1. `intel_idle.max_cstate=1` — ⚠️ REVIEW RECOMMENDED

**Purpose:** Limits CPU C-states to C1, reducing wake latency by 1-3% for decode.

**Pros:**
- Lower wake latency (CPU wakes faster from idle)
- May improve token generation speed slightly

**Cons:**
- Significantly increases power consumption
- Increases heat generation
- May contribute to thermal throttling

**Recommendation:** Consider removing unless freeze issues are observed. The thermal benefits of removing it may outweigh the 1-3% decode improvement.

#### 2. `pcie_aspm=force` — ✅ KEEP

**Purpose:** Forces PCIe Active State Power Management, reducing GPU idle power.

**Pros:**
- Reduces PCIe power consumption by ~40%
- Reduces heat generation from PCIe devices
- Helps with thermal management

**Cons:**
- Can cause system freezes on some hardware
- May cause WiFi disconnections

**Recommendation:** Keep this parameter. The thermal benefits are significant for a laptop with RTX 4050.

#### 3. `preempt=full` — ✅ KEEP

**Purpose:** Full preemption for linuxPackages_zen kernel.

**Analysis:** This is correct for the Zen kernel we're using. The comment in the code says "Preempção total do kernel Zen" which is accurate.

#### 4. `split_lock_detect=off` — ⚠️ REVIEW RECOMMENDED

**Purpose:** Disables penalties for split locks in AI workloads.

**Pros:**
- May improve AI workload performance

**Cons:**
- Hides potential hardware issues
- May cause data corruption in rare cases

**Recommendation:** Test without this parameter to see if AI workloads are affected.

#### 5. `nvme_core.io_timeout=10` — ⚠️ REVIEW RECOMMENDED

**Purpose:** More aggressive NVMe I/O timeout.

**Pros:**
- Faster error recovery

**Cons:**
- May cause data loss on slow I/O operations
- May cause filesystem corruption under heavy load

**Recommendation:** Consider increasing to 30 or removing entirely.

### P1 — llama.cpp Profiles

#### Current Profiles

| Profile | Model | Context | GPU Layers | MoE Flags | Use Case |
|---------|-------|---------|------------|-----------|----------|
| vm | Qwen3-4B | 131072 | 0 | None | Lab/VM |
| host | Qwen3.6-35B-A3B | 32768 | 45 | ncmoe=36 | Main server |
| host-ncmoe35 | Qwen3.6-35B-A3B | 32768 | 45 | ncmoe=35 | Faster variant |
| host-ehs | Qwen3.6-35B-A3B | 8192 | 45 | ehs=25 | Expert Hot Store |
| host-ehs-optimized | Qwen3.6-35B-A3B | 16384 | 45 | ehs=25 | Optimized EHS |

#### Issues Found

1. **Profile resolution at `let` block:** The `prof = pkgs.aiModels.profiles.${profileName};` is evaluated at module evaluation time, which could cause issues with lazy evaluation.

2. **Hardcoded VRAM budget:** The `ncmoe=36` is hardcoded, not calculated based on available VRAM.

3. **No profile for different use cases:** Roo Dev (large context), Chat (throughput), Jarvis (latency), Benchmark (reproducibility) all use the same profile.

#### Recommendations

1. **Create separate profiles for different use cases:**
   - `roo-dev`: Large context (32k+), parallel=2
   - `chat`: Maximum throughput, parallel=1
   - `jarvis`: Low latency, parallel=1
   - `benchmark`: Reproducible settings

2. **Dynamic VRAM budgeting:**
   ```nix
   # Calculate safe ngl based on available VRAM
   availableVram = 6144 - 2400; # Total - model size
   safeNgl = if availableVram > 4000 then 45 else 35;
   ```

### P1 — VRAM/RAM Budgeting

**Current State:**
- RTX 4050: 6GB VRAM
- Qwen3.6-35B-A3B: ~2.4GB model size
- KV Cache: depends on context size
- MoE experts: 36 on CPU, 9 on GPU

**Issues:**
1. No explicit VRAM budget calculation
2. Hardcoded `ncmoe=36` without considering available VRAM
3. No monitoring of actual VRAM usage

**Recommendation:**
```nix
# Create a VRAM budget module
let
  totalVram = 6144; # MB
  modelSize = 2400; # MB
  kvCacheSize = prof.ctxSize * 64 / 1024; # KB per token
  availableForExperts = totalVram - modelSize - kvCacheSize - 500; # 500MB safety
  expertsOnGpu = builtins.floor (availableForExperts / 100); # ~100MB per expert
in {
  gpuLayers = 45;
  moeFlags = "--n-cpu-moe ${toString (36 - expertsOnGpu)}";
}
```

### P1 — Systemd Dependency Graph

**Current State:**
```
jarvis.target
├── llama-cpp-server.service
│   └── after: network-online.target, qdrant.service
├── llama-cpp-embeddings.service
├── llama-cpp-rerank.service
├── qdrant.service
├── jarvis-idle-worker.service (user)
├── jarvis-telegram.service
└── nightwatch.timer
```

**Issues:**
1. No explicit dependency chain between services
2. No resource limits for most services
3. No sandboxing for llama-cpp-server

**Recommendation:**
```nix
# Add explicit dependencies
llama-cpp-server = {
  after = ["qdrant.service" "network-online.target"];
  requires = ["qdrant.service"];
  # Resource limits
  memoryMax = "8G";
  cpuWeight = 100;
};
```

### P1 — Home Manager

**Current State:**
- Complex module structure with many imports
- Inline scripts in some modules
- Generated files

**Issues:**
1. May be becoming a parallel OS
2. Some configurations duplicated between NixOS and Home Manager
3. Some paths may not be declarative

**Recommendation:**
- Audit all `home.file` and `xdg.configFile` usage
- Ensure all configurations are declarative
- Remove any inline scripts that could be replaced with packages

## Commits

```
f2ab9d2 fix(platform): security hardening + Systemd sandboxing
```

## Next Steps

1. **Test kernel parameter changes** — Remove `intel_idle.max_cstate=1` and monitor thermal behavior
2. **Create llama.cpp profiles** — Separate profiles for Roo Dev, Chat, Jarvis, Benchmark
3. **Implement dynamic VRAM budgeting** — Calculate ngl/ncmoe based on available VRAM
4. **Add explicit Systemd dependencies** — Ensure proper service ordering
5. **Audit Home Manager** — Ensure all configurations are declarative

## Validation

- [x] Security fix applied (PermitRootLogin)
- [x] Systemd sandboxing added to 5 services
- [ ] Kernel parameter changes tested
- [ ] llama.cpp profiles created
- [ ] VRAM budgeting implemented
- [ ] Systemd dependencies verified
- [ ] Home Manager audited

---
**Ver também:** [[../HANDOFF]] | [[../AGENTS.md]] | [[../README]]

---

# Avaliação de Arquitetura (2026-08)

> Original: [[architecture/system-assessment]]

# Avaliação de Arquitetura — JARVIS on NixOS (lab → host)

> Compilado em 08/2026, após a Fase 4 (RAG híbrido + embeddings + migração/paridade).
> Objetivo: ranquear a qualidade da stack atual, comparar com projetos similares,
> identificar gargalos e traçar o caminho até um sistema **local-first, NixOS-first,
> auto-curável (self-heal) e auto-evolutivo (self-improve)** que dispute com soluções pagas.

---

## 1. Ranqueamento da stack atual (0–10 por camada)

| Camada | Nota | Justificativa |
|---|---|---|
| **Declaratividade NixOS** | 9.5 | Flake com overlay único, módulos por serviço, imports dinâmicos, `nix build`/`flake check` verdes. **Fontes Python do JARVIS versionadas no repo** (`package.nix` usa `cleanSource ./jarvis`) — o host nasce com o binário via `systemPackages`. Requisito: tudo commitado (untracked não entra no build do flake). |
| **Adaptação lab→host** | 9.5 | **Centralização de Inteligência**: `modules/ai/models.nix` é a única fonte de verdade — declara os GGUFs (fetchurl, hash) e os **perfis** `vm`/`host` (modelo, threads, ctx, ubatch, GPU layers, KV-cache, MoE flags, scheduler). `llama-cpp.nix` só consome `pkgs.aiModels.profiles.<perfil>` via option `services.llama-cpp-server.profile` (declarativo por host — nada de detect-virt em runtime). |
| **RAG (Fase 4)** | 7.5 | Híbrido dense+sparse com RRF ponderado, `modifier: idf`, field boosting, paridade 0.9 vs legado, 58 testes. Falta: chunking por símbolo, reranker, eval formal. |
| **Serviços (llama-cpp ×3, Qdrant)** | 8.5 | systemd units com health-check no `postStart`, tmpfiles, usuário dedicado (qdrant). **Modelos 100% no store** (fetchurl com hash — sem download imperativo em runtime). Falta: `--host 0.0.0.0` sem auth, watchdog systemd. |
| **Pacote jarvis + testes** | 8 | `checkPhase` roda pytest no build Nix (qualidade garantida no store), testes unit+integração separados por marker, CLI coerente. |
| **Segurança** | 4 | ⚠️ `sudo ALL NOPASSWD` para `nixos` — o maior risco para o host. Sem sops-nix, sem sandbox nos serviços (executam como `nixos` com HOME inteiro). |
| **Feedback ao usuário (UI/UX)** | 6 | Porta do legado: `core/feedback.py` (status JSON compartilhado `/tmp/jarvis-status.json` + notificações + sons), module `custom/jarvis` no Waybar com estados/cores/animações (idle/listening/thinking/speaking/error/done), keybindings hyprland (`SUPER+A` ask, `SUPER+I` doctor). Falta: pipeline de voz real (STT/TTS) para os estados listening/speaking. |
| **Memória** | 6 | **Fase 7 feita (núcleo)**: `core/memory.py` — memória episódica com embeddings no Qdrant (coleção `memories`): `remember` (fatos/lições/decisões), `recall` (híbrido), `lessons` (formato experience_buffer legado) e **auto-aprendizado** (o agente grava lição quando um comando falha). Falta: resumo periódico de longo prazo, sessões. |
| **Roteamento (custo)** | 7.5 | `jarvis ask` roteia por custo: **fastpath (regras declarativas, zero LLM)** → doctor (zero LLM) → nixos via mcp-nixos (zero LLM) → rag (recuperação) → agent (LLM). Decisão RiveScript: **não está no nixpkgs** (quebraria a tese declarativa) — implementamos motor próprio (`core/rules.py`) com regras declarativas editáveis por humano/LLM (audiobook com topics, voz), no espírito do legado e do padrão 2026 (Agent Skills/SKILL.md). |
| **Voz (STT/TTS)** | 0 | Não existe ainda. |
| **Agente/self-heal** | 6.5 | **Fase 5/6 avançada**: `jarvis agent` (tool-calling + allowlist + aprovação + audit + cliente MCP p/ mcp-nixos), `jarvis doctor` (health) e **`jarvis ask` (roteador em cascata: doctor→nixos→rag→agent — usa o caminho mais barato, zero LLM quando possível)**. Falta: daemon contínuo, ação reparadora, canais de aprovação. |
| **Benchmarks** | 4 | Temos paridade (regressão do lab) mas não métricas de qualidade de retrieval (NDCG/Recall@k) nem latência. |

**Nota geral: ~5.9/10 — fundação sólida (declarativo, testado, adaptável), mas sem o que torna o projeto "JARVIS": agente, memória, voz e auto-manutenção.**

---

## 2. Comparação com o ecossistema (pesquisa 08/2026)

| Projeto | O que é | Local? | NixOS-first? | Auto-evolução | Lições para nós |
|---|---|---|---|---|---|
| **ClawNix** (jacopone/clawnix) | OpenClaw reconstruído para NixOS; agentes como módulos NixOS | ❌ Claude (cloud) | ✅ | ✅ **sim** (propose→validate→rebuild→auto-rollback) | O modelo de referência. Agents como systemd `DynamicUser`+`ProtectSystem=strict`; **overlay file escopo** (`clawnix-evolved.nix`) que o agente pode editar; sudo *escopo* só para `nixos-rebuild`; exec via `nix shell nixpkgs#<pkg>` com allowlist; aprovação via Telegram/web; audit de delegação. |
| **Agentix** (Beach-Bum) | Control layer que *propõe patches* (observe→plan→patch→test→explain→approve→apply→audit) | ✅ | ✅ | ✅ (propostas) | Nunca mutar direto; recusar dirty tree; audit trail JSON; `verify` sem switch. Comunidade: self-modify é controverso (risco de prompt injection — worm Shai-Hulud, 2026). |
| **mcp-nixos** (já em nixpkgs) | MCP server com options/packages reais do nixpkgs | — | ✅ | — | **Anti-alucinação de Nix**: nossa IA de bordo deve usá-lo ao editar config. |
| **OpenClaw** | Agente pessoal, 15+ canais, gateway, skills markdown | ✅ | ❌ Docker | ❌ | Skills como markdown carregadas no prompt; canais de mensagem; plugin host. |
| **Hermes** (Nous Research) | Agente pessoal com módulo NixOS | parcial | ✅ | — | Módulo NixOS declarando users/dirs/secrets/documentos. |
| **LocalAI / AnythingLLM / Open WebUI** | Stacks completas locais | ✅ | ❌ Docker | ❌ | Referência de UX, não de arquitetura NixOS. |

**Posicionamento:** nenhum projeto combina **local-first + NixOS-first + auto-evolução segura**.
ClawNix é NixOS-first mas cloud-LLM; OpenClaw é local mas não-NixOS. **Esse é o nosso diferencial**:
um "ClawNix local-first", com o modelo rodando em casa (qwen2.5-coder 7b/32b + nomic embeddings).

---

## 3. Gargalos e riscos atuais (ordenados por impacto)

1. **`sudo ALL NOPASSWD`** — qualquer exploit/vazamento vira root no host. Fix: sudo escopo mínimo (só `nixos-rebuild switch/test` e `clean.sh`), como o ClawNix.
2. ~~**Modelos em runtime (imperativo)**~~ ✅ **Resolvido** — `models.nix` agora declara todos os GGUFs (Qwen3-4B, Qwen3.6-35B-A3B + mmproj, nomic embed, reranker) via fetchurl com hash; `llama-cpp.nix` usa os store paths (sem `/home/nixos/models`, sem aria2). O host nasce com os modelos no store.
3. **Serviços sem sandbox** — rodam como `nixos` com HOME inteiro. Fix (host): `DynamicUser` onde possível, `ProtectSystem=strict`, `ReadOnlyPaths`.
4. **Zero observabilidade** — sem métricas não há *self-heal* (não se conserta o que não se mede). Fix: expor health JSON de cada serviço (já há `/health` no llama; falta do Qdrant via API), coletar em um `jarvis doctor`.
5. **Sem loop agentic** — o passo 0 para self-heal/self-improve.
6. **RAG indexa arquivo inteiro** — chunks por função/classe (os `facts` já existem) é o próximo ganho de recall.
7. **`--host 0.0.0.0` sem auth** — ok no lab (firewall), precisa de auth/tailscale no host.
8. **Sem backup/impermanence** — `/var/lib/qdrant` é a única fonte da coleção; no host, definir estratégia (disko/impermanence + snapshot).

---

## 4. Roadmap (priorizado por impacto/custo, continuação das fases)

| Fase | Escopo | Por quê | Base |
|---|---|---|---|
| **5 — Self-heal mínimo** | ✅ **Feito (núcleo + ação)**: `jarvis doctor` (health) + **`jarvis heal`** (`core/heal.py`): detecta via doctor → restart com **allowlist** (llama-cpp-server, llama-cpp-embeddings, qdrant) + **cooldown anti-loop** → **audit JSONL** → **lição na memória episódica** (errar→aprender→lembrar). Módulo `services/jarvis-heal.nix` (daemon `--watch` como user ou root). Resta: ativar no lab (precisa permissão de restart) e alertas (notify). | Transforma o lab em "ia de bordo que administra/conserta". | ClawNix `nixos`/`observe` plugins; watchdog systemd. |
| **6 — Agente com aprovação** | ✅ **Feito (núcleo + mcp-nixos + fast paths)**: loop agentic com `execute_shell` (allowlist + `--approve` + audit JSONL) + cliente MCP stdio próprio (mcp-nixos, sem libs) + **motor de regras declarativas** (`core/rules.py`, topics/prioridade/macros — no espírito do RiveScript legado, mas nativo ao stack e testável). Resta: `nix shell` allowlist, rebuild dry-run, canais de aprovação remota. | Self-improve seguro: o agente propõe, o humano aprova, NixOS garante rollback. | Agentix (patch model) + ClawNix (evolve com overlay + rollback). |
| **7 — Memória episódica** | ✅ **Completa**: `core/memory.py` (eventos com embedding no Qdrant híbrido: remember/recall/lessons/forget) + auto-aprendizado (agente grava lição ao errar) + **`core/vault.py` (Fase 7 fechada)**: `jarvis vault summarize` condensa eventos recentes em markdown estruturado (lições/decisões/fatos/padrões) num **vault git-syncado** (estilo m3ta-brain do repo AGENTS), grava de volta na memória (recall semântico acha o resumo — validado ao vivo) e tem **timer systemd semanal declarativo** (`services/jarvis-vault.nix`). | Sem memória não há continuidade ("lembrar sempre"). | m3ta-brain (AGENTS); OpenClaw/ClawNix `memory`. |
| **8 — Voz (STT/TTS)** | `whisper.cpp` (STT) + TTS local (ex: piper) como serviços declarativos; canal de voz no loop. | "Audiobook header" e interação por voz — citado como objetivo. | local-talking-llm (Whisper+Ollama+ChatterBox); piper em nixpkgs. |
| **9 — Canais** | ✅ **Núcleo completo**: `providers/telegram.py` — canal com long-polling (sem webhook/NAT), allowlist de chat_id, roteamento `/ask` `/agent` `/status` `/remember` `/vault` e **aprovação inline [Sim]/[Não]** (único consumidor de getUpdates; agente em thread com approver injetável — padrão RPC do pithagoras). `services/jarvis-telegram.nix` (token via `/etc/jarvis-telegram.env`, fora do store). **Falta: ativar** — criar o bot no BotFather + chat_id + `services.jarvis-telegram.enable = true`. | Aprovação assíncrona é o que torna o self-evolve usável. | pithagoras (RPC/eventos); ClawNix (inline buttons). |
| **10 — RAG SOTA** | ✅ **Núcleo completo**: reranker cross-encoder local (bge-reranker-v2-m3 GGUF, serviço `llama-cpp-rerank` + `providers/reranker.py` + fusão RRF com fallback silencioso). **Medido no lab: NDCG@5 = 1.0, 11/11 na 1ª posição** (antes 0.9545). Falta: chunking por símbolo (`get_symbol_block`) como refinamento. | Recall/precisão de retrieval mensurável. | rag-improvements.md. |
| **11 — Benchmark contínuo** | Dataset de queries reais do repo com relevância anotada; NDCG/Recall@k; latência por etapa (embed, dense, sparse, rerank, LLM); CI rodando `flake check` + pytest + benchmark a cada commit. | "Ranquear a qualidade" de forma objetiva e saber onde otimizar. | — |

**Referência p/ Fase 9 (canais) — `thecodacus/pithagoras`** (indicado pelo usuário): web UI para o agente `pi` com padrões que casam com o nosso canal de aprovação:
- **Agente expõe RPC (JSONL sobre stdio)** e o canal (web/Telegram) consome — o `jarvis agent` pode ganhar um modo RPC equivalente;
- **Runs donos do servidor, não do cliente** — submeter a tarefa retorna na hora; o run continua server-side (assíncrono = aprovação "de onde o usuário está");
- **Evento com replay** (`?since=`): log completo em SQLite; reconexão não perde nem duplica — nosso audit JSONL já é a base disso;
- **Eficiência de contexto**: ~3.8k tokens de sistema, skills carregadas sob demanda, MCP tools como tools diretas (150–300 tok cada) — boas práticas para o nosso agente local;
- **Sem approval prompts por design** (isolação via container/OS) — filosofia oposta ao nosso `--approve`, mas o fluxo "dá a tarefa, volta depois" é exatamente o objetivo da Fase 9.

**Referências do usuário — Sascha Koenig (m3tam3re)** — vídeo "My OpenCode Agent Workflow: NixOS Config, STT & Self-Reflection" + repos `AGENTS` e fork de `nixpkgs` (code.m3ta.dev):
- **AGENTS = "SO pessoal de IA" no Opencode**: 18 skills (brainstorming, systematic-debugging, plan-writing, skill-creator, voice-notify/TTS, doc-translator...), `agents/` + `prompts/`, `context/profile.md` (perfil do usuário: estilo de trabalho, preferências, áreas PARA) e **memória como vault git-sync** (`m3ta-brain`/`shared-brain-vault` — Obsidian versionado).
- **Transferível para o JARVIS**: (1) `context/profile.md` declarativo que o agente lê (não temos — só lessons episódicas); (2) **memória de longo prazo como vault markdown git-syncado** — candidato direto para o "resumo periódico" pendente da Fase 7 (mais simples e portátil que só Qdrant); (3) reflexão/auto-revisão pós-tarefa (próximo do nosso `regression`); (4) voice-notify ≈ nosso TTS Kokoro + feedback.
- **fork nixpkgs**: packages/overrides pessoais (n8n, buzz, basecamp-cli, vibetyper, oh-my-openagent) — modelo de como manter patches locais (nosso overlay já segue esse padrão).

---

## 4a. Self-hosting + modo idle (pesquisa 2026-08)

**Self-hosting (o JARVIS usando o próprio JARVIS) — VALIDADO no lab**: `jarvis agent "execute uptime"` completou com resposta correta em PT-BR em **1m29s** (Qwen3-4B CPU, VM). A mecânica existe e funciona; a VM é para validação de tarefas pequenas — o host (Qwen3.6-35B + GPU, ~10-30× mais rápido) é onde o self-work real acontece. Critério objetivo de prontidão: a rota `agent` do `jarvis benchmark` abaixo de ~30s no host.

**Modo idle (self-knowledge/self-heal/self-improve quando ocioso) — VIÁVEL, já é prática**: o artigo "10 things I learned running 20+ autonomous AI agent services on NixOS" (dev.to, mar/2026 — escrito por um agente autônomo) prova o modelo: 23 serviços systemd persistentes + timers, operação sem intervenção. Lições que mapeiam 1:1 para o nosso setup:
- **Heartbeat/state-file por serviço** (health check verifica se o arquivo foi atualizado — corretude de aplicação, não só "systemd acha que roda") → evolução natural do nosso `doctor`/`heal`;
- PATH explícito em serviços, `Persistent=true` em timers, `WorkingDirectory` (já adotados no nosso stack);
- `switch` não reinicia serviços rodando (o self-improve precisa de restart pós-rebuild);
- rollback real como rede de segurança (já usamos).

**Mecanismos confirmados para o modo idle**:
- **Idle do usuário**: `loginctl`/D-Bus `org.freedesktop.login1` (`IdleHint` por sessão — o systemd já rastreia; há até feature request #12668); alternativa Hyprland (`hyprctl`).
- **Yield automático (o insight-chave)**: NÃO precisa detectar jogo/Steam — `CPUWeight=1` + `Nice=19` + `IOSchedulingClass=idle` no serviço de fundo faz o cgroup scheduler ceder CPU automaticamente quando o usuário/jogo precisa. "Liberar o hardware" sai de graça do kernel. (Bônus no host: `programs.gamemode`.)
- **Custo ~0 ocioso**: com esses pesos, o fundo só roda no que sobra; eletricidade idem.

**Design — IMPLEMENTADO no lab** ✅ (`core/idle.py` + `services/jarvis-idle.nix`, ativo em `nixos-lab`):
- `jarvis idle status` — mostra carga, IdleHint do logind (com timeout curto — **nunca trava** mesmo com o logind pendurado pós-upgrade; `None` = decide pela carga) e tarefas devidas;
- `jarvis idle worker [--force TAREFA]` — executa **no máximo uma** tarefa de self-knowledge por vez (gate: carga < 2.0 E IdleHint≠no); fila escolhe a **mais atrasada** por heartbeat JSON (`state_dir/idle/<tarefa>.json` — padrão do artigo "10 things"). Tarefas: `benchmark` (6h), `regression` (diário), `eval-rag` (diário) — todas baratas, sem efeito colateral;
- **Yield automático**: timer systemd de usuário (OnUnitActiveSec=5min) com `CPUWeight=1` + `Nice=19` + `IOSchedulingClass=idle` — o kernel cede a CPU quando o usuário/jogo precisa (sem detectar jogo);
- O worker nunca quebra (exceção de tarefa → heartbeat com erro, próxima rodada tenta de novo).

Self-knowledge roda sozinho no lab agora; o **self-improve** (propor mudança → aprovação Telegram → rebuild → rollback) fica para o host, atrás da Fase 9.

---

## 4b. Áudio calibrado (legado → Nix) — wakeword com as tunagens validadas

A calibração de áudio do legado (ventoinha + sons de casa) foi recuperada e portada — ver
`docs/architecture/legacy-audio-calibration.md`. O wakeword Nix declarativo agora carrega
toda a calibração empírica que funcionou:

- **threshold 0.85** (evolução 0.05→0.15→0.30→0.70→0.75→0.65→0.85 — menos false positives);
- **cooldown 5s** anti-loop (sem ele, o beep de confirmação re-triggerava o wakeword);
- **kill TTS/audiobook ao trigger** (para o usuário falar);
- **silence adaptativo**: 40% drop do pico RMS por 1.0s = parar gravação (max 12s);
- **RMS gate opcional** (legado calibrou 2093; `null` = desabilitado);
- **notificação + beep + status waybar** (listening → processing), como o legado;
- **device ALSA parametrizável** (legado: `hw:1,7` raw, bypass PyAudio);
- **RNNoise**: **ativado declarativamente** — `rnnoise-plugin` (1.10, do nixpkgs)
  + filter-chain no `nixos/modules/audio.nix` cria o source virtual
  `rnnoise_source` (VAD threshold 50%, grace 200ms). O plugin LADSPA que
  faltava no Arch/nixpkgs antigo agora vive no store — a pendência do legado
  está resolvida sem easyeffects (pesado). A calibração do wakeword continua
  sendo o fallback robusto quando o wakeword captura via ALSA cru.

Fase 8 (voz): **núcleo implementado e validado por pesquisa 2026** —
`core/voice.py` (STT faster-whisper com VAD calibrado + TTS Kokoro-82M) no
pacote `jarvis-voice` (`nix build .#jarvis-voice`), comandos `jarvis stt` /
`speak` / `voice` (loop STT → roteador → TTS). O wakeword grava o WAV com VAD
calibrado e tem o gancho `brainCommand = [ "jarvis" "voice" ]` no host final.
Kokoro-82M confirmado como melhor TTS local 2026 (Realtime TTS Arena) e já em
nixpkgs (binary cache). **Emoção**: `core/emotion.py` (porta do emotional_state
do legado) — keywords PT/EN → perfil (tone/emoji/speed) com TTL de 5 min;
`jarvis emotion` e prosódia automática no TTS (frustrado fala mais devagar,
urgente mais rápido).

**Modelos declarativos** (`modules/ai/models.nix`): openwakeword (hey_jarvis +
melspec + embedding), Kokoro (config + modelo + voz) e whisper-small baixados
via fetchurl com hash — o host **nasce com tudo no store**, sem download em
runtime. O activation do wakeword cria symlinks store → `~/.local/share`.
Corrigidos 2 bugs latentes: (1) wakeword apontava para `~/.local/lib/python3.14`
(inexistente no Nix); (2) `libraries` do writePython3Bin recebia env em vez de
pacotes → PYTHONPATH vazio. Modelo onnx validado carregando (`hey_jarvis_v0.1`).

**Centralização de Inteligência** (`modules/ai/models.nix` — única fonte de
verdade): os GGUFs de chat agora também são declarativos e cada cenário tem
seu **perfil** de execução consumido por `llama-cpp.nix` (`services.llama-cpp-server.profile`):

- **vm (Lab, CPU)** — `Qwen3-4B` (2.5GB, tool calling nativo via `--jinja`):
  threads 4, ctx 16K, `-ngl 0`, KV f16, sem scheduler especial. Substitui o
  Qwen2.5-7B (bug de tool_call vazado como texto). O jarvis desliga o
  *thinking* do Qwen3 por default (`enable_thinking=false` via
  `chat_template_kwargs`, validado ao vivo contra o llama-server) — tool
  calling direto e rápido em CPU.
- **host (Acer Nitro V15 — RTX 4050 6GB / 32GB RAM)** — `Qwen3.6-35B-A3B`
  (MoE 35B total/3B ativos, **vision** via `--mmproj`, agentic coding) em
  GGUF UD-Q4_K_M (~20.6GiB, unsloth — o repo oficial é gated):
  - `--n-cpu-moe 2` — experts roteados na RAM (32GB), VRAM 6GB preservada;
  - `-fa on -ctk q8_0 -ctv q8_0` — flash attention + KV-cache quantizado;
  - `-ngl 14` conservador (knob de tuning 14→18 no host real);
  - `CPUSchedulingPolicy=fifo` + `CPUSchedulingPriority=50` (tempo real) —
    exige root (perfil `user = "root"`);
  - `threads 12`, ctx 16K (32K com q8_0 estouraria os 6GB).

  ⚠️ **Antes do boot do host**: conferir se o `llama-cpp` do pin (b10273)
  carrega o Qwen3.6 — modelo é de 2026; se falhar, `nix flake update
  nixpkgs-unstable` (o serviço usa o llama-cpp do unstable via overlay).

  Os modelos do host **não são baixados no lab**: o fetchurl só é realizado
  quando referenciado pela config (perfil `host` não é usado no lab).

**Benchmark da cascata** (`core/benchmark.py`, `jarvis benchmark`): mede cada
rota contra metas (fastpath 200ms, doctor 500ms, nixos 1.5s, rag 1.5s, agent
30s). Primeira rodada real revelou o **gargalo #1: rota nixos em ~20s** — a
descoberta de canais do mcp-nixos faz **20 probes HTTP sequenciais (gen 43–46 ×
5 versões) a cada processo novo**. Fix declarativo (overlay `mcp-nixos-fast` +
`modules/ai/patches/mcp-nixos-channel-cache.patch`): canais pré-computados no
store (`MCP_NIXOS_CHANNEL_CACHE`, gen 45 conferida ao vivo; `26.05` ainda não
indexado — consulta via `unstable`/`25.11`), e FALLBACK_CHANNELS atualizado de
44 → 45. **Resultado: rota nixos 20.5s → 2.3s** (a consulta em si = 160ms;
restante é startup do processo mcp-nixos ~800ms + handshake, pagos por
consulta). Nota: atualizar `nixosIndexGeneration` no flake se a geração subir.
Gargalo remanescente conhecido: spawn por consulta — um servidor MCP persistente
(transport http) tiraria o custo fixo de ~1.6s; o cache declarativo já resolve
o caso de hoje sem estado em runtime.

**Qualidade do retrieval** (`core/eval_rag.py`, `jarvis eval-rag`): NDCG@k /
Recall@k / Precision@k com ground-truth do próprio repo. Baseline no lab
(índice com 102 arquivos): **Recall@5 = 1.0, NDCG@5 = 1.0** — 11 queries
cobrindo núcleo, voz e config NixOS (self-knowledge); **11/11 com NDCG 1.0**
(relevante na 1ª posição) — com o reranker vivo (ver Fase 10 abaixo).
Otimizações aplicadas (guiadas por dado, validadas no legado):
1. `.nix` entrou nas extensões indexáveis + padrões de atributos/options NixOS
   — o RAG conhece a própria config (self-knowledge); `models.nix` agora é a
   1ª resposta para queries de modelos declarativos (comentário do módulo
descreve o propósito em PT, casando com queries em português).
2. Re-rank calibrado para o repo: penalidade estrutural para `test_*.py`
   (sequestravam o ranking por ter palavras da query no nome) e sovereignty
   só para stems >= 8 chars (termos curtos como "qdrant"/"doctor" são
   assunto genérico, não filename único).

**Fase 10 — reranker (RAG SOTA)**: `bge-reranker-v2-m3` (cross-encoder
multi-língua, GGUF Q4_K_M 438MB) provisionado declarativamente em
`models.nix` e servido pelo `llama-server --rerank` (serviço
`llama-cpp-rerank`, porta 8082, `services/jarvis-heal` não relacionado).
`providers/reranker.py` (endpoint /rerank) + integração no `HybridSearch`.
**Fusão RRF (rank-based), não reordenação por score**: o cross-encoder sozinho
favorece densidade lexical (ex: `benchmark.py` > `router.py` na query de
roteamento) e seus scores são enviesados; a fusão por RANK (1/(k+rank), k=60,
pesos 1:1, desempate 1e-6 pela posição do boost) combina o ranking
híbrido+boost com o do cross-encoder — o consenso acerta onde cada um sozinho
erra. Calibrado por varredura de pesos no eval (11 queries, NDCG 1.0000 em
platô amplo). Resultado medido no lab com o serviço vivo: **Recall@5 = 1.0,
NDCG@5 = 1.0, 11/11 com o relevante na 1ª posição** — inclui a query do
vector_store (gap de 3 sessões) e as duas que o rerank puro piorava. Fallback
silencioso — sem o serviço, o resultado é idêntico ao pré-reranker
(NDCG@5 0.9545).

**Scripts declarativos no store** (`nixos/modules/scripts.nix`, `programs.jarvis-scripts.enable`): `rebuild.sh`, `clean.sh` e `fix-qdrant.sh` agora são `writeShellApplication` — binários do store (`jarvis-rebuild`, `jarvis-clean`, `jarvis-fix-qdrant`) com PATH controlado e shellcheck no build, sem depender de arquivos soltos na raiz. O doctor referencia o binário (`clean`/`jarvis-clean`) em vez de `./clean.sh`. **Self-heal notifica no Telegram** quando repara (send_notification no `_alert`). **Fix**: `answer_callback("")` noop removido (o Telegram rejeitava com "Bad Request: query is too old" → erro no agente).

**Regressão automática** (`core/regression.py`, `jarvis regression`): compara
benchmark + eval-rag contra o baseline registrado (`jarvis/baseline.json`, 2x
de folga na latência, 0.05 na qualidade). Integrado ao checkPhase do build
(smoke offline no sandbox: `REGRESSÃO: OK ✓` no `nix build`/`flake check`);
no lab/host roda com serviços reais e falha (exit 1) se degradar. Fecha o
critério #3 e o item 11 do roadmap (benchmark contínuo + CI): `flake check`
a cada commit roda pytest + regressão estrutural.

---

## 4c. Auto-detecção de hardware → flags SOTA (hwdetect/hwprofile) — NOVO

**Visão do usuário**: um sistema que roda em QUALQUER hardware — do Termux num
celular velho a um datacenter com Teslas/TPUs/NPUs — com um cálculo matemático
que lê o hardware e decide as flags SOTA do llama.cpp + o melhor modelo.
Pesquisado (ago/2026): o llama.cpp já tem `llama-fit-params` (dry-run VRAM →
`-ngl`/`-ot`) e backends dinâmicos (`-DGGML_BACKEND_DL=ON`); o gap é a
**escolha do modelo + flags integrada ao perfil de hardware** — que é o que
implementamos, com matemática própria.

**Implementado** ✅ (`core/hwdetect.py` + `core/hwprofile.py`, 13 testes):

- **`jarvis hwdetect`** — detecta RAM/VRAM/CPU/GPU/NPU em qualquer plataforma
  (nvidia-smi → rocm-smi → vulkaninfo → Metal → Termux/Android) e classifica o
  tier: `phone | laptop | desktop | gaming-laptop | workstation | multi-gpu |
  datacenter | apple-studio`. No lab real: `laptop` (i7-13620H, 19.1GB RAM,
  sem GPU).
- **`jarvis hwprofile`** — matemática → flags + modelo + comando + previsão:
  - **KV cache**: `2·n_kv_heads·head_dim·n_layers·bytes` (f16=2, q8_0=1) —
    validada contra valores conhecidos (LLaMA-70B @32K f16 ≈ 10.5GB);
  - **Arquiteturas REAIS** dos modelos (config.json oficial do HF, ago/2026):
    Qwen3-1.7B/4B/8B, Qwen3.6-27B, Qwen3.6-35B-A3B (MoE+vision: 40 camadas,
    2 kv_heads, head_dim 256), Qwen3-VL-235B-A22B (approx — confirme antes);
  - **Offload em 4 modos**: `full` (cabe tudo na GPU, KV f16) | `expert` (MoE:
    atenção na GPU, experts roteados na RAM via `--n-cpu-moe`) | `partial`
    (denso, camadas que cabem) | `cpu` (sem GPU, KV f16);
  - **Previsão de t/s** a partir da largura de banda de memória (calibrada com
    relatos reais: Qwen3.6-35B offload ≈ 30 tps; lab Qwen3-4B ≈ 10 t/s ✓);
  - **Renderer NixOS**: emite o bloco `profiles.<nome>` pronto para colar em
    `models.nix` — o cálculo dinâmico vira declaração (NixOS-first).

**Validação do host alvo (RTX 4050 6GB / 32GB)**: `gaming-laptop` →
Qwen3.6-35B-A3B MoE+vision, expert offload `-ngl 17 --n-cpu-moe 2 -c 32768
-ctk q8_0 -ctv q8_0 -fa on` (VRAM: 17 camadas de atenção + KV q8 1.25GB +
0.6GB overhead ≈ 5.9GB ≤ 6GB) — bate com o perfil `host` já declarado em
`models.nix` (ngl 14, knob de tuning). Datacenter 4×80GB: `full` offload +
`--split-mode row` (MoE).

**Bugs reais caçados pelos testes**: (1) unidades misturadas B/raw no cálculo
por-camada dos experts MoE (dava `ngl=40` e t/s=1.0); (2) `classify()`
ignorava memória unificada do Apple Silicon; (3) multi-GPU usava VRAM por-GPU
em vez do total. 243 testes verdes + `flake check` OK.

**Próximo**: plugar `hwprofile` ao serviço — o `llama-cpp.nix` pode consumir
`jarvis hwprofile --json` (ou o bloco declarado) para o host nascer com as
flags certas; e `llama-fit-params` como validação cruzada empírica no host.

---

## 4d. Sistema-água + esqueleto do host + cascade (NOVO)

**Visão do usuário**: o sistema deve se adaptar a QUALQUER ambiente como água
(Bruce Lee) — e cada parte se adaptar ao sistema — sem hardcode espalhado.
Pesquisa (ago/2026): NixOS não detecta hardware em build-time (a config é
avaliada antes do boot); o padrão correto é **cada host declarar seu
recipiente** via um switch central, e a detecção em runtime (hwdetect) ficar
para os serviços que decidem ao vivo.

**Implementado** ✅:

- **`services.jarvis.environment = "vm" | "host"`** — switch central
  (`nixos/modules/jarvis-env.nix`). Um cérebro decide, o corpo inteiro reage
  no rebuild: llama-cpp (perfil do models.nix), waybar (módulos de hardware
  só no host), mpvpaper (serviço nem existe na VM; host = iGPU VA-API),
  hyprland (animações full no host).
- **Waybar VM profile** — sem battery/bluetooth/backlight na VM (popups de
  erro sumiram). Bug real caçado: o diretório `waybar/` era inerte — o arquivo
  ativo era `waybar.nix` (raiz); os módulos agora são `if/then/else` puro
  (determinístico, sem `mkIf` aninhado em listas).
- **Esqueleto do host** (`hosts/nitro-v15/`): `configuration.nix` (switch
  `host` liga Qwen3.6-35B MoE + waybar full + mpvpaper iGPU + whisper SYCL +
  NVIDIA 4050 + Intel media driver) + `disko.nix` (2 NVMe: o **mais rápido**
  p/ `/` + `/nix` — store/models I/O-intensivo; o **mais lento** p/ `/home` —
  dados; detecte Gen3/Gen4 com `nvme list` + `lspci -vv | grep LnkSta`;
  use `/dev/disk/by-id/*`, nunca `/dev/nvmeXnY`). Não registrado no flake
  até o `hardware-configuration.nix` real existir.
- **Hyprland — 4 deprecações corrigidas**: `togglesplit` → `layoutmsg`,
  `dwindle.pseudotile` removido, `gestures.workspace_swipe` → `gesture =
  "3, horizontal, workspace"`, `windowrulev2` → `windowrule` (validado no
  config gerado).
- **LiteLLM cascade** (porta do legado `config-free-ai.yaml`): módulo OFICIAL
  do nixpkgs (`services.litellm`, com hardening) + `litellm-cascade.nix` que
  injeta a estratégia: `local (llama.cpp :8080) → Groq → Gemini → OpenRouter`
  com fallbacks em cadeia, em `:4000` (127.0.0.1). O JARVIS usa UM endpoint
  e o roteamento fica declarativo. Chaves em `/etc/litellm.env` (600, fora
  do repo) — sem o arquivo, roda só a rota local.
- **Fluxo de auto-diagnóstico de deprecações** (para a IA de bordo): quando
  um rebuild/popup apontar deprecações ou erros de config, o fluxo validado
  é: (1) ler o log/erro exato → (2) pesquisar a sintaxe atual na web (wiki
  oficial do projeto) → (3) achar o arquivo ATIVO (cuidado com diretórios
  inertes — confirmar no `imports`) → (4) corrigir com `if/then/else`
  determinístico → (5) validar no config GERADO (`nix flake check` + avaliar
  o artefato) → (6) rebuild. Este padrão é o que o `jarvis heal` deve replicar
  no host.

**Segurança**: a chave Groq que estava hardcoded em `home-manager/home.nix`
foi REMOVIDA (vazava para o repo/histórico) — **rotacione-a** no painel da
Groq. Segredos agora só em `/etc/*.env` (600, fora do git).

---

## 5. O que NÃO portar do legado (paradigma mudou)

- **Espelho do V4.0.5 como arquitetura** — serviu para validar paridade no lab; o host nasce com `jarvis index` limpo.
- **Compiler-expert/otimizações acopladas ao paradigma antigo** — só reutilizar se o paradigma novo (agente NixOS) as demandar; não carregar dívida.
- **Ollama/11434** — já removido; llama.cpp é a base.
- **Estado imperativo** (`.ai-index`, modelos baixados à mão) — no host tudo nasce declarativo ou provisionado.

---

## 6. Critérios de qualidade do sistema final (definition of done do host)

1. `nix flake check` + `nix build .#jarvis` (pytest) verdes a cada commit — CI.
2. `jarvis doctor` reporta saúde de todos os serviços com 1 comando.
3. Benchmark de retrieval (NDCG/Recall@k) + latência registrado e regredindo → otimização guiada por dado.
4. Toda mudança de sistema passa por aprovação humana (exceto restarts seguros), com audit trail.
5. Qualquer mudança aplicada é reversível em 1 geração Nix (`nixos-rebuild switch --rollback`).
6. Nenhum segredo em claro (sops-nix); sudo mínimo; serviços sandboxados.

---
**Ver também:** [[../HANDOFF]] | [[../AGENTS.md]] | [[JARVIS-COMPARISON]] | [[NIGHTWATCH]]
