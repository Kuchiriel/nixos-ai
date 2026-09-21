# ANCHOR PLAN — roadmap canônico pós-redteam (Ciclo 3, 20/09)

> Evidência: EXP-A/C/D/E + R1/R2/E6/F/G/J em
> `docs/benchmarks/KNOWLEDGE-BEHAVIOR-RESULTS.md`; estado final em
> `docs/audit/FINAL-EMPIRICAL-STATE.md`. Owner = código citado.

## P0 — nunca regredir (invariantes + teste)
- Stale ≠ success (`stale_artifact:*` em run_task) — owner eval_harness.
- STUCK honesto em provider sem choices (não IndexError) — providers+Agent.
- Outage ≠ vazio (`lessons_unavailable`; recall propaga erro) — agent/memory.
- Rebuild hermético Layer5 (testes sem pgrep/jq) — package.nix.
- Verificação: suite verde (1399+19) + rebuild-host.sh.

## P1 — melhorias justificadas (evidência ≥ replicação)
- Disclosure por classe (`tool_class`, Contract A; E6 9/9) — owner agent.
  Verificação: `test_tool_surface` + KB-regression E2-only.
- Lesson value-free (`JARVIS_LESSON_LINT`, Contract B; R2) — owner memory.
  Verificação: `test_lesson_lint` + KB-regression B3.
- Grounding/state (`knowledge_state`; G/J) — owner core. Verificação:
  `test_knowledge_state` + tarefas Ga/Gb no host.
- KB-regression permanente (`benchmarks/kb_regression.py`, host).
  Verificação: rodar no host, world_ok registrado.

## P2 — próximos experimentos (alto valor)
- E6 completo: threshold de colapso por tamanho de superfície
  (model-specific, bonsai) — rodar 2/4/6/8/12 tools.
- Lesson compiler: episódio→regra automática (testar se generalização
  mecânica preserva B3).
- Plano-âncora explícito (not-the-size: plan/recover ~50% SLM).
- Approval-gap MCP: classificar boundary (NÃO afrouxar sem dono).

## P3 — pesquisa especulativa
- Context optimizer por relevância/frescor (só observabilidade hoje).
- Judge-reliability p/ completion (perturbação de formato).
- Cross-doc synthesis benchmark.

## DEFERRED — sem evidência suficiente
- Finetune/Qwen/MoE (dono; sem GPU).
- Refactor dos dois loops (provar divergência comportamental 1º).
- Regras Bonsai-specific no core (isolar atrás de config, §19-20).
- Remover duplicatas de tools (documentar antes de consolidar).
