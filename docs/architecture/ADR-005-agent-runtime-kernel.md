# ADR-005 — JARVIS Agent Runtime Kernel (aceita 26/09/2026)

> Status: ACCEPTED. Substitui na prática ADR-003 (convergência dev.py, bloqueada até
> reconstrução do loop) e operacionaliza ADR-001 (pipeline User→…→Memory) e ADR-002
> (Working/Episodic/Semantic/Project). Forense: `docs/audit/RUNTIME-FORENSICS-CURRENT.md`.

## Contexto

Três loops cognitivos com semânticas diferentes (`agent.py:1057`, `dev.py:1997`,
`harness.py:1687`) + 4 dialetos de tool schema + 4 fachadas de RAG + roteamento ×4.
Toda melhoria num loop pode não existir nos outros ("o teste passou mas o produto usa
outro caminho"). Pesquisas (2605.13357, 2609.00006, 2605.23950) e a engenharia de harness
da OpenAI convergem: **o harness — não o prompt/modelo — é o sistema do agente**.

## Decisão

1. **Um único `AgentRuntime.run(task) -> AgentResult`** em `jarvis/runtime/`. Ciclo fixo:
   TASK → CONTEXT → MODEL → TOOL/TEXT → OBSERVATION → STATE → VERIFICATION →
   RECOVERY/CONTINUE/COMPLETE/STUCK. Nenhum adapter reimplementa.
2. **Base canônica = `agent.py:Agent.run`** (vereditos honestos, repair, cascata, budget-stop,
   finalize com evidência). dev.py cede sessão/compaction/checkers/catálogo/approval;
   nightwatch cede supervisor (branch/checkpoint/review/ratchet) como CAMADA.
3. **`ToolRegistry` único** (name/description/schema/capability/risk/approval/handler/
   verification). MCP = transporte. `tool_surface` vira propriedade estrutural (`for_task`).
4. **`ContextAssembler` único** (onboarding JIT: ids leves, detalhe via tools).
5. **Knowledge/Memory como providers** (`retrieve()` etc.; o runtime decide quando usar).
   RRF default, rerank como stage 2, pesos só com eval set.
6. **Completion único**: todo DONE passa por VERIFIED/UNVERIFIED/STUCK/FAILED/DEFERRED.
7. **Choke point model/provider único**; `models.nix` SSOT (mutation tests anti-drift);
   regras por capability, nunca `if bonsai`.
8. **Nightwatch = supervisor** (queue+checkpoint+scheduler+isolamento+retry+`ModelLifecycle`
   via systemd). `dev.py` = REPL fino. Personas: 1 identidade (`PersonaRegistry`),
   Mode = sessão/UX.
9. **Linter estrutural** (`test_runtime_convergence.py`): conta loops/registries/assemblers
   no repo e trava o teto (3→2→1). Drift arquitetural vira falha de teste, não de revisão.
10. **Harbor só pós-kernel** (calibração externa, subset primeiro, nunca otimizar p/ task).

## Consequências

- APIs internas de `Agent`/`dev loop`/`Harness` podem quebrar; superfície externa congelada.
- Código morto vai p/ `archive/` com motivo (regra do dono: nunca apagar sem rastro).
- Bateria interna (harness-suite) vira cliente do runtime; Harbor depois.
