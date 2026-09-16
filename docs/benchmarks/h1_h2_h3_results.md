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

---

## H4 — Model swap idle-reload (dono 16/09, pós-fixes do outro agente)

**Swap latency real** (`ensure_model` bonsai↔jarvis-fast, n=3, idle-reload):
```
n=0: up=5.6s | down=2.1s
n=1: up=2.1s | down=2.1s
n=2: up=2.1s | down=2.1s
```
Infra **viável**: 2.1s por troca (idle-unload + reload funciona).

**A/B task difícil (pasta+arquivo, n=5, PTY real, world-state verificado):**
| Modelo | world_ok | latência média |
|--------|----------|----------------|
| bonsai (default) | **5/5** | 14.4s |
| jarvis-fast | 3/5 | **9.1s** |

**A/B task simples (arquivo único, n=5):** ambos 5/5 (~3s) — sem diferença.

**Resultado: hipótese CONTRA-dita.** Trocar modelo para write tasks degrada
world-state (5/5 → 3/5). Bonsai é mais confiável; jarvis-fast só ganha
latência (~5s). Como WORLD STATE é a métrica primária (§10), **default
bonsai permanece** (§21 preservado). Swap condicional por tarefa: NÃO
justificado para escrita.

**Nota histórica:** bonsai 5/5 neste experimente vs 0/9 do braço B do
outro agente (pré-fixes) — as 8 correções (`5422dc0`: validator ensina
criar, allowlist nomeia tool, promise-guard, claim-checker…) moveram o
indicador de 0/9 → 5/5. LOCAL_EVIDENCE de que as correções funcionam.

**Swap idle-reload permanece útil para:** strong tier em
planning/review (qualidade > latência); recovery de falha repetida de
escrita (STUCK → swap); tarefas de análise longa que precisam de
raciocínio profundo.
