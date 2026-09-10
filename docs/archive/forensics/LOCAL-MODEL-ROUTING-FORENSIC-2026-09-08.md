# LOCAL MODEL ROUTING — forensic + implementação 2026-09-08

> Hipótese inicial: "rotear modelos locais pequenos via model.nix".
> Achado central: **llama-server já tem router mode nativo** (load/unload
> por request, sem restart) nos DOIS binários do repo — a hipótese
> SIGTERM-dance (C) está obsoleta. Nenhum `ensure_model()` baseado em
> achismo foi escrito antes da investigação (§0).

## Executive Summary

- IMPLEMENTED: `models.nix:routing` (tiers/capabilities por modelo) como
  extensão da Source of Truth existente; preset INI do router GERADO do
  Nix (sem dict duplicado); `llama-cpp-server` em router mode (:8080,
  max 1 residente); registry JSON em `/etc/jarvis/model-registry.json`;
  `core/model_registry.py` (só carrega/valida); `select_model()` convergindo
  `model_policy.py` (capabilities HARD, tier soft); `core/model_lifecycle.py`
  (`ensure_model` idempotente, lock, timeouts por fase, identidade via
  `/v1/models`); `LLMClient` resolve alias `"default"` pelo registry;
  Agent aceita `model_requirements`; REPL `/model [<id>]`.
- VERIFIED: 20 testes novos (HTTP real via http.server, sem mock de
  router); full suite sem regressão; `nix flake check` verde.
- BLOCKED: benchmark Qwen3-4B (banda p/ HF a 184 B/s — download 2.5GB
  inviável na sessão); ativação do router (exige rebuild+restart do LLM,
  proibido durante sessão ativa + alvo é o host físico).
- HYPOTHESIS: Qwen3-4B como tier fast (tool-native, 2.5GB, precedente do
  perfil `vm`); fork Prism servindo GGUFs upstream no router.

## Current Architecture (encontrada, não presumida)

- VERIFIED: serviço único `llama-cpp-server` :8080, single-model, perfil
  via `hosts/nitro-v15/configuration.nix:156` (`profile="bonsai"` migrado
  p/ `defaultModel="bonsai"` — mesmo efeito). :8081 embed, :8082 rerank,
  :6333 qdrant. Troca de modelo hoje = editar + `rebuild-host.sh`.
- VERIFIED: hot path sem routing local — REPL/Agent → `LLMClient(config)`
  → 1 backend em :8080, `model="default"` no payload (servidor ignora,
  serve o GGUF carregado). `provider_registry.py` ZERO consumers;
  `model_policy.select_tier` só usado por nightwatch/self_test.
- VERIFIED: metadata de capability existia só no path morto
  (`ModelCaps`, `PERSONA_ROUTING`, `ModelTier` com nomes que não existem
  em disco: `qwen3.6-4b`, `qwen3.6-moe-14b`).

## model.nix Source of Truth Audit

- VERIFIED: `models.nix` declara arquivos (fetchurl+sha) + `profiles`
  (flags de execução). Adicionado: `routing{version,default,maxResident,
  models}` (tier/capabilities/params/vram/needsWrapper/serve/iniExtra) +
  perfil `qwen-fast` + `registryJson = builtins.toJSON routing` (eval
  OK, sem realização).
- Duplicação mapeada (3 agentes): Python tem defaults de porta/backend
  (MUST stay — derivação, não metadata); STALE: labels home.nix/vscode-roo
  (Qwen 35B/196K), scripts com store-pins + ngl45 (OOM documentado),
  `model_policy` nomes inexistentes (CONVERGIDO p/ registry nesta sessão),
  comments pi.nix/agents-md. Nenhum `.env` com modelos no repo.

## Existing Router Audit

- Fluxo real: `dev.py:_call_llm` (profile model_id) e `Agent` (config) →
  `LLMClient.chat_with_tools` → backend POST. Seleção = nenhuma (1 modelo).
- `detect_profile` (regex `\d+B`) só afina temp/max_tokens — mantido
  (ortogonal, não é seleção).
- Convergência: NENHUM router novo criado. `select_model()` mora em
  `model_policy.py` (existente); registry é dados, lifecycle é adapter
  HTTP fino; `LLMClient`/backends intactos (+alias default).

## llama.cpp Lifecycle Investigation (fontes primárias)

- VERIFIED (binários locais): nixpkgs 0.4.0 b10809 E prism b10660 expõem
  `--models-dir/--models-preset/--models-max/--models-autoload`
  (README tools/server "Using multiple models", HF blog 2025-12-11).
- Semântica: router sem `-m`; presets em INI (`version=1`, `[*]` global,
  seções por id/HF com `model=<path>`, chaves = args CLI); instâncias
  herdam CLI+env do router; `GET /v1/models` (status
  unloaded/loading/loaded/sleeping/failed), `POST /models/load|unload`,
  SSE `/models/sse`; UM residente por worker (switch = unload+reload,
  3–10s p/ 7B); `--sleep-idle-seconds` existe (não usado — warmup
  explícito preferido p/ boot-ready).
- Decisão §7: E (nativo) >> C (SIGTERM: racy, sem identidade) > B (2
  processos: OOM 6GB p/ strong+fast) > D (complexo p/ ganho incerto) >
  llama-swap (dep Go extra duplicando feature nativa — rejeitado).

## Model Candidates (pesquisa 2026, sem achismo)

- Shortlist p/ 6GB VRAM + tool-calling + PT-BR + llama.cpp: Qwen3-4B-Q4_K_M
  (~2.5GB, tool-native, Apache 2.0, **já em models.nix**), Qwen3-8B
  (~5GB, limite), Gemma 3 4B (~4.2GB, HumanEval 71%, multimodal),
  Ministral-3 8B (Apache 2.0, tool-native, 256K), Phi-4-mini (MIT,
  reasoning 3.8B).
- Descartados p/ fast: 27–32B "confiáveis" (PromptQuorum 2026-09: Gemma 4
  27B, GLM-4.7, Qwen3-32B — exigem 16–24GB, fora do hardware); Q3 e abaixo
  (quebra tool-call); Qwen2.5-7B IQ2_M da proposta (geração anterior sem
  vantagem sobre Qwen3-4B Q4).
- RECOMMENDATION (HYPOTHESIS p/ qualidade, VERIFIED p/ fit): `jarvis-fast`
  = Qwen3-4B-Q4_K_M. Pesado continua Qwen3.6-35B-A3B (`jarvis-strong`,
  com mmproj). Bonsai continua default (decisão de produto pendente).

## Benchmark Results (números reais ou nada)

- VERIFIED (Bonsai :8080 vivo, CPU, chat_with_tools, schema do Agent):
  simples 5/5 (0.1–0.6s, tool certa + args certos, PT-BR ok);
  round duro: condicional ok no 1º passo, web_search ok, PT-BR explicativo
  ok (4.2s) — **H3 FALHA: `echo a; echo b` → chamou `read_file` em
  `output.txt` (tool errada + arquivo alucinado)**. Evidência medida de
  que o tier speed falha em instruction-following sob ambiguidade.
- BLOCKED: Qwen3-4B (fetch 184 B/s; resume: `nix-store --realise
  /nix/store/6awdskfqxbbjgw4s3r7869r1jzmq088q-Qwen3-4B-Q4_K_M.gguf.drv`).
- Citados (docs do repo, não remedidos): Bonsai TG 71–76 t/s; MoE
  13.8–32.5 t/s; ngl45 = OOM.

## Architecture Alternatives

| Estratégia | Latência | VRAM | Complexidade | Robustez | Recomendação |
|---|---|---|---|---|---|
| Router nativo max-1 | cold 5–60s 1ª vez | 1 residente | baixa (INI+Nix) | alta (status/identidade) | **ESCOLHIDA** |
| SIGTERM dance (C) | + restart proc | 1 | média (locks/health) | baixa (sem identidade) | rejeitada |
| 2 processos (B) | zero switch | OOM strong+fast | média (2 health) | média | rejeitada |
| Híbrido RAM (D) | variável | estoura 32GB c/ MoE | alta | incerta | rejeitada |
| llama-swap | como nativo | 1 | média + dep Go | alta | rejeitada (duplica nativo) |

## Chosen Architecture

```text
models.nix routing ─┬─→ models.ini (preset) ─→ llama-server --models-preset (systemd, :8080, max 1)
                    └─→ registryJson ─→ /etc/jarvis/model-registry.json ─→ ModelRegistry
 arrivarequirements ─→ select_model() ─→ ensure_model() ─→ LLMClient(model=<id>) ─→ backend (inalterado)
```

- Default EFETIVO preservado: host→bonsai, vm→jarvis-fast (= perfis
  antigos). Warmup best-effort no boot (postStart, nunca derruba).
- Cloud cascade (litellm) intocada; registry é local por construção.

## Routing Policy

- `select_model({capabilities, tier?, stage?, local_only?})` → (id, reason).
  Capabilities HARD (ModelRouteError, nunca incapaz silencioso); tier soft
  (fallback registrado); rank (tier, params_b); local_only documentado.
- Agent: `model_requirements=None` = zero mudança; com requirements:
  select→ensure→swap de `config.llm_model` + rebuild do LLMClient + evento
  `model_routed` (requested/selected/switched/previous/latency/reason).
- REPL: `/model` (uso + residente + tiers), `/model <id>` (valida + ensure
  + override de sessão). Voice/API/WebUI: default (inalterados).

## Lifecycle State Machine

`discover → (noop | lock → re-check → load → poll[loaded+id] → health) → report`.
Fases de erro nomeadas (discover/lock/load/readiness/health); single-model
(404) honesto; concorrência via flock + re-check (sem interleave A/B);
timeouts: lock 330s, load 300s, poll 2s, health 10s, warmup 5min.

## Failure Recovery

Servidor fora → discover; lock preso → lock; preset desconhecido → load;
status failed → load; nunca-loaded → readiness; loaded sem health →
health. Report nunca afirma switch sem identidade (`loaded` + id + health).

## Concurrency

flock em `state_dir/model-switch.lock` + re-check sob lock. Teste com 4
threads: todos com identidade verificada, estado final consistente.

## Observability

SwitchReport + evento `model_routed` + warning em fallback de registry.
Sem 2º sistema de métricas (logger + SessionTelemetry existentes).
`reason` registra tier_fallback/noop/seleção.

## Tests

- 20 novos em `tests/test_model_routing.py` (registry 6, policy 6,
  lifecycle 7 com router fake HTTP REAL, Agent integrado 1).
- Achados pelos testes: `continue`-like não houve; mas `unloaded` como
  "falha" (corrigido: só `failed` é terminal), base_url com `/v1`
  (normalizado) e 2 asserts do solar_probe que cristalizavam o
  pass-through de `"default"` (atualizados p/ o contrato do alias).
- Full suite: 1040 passed, 5 failed (as 5 infra conhecidas:
  nightwatch_real_e2e x3 + platform_e2e x2), 21 skipped, 2 xfailed,
  3 xpassed; flake: `nix flake check --no-build` verde
  (após corrigir bloco duplicado extraFlags/bindAddress no edit inicial);
  unidades router avaliadas p/ nitro-v15 (3 presets, prism, default
  bonsai) e nixos-lab (2 presets, default jarvis-fast, t4);
  reverso dos afetados: OK.

## Performance

- Switch: não medido de ponta a ponta (router inativo); literatura: 3–10s
  (7B) — MoE 20GB estimado em dezenas de s (warmup cobre o boot).
- Métrica-alvo (§28): latência de conclusão × qualidade — Bonsai vence
  t/s e perde instrução (H3); fast deve vencer tarefa simples de ponta a
  ponta (HYPOTHESIS, teste de comparação documentado em Remaining Work).

## Risks

- P1: fork Prism servindo Qwen no router (needsWrapper) — NÃO verificado
  (verificação: prism bin + Qwen3-4B em :18080 CPU quando o arquivo
  existir; fallback: router upstream + bonsai fora — exige 2 unidades).
- P1: router inativo até rebuild+restart (mudança Nix validada só por
  eval/flake; ativação = próxima janela, host físico).
- P2: `models-max 1` + request durante switch (comportamento de fila do
  router não caracterizado); presets exóticos (split-mode/EHS) não
  portáveis p/ INI (throw explícito); warmup MoE lento se default virar
  strong; fallback embutido divergindo do Nix (warning + teste de
  estrutura, não de conteúdo).

## BLOCKED

Benchmark Qwen3-4B (banda); ativação router (rebuild/restart); default
fast vs bonsai (produto); cloud-vs-local (fora do escopo — registry é
local); Bonsai motor (intocado, §22); Hyper-V (intocado, §23).

## Product Decisions

Default model (bonsai/speed vs jarvis-fast), quando usar strong
automático (heurística de complexidade), voz pinada no fast?, WebUI
expondo tiers, persistência de preferência de modelo por sessão.

## Migration Path

1. Realizar Qwen3-4B no host (`nix-store --realise` do .drv).
2. Verificar Prism+Qwen (:18080 CPU).
3. `rebuild-host.sh` em janela (router assume :8080; warmup bonsai).
4. Comparar fast vs speed em agent loops reais; decidir default.
5. (Opcional) `/model` no WebUI; heurística auto-tier no Agent.

## Remaining Work

- Teste de comparação Bonsai×Qwen3-4B no suite H0–H3 (script na seção
  Benchmark; trocar base_url p/ :18080).
- Limpar labels STALE (home.nix, vscode-roo 196K, pi.nix, agents-md) — P3,
  fora do escopo p/ não misturar.
- Deletar `provider_registry.py`? NÃO (ADR-004 BLOCKED).
