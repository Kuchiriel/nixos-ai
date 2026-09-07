# HANDOFF.md — Project Index

> Updated: 2026-09-03

## Quick Start

```bash
# Tests
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q

# Build
nix build .#jarvis --no-link && nix flake check

# WebUI
jarvis-webui  # port 8090
```

## Architecture

```
PersonaExecutor
  → TaskQueue (persistent)
    → Harness (pipeline engine)
      → LLM (via _default_call_llm)
        → Patcher + SafeEditor
          → Validator (syntax + tests)
            → Evaluator (review)
              → Checkpoint + Safety
                → Git commit
```

## Module Map

### Core (jarvis/core/)
- config.py — Configuration (31 imports)
- eventbus.py — Event bus (17 imports)
- memory.py — Episodic memory (17 imports)
- rag.py — Hybrid search (15 imports)
- voice.py — TTS/STT (9 imports)
- feedback.py — Notifications (9 imports)
- workspace.py — Project discovery (8 imports)
- persona.py — Persona registry (7 imports)
- gaming.py — Gaming mode (3 imports)
- health_monitor.py — Backend monitoring (3 imports)

### Nightwatch (nightwatch/)
- harness.py — Main execution engine
- task_queue.py — Persistent task queue
- patcher.py — LLM patch application
- safe_editor.py — Atomic writes
- validator.py — Syntax + test validation
- evaluator.py — Independent review
- checkpoint.py — State persistence
- safety.py — Branch isolation

### Control Plane (control_plane/)
- plane.py — Unified orchestration
- events.py — 58 event types
- state.py — Thread-safe state store
- commands.py — Typed command registry
- notifications.py — Multi-channel routing
- systemd_adapter.py — Safe systemctl

### WebUI (webui/)
- api.py — FastAPI backend (12 endpoints)
- server.py — Uvicorn launcher
- frontend/ — SvelteKit (12 routes, SSE)

## Services

| Service | Port | Status |
|---------|------|--------|
| llama-server | 8080 | Check health |
| embeddings | 8081 | Check health |
| rerank | 8082 | Check health |
| qdrant | 6333 | Check collections |
| WebUI | 8090 | Check /api/health |

## Tests

- 859 passed, 0 failed, 26 skipped, 5 xpassed
- Core: eventbus, feedback, queue, harness_e2e, gaming
- Nightwatch: validator, safe_editor, safety, checkpoint
- Control Plane: events, state, commands, notifications

## 2026-09-07 — opencode auth + fast path enriquecido

### opencode (config/home.nix)

Problema real: "só alguns modelos funcionam; header/token error na maioria".
Duas causas raiz (ambas corrigidas em home.nix):

1. `headers.Authorization = "Bearer \${VAR}"` — o opencode NÃO expande `${VAR}`;
   a sintaxe é `{env:VAR}`. Virou `options.apiKey = "{env:VAR}"` em
   openrouter/groq/cerebras/together/huggingface (sem header Authorization;
   o SDK monta o header a partir do apiKey). Verificado: `opencode debug config`
   mostra o apiKey expandido com a chave real.
2. Shell do usuário é **zsh** mas as chaves só eram carregadas em
   `programs.bash.initExtra` → zsh abria opencode sem env vars. Adicionado o
   mesmo sourcing (keys-wrapper.sh + opencode-auth-sync.sh) ao
   `programs.zsh.initContent`.

Versão: `pkgs.kilo` = opencode do nixpkgs-unstable pinado no flake.lock
(1.18.16, lock de 2026-08-13). `nix run nixpkgs#opencode` é o canal estável
(1.15.10, MAIS VELHO). autoupdate não funciona em Nix. Atualizado:
`nix flake lock --update-input nixpkgs-unstable` → 2026-09-07 (deve trazer
~1.18.29 no próximo rebuild). Modelos mortos atualizados: groq →
`qwen/qwen3.6-27b`, cerebras → `qwen-3.8-27b`.

Testes manuais pós-fix (via OPENCODE_CONFIG com apiKey): groq responde,
cerebras = "Payment required" (conta sem billing — não é config), openrouter =
rota OK (modelos :free às vezes sem endpoint — capacidade). Chaves validadas
por curl direto (HTTP 200).

### Fast path (rules.py + router.py) — portado do legado Manjaro/AI_SYSTEM

- Engine: `! array nome = a b c` + `@nome` (dentro de `[]`/`()` também),
  `[*]` (wildcard opcional), `#` (número), `<star1>..<starN>`, ordenação por
  especificidade (literal > número/alternativa > opcional > wildcard),
  normalização de entrada (tira "jarvis/hey/ei/por favor/pode/você pode/fala"
  do INÍCIO, nunca do final), wildcard `*` agora lazy (não engole o 2º número
  em matemática).
- Handlers novos: `math` (ast-safe, sem eval; "quanto é 8 + 2" → 10, aceita
  vírgula decimal e multi-operando) e `screenshot` (grim).
- DEFAULT_RULES: audiobook com controle completo (pausa/continua/next/prev/
  status no tópico, sem expulsar do tópico), voz com variações PT/EN, sistema
  (cpu/memória/disco/temperatura/hora/data/kernel/uptime/processos),
  saudações, screenshot.
- SEGURANÇA: matching ANCORADO — trigger curto só casa frase EXATA;
  filler no fim nunca é removido; regras com `*` que roubariam pergunta real
  foram removidas (`que livros *`). Testes negativos garantem que perguntas
  reais ("explique como funciona uma cpu", "quanto é a capital da frança")
  NUNCA casam fast path → vão pro LLM.
- Testes: `tests/test_rules.py` (26 → 33 testes). Rodados: test_rules,
  test_router, test_voice, test_benchmark, test_regression, test_intents —
  verdes no env disponível; falhas de `requests`/`hypothesis` são só do env
  ad-hoc (bare pytest), não regressões (a suíte Nix roda com deps completas).

### Pendências abertas

- Validar opencode pós-rebuild (versão esperada ~1.18.29 + modelos reais).
- Cerebras: conta sem billing (pagamento necessário para usar).
- RiveScript legado tem mais regras aproveitáveis (git, typing, vision) —
  portar quando houver handler correspondente no jarvis atual.
