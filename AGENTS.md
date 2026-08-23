# AGENTS.md — contexto compartilhado do repo (leia antes de trabalhar)

> Formato aberto (agents.md, Linux Foundation) — **toda** IA que trabalhar neste
> repo (Codebuff/Buffy, Gemini, ChatGPT/Codex, Cursor, JARVIS local) lê este
> arquivo. É a **fonte de premissas**: se uma premissa mudar, atualize aqui.
> O humano e os agentes sincronizam por **git** (commits pequenos e frequentes)
> + este arquivo. Nunca trabalhe sobre uma premissa que não está registrada.

## O que é este projeto

JARVIS on NixOS — "ia de bordo" local-first: RAG sobre o próprio repo, memória
episódica (Qdrant) + vault markdown git-syncado, agente tool-calling com
aprovação, self-heal, modo idle (self-knowledge), canais (Telegram) e voz
(STT/TTS). Tudo declarativo no NixOS (flake) — o host físico (Acer Nitro V15,
RTX 4050 6GB / 32GB RAM) nasce do zero via este repo.

## Build, teste e validação (sempre antes de commitar)

### TESTES — USE `nix develop` (NÃO nix-shell)

```bash
# ✅ CORRETO — provisiona jarvis + pytest + hypothesis + PYTHONPATH:
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# ❌ ERRADO — nix-shell com pacotes soltos não tem as dependências do jarvis:
# nix-shell -p python3Packages.pytest python3Packages.requests --run "pytest ..."
```

O `nix develop` carrega o flake devShell que inclui:
- Todas as dependências do jarvis (via `inputsFrom = [ pkgs.jarvis ]`)
- pytest + hypothesis
- `PYTHONPATH` automático para `modules/ai/jarvis/src`

### BUILD

```bash
git add -A          # OBRIGATÓRIO antes de build: o flake só copia arquivos trackeados
nix build .#jarvis --no-link        # roda pytest (checkPhase)
nix flake check                     # avalia TODAS as configurações
```

### REBUILD DO SISTEMA (CRÍTICO — NÃO ERRE ESTE PASSO)

```bash
# HOST (bare metal) — SEMPRE usar este script:
./rebuild-host.sh

# LAB (VM) — usar este:
./rebuild-lab.sh

# NÃO FAÇA:
nixos-rebuild build --flake .#nixos-lab   # ERRADO no host!
nixos-rebuild switch --flake .#nitro-v15  # ERRADO — usar rebuild-host.sh!
```

**Por quê**: `rebuild-host.sh` faz `git add -A` + commit automático antes do build. Sem isso, o flake não vê arquivos untracked e o build quebra.

- Convenção de commit: mensagem em PT-BR, um verbo por mudança
  (`feat:`/`fix:`/`chore:`/`docs:`), corpo explicando o **porquê**.
- Rodar `./clean.sh` de vez em quando (GC do Nix) para não encher o disco.

## Estado atual (agosto/2026 — auditoria code-first)

### Implementado e validado
- **Agent loop** (tool-calling com repair, circuit breaker, audit trail)
- **Router** (cascata: fastpath → doctor → nixos → rag → agent)
- **Fast Paths** (regras declarativas, zero LLM)
- **DevTools** (read_file, write_file, str_replace, code_search, run_tests)
- **Memory** (Qdrant episódica: remember/recall/lessons, 14 eventos)
- **MCP** (mcp-nixos via JSON-RPC 2.0)
- **Circuit Breaker** (CLOSED/OPEN/HALF_OPEN + egress filter)
- **Self-Heal** (detect→restart→audit→learn, allowlist de 3 serviços)
- **AST Guard** (validação antes de str_replace)
- **Gaming Profile** (multi-sinal: GPU/Hyprland/Steam/Proton)
- **Vision** (grim/slurp/hyprctl)
- **Triggers** (disco, doctor, CPU alerts)
- **EventBus** (asyncio pub/sub)
- **User Profile** (preferências + contexto dinâmico)
- **llama-server** (32 t/s estável, 0.7% drift)

### Implementado mas NÃO validado
- **RAG code_index** — collection NÃO EXISTE no Qdrant (nunca indexado)
- **Voz/wakeword** — implementado, não testado E2E no host
- **Telegram** — precisa criar bot + env file
- **Heal daemon** — implementado, não ativado

### Problemas conhecidos
- **Modelo não usa tools** — Qwen responde do contexto em vez de chamar read_file/code_search
- **thinking overhead** — 88% dos tokens são thinking no aider (~42s por tarefa)
- **legacy_index.py** — requer numpy, mas agora passa todos os 11 testes (corrigido em 2026-08-22)
- **Backups** — agent.py.bak, rag.py.bkp foram removidos em commits anteriores

## Configuração atual do llama-cpp (host)

- **Modelo**: Qwen3.6-35B-A3B MoE (UD-Q4_K_M, ~20.6GiB)
- **GPU layers**: ngl=50 (atenção na GPU)
- **MoE**: n-cpu-moe=50 (experts na RAM)
- **Contexto**: 131072 tokens (128K, KV cache q4_0)
- **Threads**: 16
- **VRAM**: ~4.2GB / 6GB (mmproj em CPU via --no-mmproj-offload)
- **RAM livre**: ~27 GB (sem --load-mode none)
- **Decode**: ~32 t/s (estável, 0.7% drift)
- **Flags**: --no-mmproj-offload --reasoning-preserve --jinja

## Regras que não podem ser quebradas

1. **`models.nix` é a única fonte de verdade** dos modelos (GGUF/URL/hash/perfis
   `vm`/`host`). Nunca baixe modelo imperativamente nem edite unit à mão.

2. **VRAM BUDGET (RTX 4050 6GB) — NÃO EXCEDER**:
   - Main LLM (ngl=50): ~3.2GB (atenção +KV)
   - mmproj BF16: 0MB VRAM (--no-mmproj-offload mantém em CPU)
   - Overhead CUDA: ~0.5GB
   - Total: ~4.2GB / 6GB (1.9GB margem)
   - Embeddings/Rerank: 0MB VRAM (CUDA_VISIBLE_DEVICES="" força CPU)
   - **IMPORTANTE**: mmproj na GPU causa degradação 32→14 t/s após 1º request

3. **DISTRIBUIÇÃO DE HARDWARE**:
   - RTX 4050: Main LLM + mmproj (atenção densa + vision)
   - Intel UHD 770 iGPU: Whisper STT, mpvpaper, Kokoro TTS (futuro)
   - CPU: MoE experts na RAM, embeddings, reranker, TTS
   - `CUDA_VISIBLE_DEVICES=""` em embeddings/rerank é OBRIGATÓRIO

4. **NÃO tocar no dbus-broker** (`reloadIfChanged`/`restartIfChanged = mkForce false`
   no lab): restart derruba o bus do sistema; reload trava ~90s na VM.

5. **Fontes Python do JARVIS ficam no repo** (`modules/ai/jarvis/`) — declarativo.
   Arquivos untracked NÃO entram no build do flake: `git add -A` antes de build.

6. **`sudo ALL NOPASSWD` é temporário** (lab, para o agente não travar). No host:
   sudo escopo mínimo (só `nixos-rebuild` e `clean.sh`) — ver assessment §3.

7. **Nunca editar arquivos do store** (`/nix/store/...`) — mudar a fonte no repo.

8. **Circuit Breaker**: se o backend local falhar 3x, o sistema usa fallback remoto
   (Groq/Gemini/OpenRouter). **POLÍTICA DE EGRESS**: dados sensíveis (memórias,
   vault, RAG, paths, passwords) NUNCA saem do host — o ContentSafetyFilter
   bloqueia. Usuário pode forçar modo local (`/force_local`).

## Perfil do usuário (o que toda IA deve saber sobre ele)

- **Idioma**: PT-BR — responda, comente código e escreva docs em português.
- **Estilo de trabalho**: pragmático e minimalista — "extrair o máximo do
  mínimo" (SLMs + fast paths declarativos > LLM caro para tudo). Zero
  desperdício de hardware, zero estado imperativo.
- **Local-first e privacy-first**: tudo roda local (llama.cpp, Qdrant, voz);
  cloud só para pesquisa/revisão. É o diferencial vs soluções pagas.
- **Decisões**: na dúvida, pesquise na internet e/ou no legado (Manjaro) antes
  de decidir. Ele confia na pesquisa com fonte; decisões de arquitetura
  importantes passam por ele (pergunte), followups menores ficam com o agente.
- **NixOS-first**: tudo declarativo e reprodutível; se uma solução quebrar a
  tese declarativa (ex: dependência fora do nixpkgs), prefira implementar o
  próprio motor no repo (ex: regras declarativas em vez de RiveScript).
- **Qualidade medida**: testes, benchmark, NDCG/Recall e regressão guiam a
  otimização — nunca "achismo". Cada fase do roadmap tem critério objetivo.
- **Auto-manutenção**: quer a "ia de bordo" que se auto-cura, auto-melhora e
  não fica parada (modo idle, self-knowledge, aprovação assíncrona).
- **Hardware alvo**: Acer Nitro V15 (RTX 4050 6GB / 32GB RAM) — modelos MoE
  com expert offloading, não densos.
- **Histórico valioso**: o sistema legado Manjaro tem padrões testados
  (compiler-expert, RiveScript com topics, audiobook, áudio calibrado com
  RNNoise) — consulte antes de reinventar.

## Como trabalhar em paralelo (sincronia de premissas)

- **git é o sensor de mudanças**: antes de começar qualquer tarefa, rode
  `git log --oneline -5` e `git status` — se o outro agente/humano fez algo,
  está lá. Commits pequenos e frequentes > trabalho longo sem commit.
- **Este arquivo é o acordo**: mudou uma premissa (ex: modelo novo, fase
  concluída, decisão de arquitetura)? Atualize o AGENTS.md no mesmo commit.
- **Divisão de trabalho sugerida**: o humano (notebooks Gemini/ChatGPT) faz
  pesquisa, revisão e decisões; os agentes fazem implementação+teste. Se o
  humano implementa algo, commit + mensagem descritiva para o agente saber.
- **Não duplicar trabalho**: antes de implementar algo, consulte o
  `docs/architecture/system-assessment.md` (estado da stack) e o `git log`.

## Integração m3ta-nixpkgs (agosto/2026)

### Submodule
O repositório `nixpkgs` (`/home/nixos/projects/nixpkgs`) é importado como submodule
git em `m3ta-nixpkgs/`. Ele contém:
- **Pacotes**: sidecar, stt-ptt, talk, td, opencode, vibetyper, zellij-ps etc.
- **Módulos NixOS**: ports (gerenciamento centralizado de portas)
- **Módulos Home Manager**: stt-ptt, coding agents (opencode, pi, claude-code)
- **Bibliotecas**: ports, agents, coding-rules

### Estrutura de integração
```
nixos-ai/
├── flake.nix                          # m3ta-nixpkgs input + overlay + packages
├── overlays/m3ta-packages.nix         # overlay: sidecar, stt-ptt, talk
├── lib/                               # wrappers das bibliotecas m3ta
│   ├── default.nix
│   ├── ports.nix
│   ├── agents.nix
│   └── coding-rules.nix
├── nixos/modules/m3ta-ports.nix       # módulo NixOS de portas
├── home-manager/modules/m3ta-coding/  # módulos coding agents
│   ├── default.nix
│   ├── opencode.nix
│   ├── pi.nix
│   └── shared/
├── home-manager/modules/m3ta-stt-ptt.nix
└── home-manager/home-packages.nix     # sidecar, stt-ptt, talk
```

### Uso dos módulos

#### Ports (NixOS)
```nix
# Em configuration.nix:
imports = [ ./nixos/modules/m3ta-ports.nix ];
m3ta.ports = {
  enable = true;
  definitions = { qdrant = 6333; llama-cpp = 8080; mcp = 3000; };
  hostOverrides = { nitro-v15 = { qdrant = 6334; }; };
};
# Uso: services.qdrant.settings.config.listener.port = config.m3ta.ports.get "qdrant";
```

#### STT-PTT (Home Manager)
```nix
# Em home.nix:
m3ta.stt-ptt.enable = true;
m3ta.stt-ptt.model = "ggml-large-v3-turbo";
m3ta.stt-ptt.language = "pt";
```

#### Coding Agents (Home Manager)
```nix
# Em home.nix:
coding.agents.opencode.enable = true;
coding.agents.opencode.agentsInput = inputs.agents;
coding.agents.opencode.modelOverrides = { chiron = "anthropic/claude-sonnet-4"; };

coding.agents.pi.enable = true;
coding.agents.pi.agentsInput = inputs.agents;
coding.agents.pi.settings.defaultProvider = "anthropic";
coding.agents.pi.settings.defaultModel = "claude-sonnet-4";
```
