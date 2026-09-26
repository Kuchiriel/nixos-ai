# RECONSTRUCTION PLAN — JARVIS Agent Runtime Kernel (26/09/2026)

> Origem: diagnóstico do dono sobre o HEAD público 586ec31 + forense em
> `docs/audit/RUNTIME-FORENSICS-CURRENT.md`. Fontes: `~/Books/papers/*-kernel.md`,
> `web-openai-harness-engineering.md`, `web-qdrant-hybrid-queries.md`,
> `web-openai-agents-api-architecture.md`, `web-harbor-terminal-bench.md`.

## Alvo

```
                    ┌─────────────────────────┐
                    │      JARVIS KERNEL      │  jarvis/runtime/
                    │ AgentRuntime.run(task)  │  UM loop cognitivo
                    │ session/context/tools/  │
                    │ policy/model/observer/  │
                    │ verifier/recovery/      │
                    │ persistence/telemetry   │
                    └───────────┬─────────────┘
           ┌──────────────────┼──────────────────┐
         CLI/REPL            MCP            Nightwatch
       (thin adapter)   (transport)      (supervisor)
         Voice            WebUI/Telegram  Benchmarks (clientes)
```

Regra: **existe um único loop cognitivo; adapters não reimplementam o ciclo.**
`Agent = Model + Harness` — 98,4% do valor está no harness (OpenAI/Claude Code).

## Grafo de migração (ordem = dependência)

```
F1 kernel shell     F2 ToolRegistry   F3 ContextAssembler  F4 Knowledge plane
  (runtime/ pkg +      (1 schema,        (1 pipeline,         (retrieve() único,
   AgentSession +       MCP=transporte)   onboarding JIT)      RRF+rerank fixos)
   convergence tests)
        │                    │                    │                    │
        └────────┬───────────┴──────────┬─────────┴──────────┬─────────┘
              F5 Completion            F6 Model/Provider     F7 Nightwatch→
              (contrato único,          choke point          supervisor
               todo DONE passa)         (models.nix SSOT)    (sem loop próprio)
                        │                    │
                   F8 dev.py thin ──────┴──── F9 personas/modes (1 identidade)
                                                 │
                                    F10 Harbor adapter (calibração externa)
                                                 │
                                    F11 otimização Bonsai (SÓ aqui)
```

## O que criar / modificar / deletar (alto nível)

- CRIAR: `jarvis/runtime/` (`__init__`, `session.py`, `registry.py`, `context.py`,
  `agent_runtime.py`, `policy.py`, `lifecycle.py`), `tests/test_runtime_convergence.py`
  (linter estrutural: 1 loop, 1 registry, 1 assembler — trava o drift).
- MODIFICAR: `agent.py` (extrair p/ runtime, virar compat fino), `dev.py` (só REPL/render),
  `harness.py` (supervisor: queue+branch+checkpoint+review → chama `runtime.run`),
  `mcp_server.py` (transporte sobre o registry), `persona*.py` (1 identidade),
  `provider_registry` (choke point executável), `rag/memory/vault` (providers c/ contratos).
- DELETAR (p/ `archive/` com motivo): `persona_executor.py` (executor órfão),
  `devtools.semantic_search` (fachada paralela), `nightwatch/context_budget.py` (shim),
  `tokens.py` OU `context_budget.estimate` (ficar 1), 1 dos 2 Fernets, 1 dos 2 CircuitBreakers,
  schemas-fantasma (`CAPABILITY_TOOLS` nomes inexistentes), scripts sem caller.
- QUEBRAR: APIs internas de `Agent.run`/`_run_agent_loop`/`Harness.execute_task`
  (externo intacto: CLI, MCP stdio, Telegram, WebUI).
- PRESERVAR: `LLMClient`, `handle_dev_tool`, `check_completion`, `LoopDetector`,
  `ToolValidator`, `ContextBudget` (migrar p/ dentro), `models.nix` SSOT, Qdrant+provenance,
  filesystem jail, git isolation, telemetry, harness-suite (vira cliente do runtime).

## Riscos + rollback

- Risco 1: extração quebra REPL diário do dono → mitigação: cada fase termina com
  `dev_once` + `ask` + bateria v2 verdes; branch por fase (`kernel/f1..f11`).
- Risco 2: testes antigos protegem arquitetura errada → reescrever, nunca `xfail` eterno
  (convergence test conta loops: 3→2→1).
- Risco 3: sessão/MCP externos quebram → contrato externo congelado (stdio MCP, CLI flags).
- Rollback: 1 commit por fase, `git revert` limpo; `archive/` guarda removidos c/ motivo.

## Critério de conclusão (do briefing — vira checklist do REPORT)

Um único AgentRuntime · CLI sem loop próprio · Nightwatch sem loop próprio · MCP sem
lógica própria · 1 ToolRegistry · 1 ContextAssembler · 1 Completion · 1 choke point
model/provider · contratos memory/knowledge · systemd nos pesados · sessão serializável ·
recovery no runtime · progressive-disclosure · modelos trocáveis sem tocar runtime ·
bonsai+forte+CLI+MCP+nightwatch funcionando · testes da arquitetura nova · morto removido ·
docs reconciliadas.
