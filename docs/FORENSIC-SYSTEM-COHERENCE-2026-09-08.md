# FORENSIC SYSTEM COHERENCE — 2026-09-08

Sessão de investigação + refatoração (pré-missão voz/RVC + missão 52 fases,
escopo executado: pré-missão completa, consolidação project-root, personas,
MCP, memória, voz, registries; restante mapeado como BLOCKED/produto).
Evidência primária: código + testes executados. Docs anteriores tratadas
como pista, não verdade.

## Executive findings

1. `--clone` quebrado por env ausente no zsh (bash tinha, zsh não) +
   binário instalado STALE reportava sucesso-falso (driver converteu 0
   arquivos; sem verificação de output). Ambos corrigidos e provados.
2. Método RVC superior ao dos scripts: patchelf do venv → loader nix-ld
   (prova `env -i`); zero LD manual, imune a GC. Env declarativo bash+zsh.
3. Project root: 3 resolvers + 4 mutadores + monkeypatch de isolamento →
   UMA API (`core/paths.py`: ctx > env > walk > fallback), contextvar no
   lugar de monkeypatch (mecanismo que o próprio código prescrevia).
4. Personas: Registry canônico, Executor consumidor, jarvismodes com
   overlap real (stack de identidades + modo não persiste) → ADR-003 BLOCKED.
5. MCP: adapters finos corretos, EXCETO `_handle_rag_search` que recriava
   coleção com schema divergente → convertido ao store canônico.
6. Registry de providers (política de privacidade): declarado, testado,
   mas ZERO consumidores → ADR-004 BLOCKED (choke point não ligado).
7. Suite do Agent era pulada no build (`pytestmark integration` global) →
   fixture + unmark: 833→834 passando no sandbox, 0 failed.
8. Detalhes com efeito real: lessons("") → lessons(prompt); waybar mentia
   IDLE durante listening (writer sem ts); STT small agora declarativo;
   tiny.en morto (149MB, conteúdo errado) removido.

## Architecture graph

```text
ENTRYPOINT (jarvis CLI subcommands + jarvis-{stt,speak,voice,waybar,...})
  ↓  SESSION (shell env declarativo home.nix; services systemd user)
REPL (main ask→router | agent direto | dev REPL)
  ↓  AGENT RUNTIME (Agent.run: LLMClient→tools→validator→context guard)
DECISION (router: fastpath/read/doctor/nixos/rag/agent por evidência)
CONTEXT (system+persona+lessons(prompt)+repo/agent ctx; budget por prompt)
CAPABILITIES (devtools canônicas; Registry personas; Registry providers [unwired])
TOOLS (execute_shell/read_file nativas; MCP adapters finos p/ externos)
OBSERVATION (tool result + validation warnings + audit JSONL + EventBus)
FEEDBACK (status canônico → waybar signal+poll; notify/sound efêmeros)
VOICE (wakeword daemon two-phase/VAD/pre-roll → brain jarvis voice → STT→LLM→TTS[+RVC] → ack cache)
```

## Source-of-truth map

| Domínio | Canônico | Mortos/migrados |
|---|---|---|
| Project root | `core/paths.find_repo_root` (+set/use) | 3 resolvers, REPO_ROOT snapshot, 4 mutadores diretos |
| LLM | `LLMClient` (+factory/backends) | `requests.post` no Agent (removido sessões anteriores) |
| tools filesystem | `devtools.read_file/str_replace` | spawn duplicado RVC (consolidado `_run_driver`) |
| RAG store | `QdrantStore` (dense+bm25) | ensure via requests no MCP (convertido) |
| RVC env (shells) | `scripts/rvc-env.sh` | blocos inline duplicados bash/zsh |
| STT models | `models.nix whisper-small{4}` | wget \|\| true, tiny.en |
| Voice status | `/tmp/jarvis-status.json` + `set_status` | writer do daemon sem ts (corrigido p/ contrato) |
| Personas identidade | `PersonaRegistry` | — (jarvismodes overlap → ADR-003) |
| Routing privacidade | `provider_registry` (DECLARADO, unwired → ADR-004) | — |
| Context budget | `core/context_budget` único | shim nightwatch (compat, sem lógica) |

## Duplication matrix

| Responsabilidade | Canônica | Eliminadas |
|---|---|---|
| project resolution | core/paths | paths.find_repo_root duplicado, categories inline, devtools._project_root, 7× env-if-exists, harness._get_project_root |
| task override | contextvar use_project_root | monkeypatch REPO_ROOT em 5 módulos |
| RVC spawn | _run_driver(extra_env) | clone_wav inline (~60 linhas) |
| RVC env shell | rvc-env.sh | blocos bash/zsh divergentes |
| lessons query | prompt | `""` (embedding vazio) |
| Qdrant ensure | QdrantStore | bloco requests no MCP |
| Agent tests no build | fixture JARVIS_STATE_DIR | pytestmark global (2 arquivos) |

## REPL findings

- Rota read nova: path exato → direta (zero LLM/RAG); precedência sobre
  wildcard audiobook documentada e testada (11 contratos); contratos
  antigos preservados.
- Exposição: read_file sempre + execute_shell/MCP condicionais (2 tools
  base — sem explosão de surface; dev.py com 21 é outro runtime).
- Decisões determinísticas: path→read, composta→agent, pergunta→RAG/agent
  (guardas por regex ancorada + path extraction; testes adversariais em
  test_read_route.py).

## Tool selection findings

- Agent só decide entre tools anunciadas (2); roteador decide o resto
  deterministicamente. Sem progressive disclosure adicional necessária
  neste surface.
- Resultados: contrato texto + `ERROR:` prefix + `[validation:]` warnings;
  truncamento TOOL_OUTPUT_MAX_CHARS preservado.

## RAG findings

- Canonical HybridSearch/HybridIndexer (dense+bm25+boosts+rerank) íntegros;
  coleções isoladas (code/memories/books).
- Trigger continua keyword-based no router (limitação conhecida, fora do
  escopo: exigiria classificador; RAG nunca é chamado sem rota/gatilho).

## MCP findings

- 20 tools auditadas: todas delegam a implementações canônicas
  (handle_dev_tool, EpisodicMemory, HybridSearch, vision). Interface
  externa legítima (Roo/opencode/WebUI), não duplicação interna.
- Corrigido: ensure de coleção com schema divergente (detalhe acima).

## Memory findings

- EpisodicMemory (eventos) vs RAG (código): coleções e códigos distintos,
  sem mistura. ✅
- Bug corrigido: lessons("") → lessons(prompt) + teste de contrato.
- Sem rota `memory` no router (recall só via CLI/memória injetada) —
  gap documentado (harness §eval cobre parcial).

## Persona findings

Ver ADR-003. Resumo: Registry canônico + Executor consumidor (legítimos);
jarvismodes com overlap (stack + não-persistência provados) → BLOCKED.

## Project isolation findings

- Mecanismo migrado p/ contextvar; testes reescritos provam A/B/A real
  (git repos independentes) + restore em exceção + fix assert vacuoso.
- Precedência final: task-ctx > env válido > walk-up > fallback.
- Exceção intencional: goal_loop default externo por nome (documentado).

## Configuration findings

- Env vars fragmentadas de LLM mortas (sessão anterior); RVC unificado
  em rvc-env.sh; STT espelha models.nix; wakeword service já era
  declarativo (inclusive LD_PATH, agora redundante mas inofensivo).
- `JARVIS_PROJECT_ROOT`: escrita só via set_project_root; leitura só
  via find_repo_root (exceto goal_loop, intencional).

## Hardcode findings

- Store paths hardcoded eliminados (bootstrap heredoc, bash init);
  serviço usa `${pkgs...}` (declarativo, mantido).
- `127.0.0.1` restantes: defaults de Config com override por env
  (padrão legítimo) + doctor check local (aceitável, documentado).
- Removidos nesta sessão: LD hardcoded (3 lugares), tiny.en URL quebrada.

## Control Plane findings

- EventBus único (`get_bus`), async sólido (timeout/DLQ/tasks), sem
  blocking. StateStore seções; set_status publica VOICE (daemon cobre
  arquivo+signal; store só via set_status — gap parcial documentado).
- Auditoria anterior (SSE leak etc.) mantida; sem regressão.

## Voice findings

- --clone: PROVADO E2E (15.9s Jarvis, arquivo real, binário novo, zsh
  limpo). Fake-success do binário stale explicado (stdin vazio → 0
  conversões + sem verificação).
- STT small: PROVADO (PT-BR coerente); modelos declarativos pós-rebuild.
- Wakeword daemon: ativo, VAD adaptativo detectando fala, two-phase,
  pre-roll 770ms, scorer com fallback. Maduras; sem redesign.
- Coerência: waybar lê fonte canônica (signal+poll); writer do daemon
  alinhado ao contrato ts (fix desta sessão).

## Async findings

- Sem blocking novo introduzido; EventBus async íntegro (verificado
  sessão anterior, sem mudança). voice_loop é síncrono por design
  (subprocess isolado STT/RVC) — correto, não alvo.

## Error-path findings

- `except: pass` restantes: paths opcionais (persona/profile/lessons) +
  telemetria best-effort — graceful degradation legítima, não silenciamento
  de path crítico (tool exec/LLM propagam).
- `|| true` do wget eliminado com a declaratividade STT.

## Test integrity findings

- 50 testes do Agent eram pulados no build (marks globais) → rodam agora.
- 1 assert vacuoso corrigido (`or True`); 1 binário inexistente no sandbox
  trocado preservando propósito (hostname→echo).
- Falso-verde do binário stale (RVC-BATCH-OK 0) eliminado na origem
  (verificação de output existe no caminho canônico).

## Dead-code findings

- Removidos: resolvers duplicados, REPO_ROOT snapshot, monkeypatch
  machinery, spawn RVC duplicado, bloco env morto, _regex.txt (anterior),
  tiny.en (149MB), wget morto, imports mortos (file_guard etc.).
- `archive/` verificado sem imports produtivos (mantido como histórico).

## Refactors performed

1. `core/paths.py` novo + shim + 12 arquivos migrados (commits: paths).
2. RVC: patchelf+nix-ld, rvc-env.sh, bootstrap, home.nix bash+zsh.
3. STT declarativo (models.nix ×4 + links + remoções).
4. MCP rag ensure → store; voice status ts; lessons(prompt).
5. ADRs 003/004; testes (+13 no total do período; 2 reescritos de contrato).

## Code deleted

~-350 linhas líquidas (resolvers, monkeypatch, spawn duplicado, env
duplicado, wget, tiny.en ref, imports, asserts vacuosos). +~200 linhas
úteis (paths.py, testes de contrato, ADRs)._

## Remaining BLOCKED

1. Personas jarvismodes (ADR-003) — produto.
2. Registry privacy wiring (ADR-004) — produto + hot path.
3. dev.py convergence (agent_loop.py) — engenharia grande.
4. WebUI canonical-state audit; long-run E2E (P3-2).
5. `jarvis chat` vs `ask` overlap (dois entrypoints conversacionais —
   observado, não investigado a fundo).

## Remaining product decisions

As 5 acima + default multi-provider (custo×latência×privacidade).

## Evidence

- Builds Nix verdes: sandbox com suite (834 passed, 0 failed).
- Arquivos de prova: `/tmp/opencode/prova_sem_ld.wav`,
  `.../jarvis_tts_538684693-clone.wav` (15.9s, 24kHz).
- Logs: clone_e2e/direct/nold/final, stt_probe/postrebuild, rebuild(2).
- Commits listados abaixo; suite local 998+ (5 infra pré-existentes).

## Addendum 2026-09-08 ~11h — Waybar flicker (CPU + REC fantasma)

Causa raiz única com dois sintomas: `pkill -RTMIN+8 waybar` (refresh do
módulo a cada set_status + pulse do daemon a cada ~1.6s) casava por regex
substring `waybar-cpu`, `waybar-memory`, `waybar-gpu`, `*-waybar` — o sinal
matava os scripts no meio do `sleep 0.5`/read (reproduzido: 4/15 runs,
rc=170=128+SIGRTMIN+8, zero bytes) e gerava os 7 defuncts. Fix: `-x`
(feedback.py + daemon). Removido `wait $PPID` teatral do cpuScript.

REC fantasma: daemon afirmava `listening` no onset do VAD (ruído 456-773
dispara gate 400), até 10s antes de qualquer verificação, com falsos
positivos do scorer entrando em fase 2. Fix: estado `hearing` (HEAR) até
confirmação; TTL cobre hearing; waybar mapeia. Evidência: watch de 2min
+ journal RMS correlacionado.

## Before/after metrics

| Métrica | Antes | Depois |
|---|---|---|
| Build sandbox | 781 passed (50 pulados) | **834 passed, 0 failed** |
| Suite local | 987/5 infra | 998+/5 infra (mesmas) |
| Resolvers de projeto | 3 + 4 mutadores + monkeypatch | 1 API (ctx/env/walk) |
| `--clone` no zsh | ERROR ausente | áudio Jarvis real |
| LD manual RVC | 6 exports + store hardcoded | zero (loader nix-ld) |
| STT provisioning | wget \|\| true + tiny.en morto | 4 symlinks declarativos |
| Tools Agent | 1 condicional | 2 (read_file sempre) |
| Rota "leia X" | RAG/audiobook | read direta |
| Lessons recall | query "" (aleatório) | query prompt |
| MCP rag ensure | schema divergente | store canônico |
| Waybar listening | IDLE (sem ts) | estado real |
| Registry privacidade | unwired (não quantificado) | unwired + ADR (honesto) |
