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

```bash
git add -A          # OBRIGATÓRIO antes de build: o flake só copia arquivos trackeados
nix build .#jarvis --no-link        # roda pytest (checkPhase) — 200+ testes
nix flake check                     # avalia TODAS as configurações
nixos-rebuild build --flake .#nixos-lab   # valida o sistema (sem ativar)
./rebuild.sh                        # switch de verdade (rebuild + ativação)
```

- Testes: `modules/ai/jarvis/tests/test_*.py` (pytest, roda no build Nix).
- Convenção de commit: mensagem em PT-BR, um verbo por mudança
  (`feat:`/`fix:`/`chore:`/`docs:`), corpo explicando o **porquê**.
- Rodar `./clean.sh` de vez em quando (GC do Nix) para não encher o disco.

## Estado atual (agosto/2026 — fases do roadmap)

- **Feitas**: 5 (self-heal), 6 (agente+aprovação), 7 (memória+vault), 9 (Telegram),
  10 (RAG SOTA: NDCG@5=1.0), 11 (benchmark+regressão), 4a (modo idle),
  audiobook, observabilidade, perfil dinâmico, circuit breaker, event bus,
  vision, triggers, devtools, CLI dev — todas implementadas e testadas.
- **Testes**: 485+ (pytest). Inclui PBT (hypothesis), security, wakeword, profile,
  observability, eventbus, triggers, vision, circuit breaker, fuzzing, devtools.
- **Pendente no lab**: ativar Telegram (bot + `/etc/jarvis-telegram.env`);
  ativar `jarvis heal` como daemon; testar `jarvis dev` com mais tarefas reais.
- **Pendente no host**: `services.llama-cpp-server.profile = "host"` (Qwen3.6-35B
  MoE + GPU), verificar se o llama-cpp do pin carrega o Qwen3.6, voz/wakeword.

## Regras que não podem ser quebradas

1. **`models.nix` é a única fonte de verdade** dos modelos (GGUF/URL/hash/perfis
   `vm`/`host`). Nunca baixe modelo imperativamente nem edite unit à mão.
2. **NÃO tocar no dbus-broker** (`reloadIfChanged`/`restartIfChanged = mkForce false`
   no lab): restart derruba o bus do sistema; reload trava ~90s na VM.
3. **Fontes Python do JARVIS ficam no repo** (`modules/ai/jarvis/`) — declarativo.
   Arquivos untracked NÃO entram no build do flake: `git add -A` antes de build.
4. **`sudo ALL NOPASSWD` é temporário** (lab, para o agente não travar). No host:
   sudo escopo mínimo (só `nixos-rebuild` e `clean.sh`) — ver assessment §3.
5. **Nunca editar arquivos do store** (`/nix/store/...`) — mudar a fonte no repo.
6. **Circuit Breaker**: se o backend local falhar 3x, o sistema usa fallback remoto
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
