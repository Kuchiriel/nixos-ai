# REGRESSION PLAN (20/09 — §45: cada achado vira proteção)

FEITO:
- R1. `stale_artifact:<path>` em run_task + 2 testes (commit 60bda85).
- R2. Testes herméticos sandbox (/proc+jq-condicional; rebuild verde).

ABERTO (ordenado por valor/custo):
- R3. Desambiguar recall vs lessons nas descrições MCP (EXP-E 0/3) —
  teste: probe de seleção no CI? (mock LLM não prova; marcar
  integration + rodar no host).
- R4. Lint value-free em remember_lesson — FEITO (lesson_lint + env + meta) (alerta se contém dígitos de
  episódio? mínimo: documentar formato STATE sem números) — EXP-C.
- R5. Remover ou ligar `approval_callback` (F8) — teste de paridade.
- R6. Guia anti-contaminação em eval (exemplos neutros,UNTID paths
  únicos, rmtree pré-run) — EXP-A/C lições (doc + checklist).
- R7. Replicar EXP-A/C n=5 (H1-variância) antes de fechar dimensões.
- R8. Pendentes dono: push 20+ commits, Qwen/MoE, finetune, docker.

- R9. Contract A: tool_class filter (E6) — FEITO (test_tool_surface).
- R10. knowledge_state + outage emit — FEITO (testes).
- R11. KB-regression host (`benchmarks/kb_regression.py`: RAG+lesson+persist+R8-boundary) — rodar 1×/semana.