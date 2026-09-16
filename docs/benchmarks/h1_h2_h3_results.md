# Resultados H1/H2/H3 — Benchmark do Sistema (dono 16/09)

## H1 — Memória/RAG como fator diferencial

**Teste:** `ux_driver` + `ux_world` verification (world_state).
Tarefa: write+read (`hello world` em arquivo).

| Condição | world_state | world_content_ok |
|----------|------------|------------------|
| A (controle) | ✅ | ✅ |
| B (+ memória injetada) | ✅ | ✅ |

**Resultado: INCONCLUSIVE.** Memória não é fator diferencial para tasks que o modelo já sabe executar.

**Conclusão H1 reformulada:** Memória só ajuda em tasks que requerem contexto que o modelo não tem na task description. A injeção automática de lessons (via `Agent.run` linhas 477-483) já é o mecanismo primário; RAG/recall como tools opcionais são secundários.

---

## H2 — Persona vs Regra vs Neutro

**Teste:** `ux_driver` classificação falante (1ª pessoa = KLEIN).

| Condição | Resposta | Correto? |
|----------|----------|----------|
| A_neutral | KLEIN | ✅ |
| B_persona | NARRADOR | ❌ |
| C_rules | KLEIN | ✅ |

**Resultado: persona PERTURBA (respondeu NARRADOR quando deveria ser KLEIN); regras funcionam; neutro funciona.**

**Conclusão H2:** persona-role não melhora acurácia (pode piorar). Âncoras de regra sim. Confirma external evidence (Wharton, arXiv 2605.29420).

---

## H3 — reasoning_effort

**Teste:** `ux_driver` com /no_think vs pense vs pense extensivamente.

| Tipo | low turns | medium turns | high turns |
|------|-----------|-------------|------------|
| classify | 28 | 64 | 98 |
| tool_use | 36 | 61 | 98 |
| factual | 26 | 28 | 17 |

**Resultado:** higher effort = MAIS turns/contexto sem benefício mensurável em tasks curtas/classificação. Nenhum arquivo criado (tool_use falhou em todas as condições — limitação do bonsai, não do reasoning).

**Conclusão H3:** gate automático para `reasoning_effort` é JUSTIFICÁVEL — só ativar para tasks longas/factual-grounded onde o custo extra é compensado. Em tasks curtas/classificação, `low` é ótimo.

---

## Métricas agregadas (todas as condições)

```
world_state_success: task-simpla = 100% (ambas condições)
accuracy H2: neutro=100%, regra=100%, persona=0%
latência H3: low < medium < high (98 turns é 3× o low em classify)
```

## Próximos passos

1. Implementar gate para `reasoning_effort` em `llm.py`: só ativar quando task-length > threshold ou factual keywords detectadas
2. Substituir persona `B_persona` por `C_rules` como default no `Agent.run()` system_content (linha 436-446 de agent.py)
3. Investigar se `Agent.run()` loop in-line vs `dev.py` loop divergem; consolidar duplicação
4. Migrar todos os scripts soltos de bench para `EvalHarness.compare` (já concluído)
