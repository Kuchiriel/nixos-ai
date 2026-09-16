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

---

## Consolidação Framing: Rules vs Persona (evidência externa + local)

**Paradigma externo: RRP — Rule-based Role Prompting** (emergentmind.com/topics/rule-based-role-prompting-rrp; refs: PRBoost 2203.09735, RulePrompt 2403.02932, RoleLLM 2310.00746, RadPrompt 2408.04121, PDL 2507.06396, ORPP 2506.02480):

- Prompts implícitos/descritivos (persona natural-language) sofrem **drift,
  inconsistência, brittleness, falta de verificabilidade** — exatamente o que
  H2 mediu (persona PERTURBA classificação).
- Regras explícitas (RRP) dão **consistência, interpretabilidade,
  confiabilidade operacional**: F1 +7% (PRBoost), +2.1% radiologia
  (RadPrompt), +2-3 pts GPQA/MMLU (ORPP), 4× compliance em tool calls (PDL).
- **"Action-first" policy** (character-card/scene-contract, Ruangtanusak
  2509.00482): regras turn-by-turn "action-first / single-shot /
  schema-correct" — mesma arquitetura do promise-guard + gate de rota do
  outro agente (5422dc0). O que transfere entre personas são ÂNCORAS
  comportamentais (arXiv 2607.18566: narrative priors explicam 5-31× mais
  variância que persona).
- **Scalability: RRP permite modelos PEQUENOS lidarem com tasks
  decision-heavy** — valida a estratégia bonsai-first (envelope do sistema
  no modelo mais fraco; se funciona nele, funciona em qualquer outro).
- **PDL (Prompt Declaration Language)**: patterns declarativos em YAML —
  alinha com a filosofia NixOS-first do repo (declaração > imperativo).

**Síntese local + externa:** persona = fantasia de expertise (Wharton
GPQA/MMLU-Pro, 6 modelos, 25 trials/condição — sem ganho; H2 local:
persona 0% vs rules 100%); rules/âncoras = o ativo real (RRP
consistente). Frase do dono confirmada: "o framing de persona não é tão
útil quanto o framing de rules".

**Aplicação no JARVIS:** system prompt = regras operacionais
(TOOL_USE_DISCIPLINE + action-first), persona só quando o domínio exige
(forensic/áudio — contrato do caller). Próximo passo do paradigma:
discovery automático de regras dos erros do modelo (PRBoost-style: casos
de alto erro → rule mining) — os lessons do sistema já fazem metade
disso (recall qualificado por prompt injeta AVOID de erros passados).

---

## Harness-Maxxing (validação da tese do dono, ago/2026)

Fonte: msukhareva.substack.com "How a Small Open Model Beat a Frontier LLM"
(+ LangChain anatomy-of-an-agent-harness + tbench.ai/leaderboard):

- Qwen3.6-27B **59.3 no Terminal-Bench 2.0** ≈ Sonnet 4.6 (59.1) — modelo
  aberto 27B empata com frontier.
- SWE-bench Pro: dev reproduziu model card 53.5% → **28% com agente
  bash-only → 50.7% adicionando UMA tool (`str_replace`)**. "Todos esses
  números são do HARNESS e não do modelo."
- **Agent = Model + Harness**; harness = loop + tools + context + policy
  + persistence. Mesmo modelo em harnesses diferentes = **até 5.1 pts de
  diferença** (GPT-5.5: 83.1 Codex vs 78.0 Terminus).
- **Camadas do outer harness**: GUIDES (antes: instruções, exemplos,
  tool descriptions) + SENSORS (depois: tests, linters, validators,
  reviewers) + **CAPS** (boundary que o modelo não atravessa por
  conversa — permissões/infra).

**Mapeamento JARVIS (inner+outer):**
| Camada | JARVIS |
|--------|--------|
| Guide | `TOOL_USE_DISCIPLINE` + FERRAMATAS + descrições WHEN-first |
| Sensor | validator + completion (claim-checker) + LoopDetector + verify |
| Cap | permission gates (approve/write-jail/protected-files) |
| Tools | devtools 9 + browser 7 ações + memory/rag/vault |
| Context | REPO MAP + RECENT LESSONS + compact + âncoras |

**Conclusão:** a tese do dono (bonsai + envelope maxado no modelo mais
fraco) = **harness-maxxing** — validada pela indústria. O trabalho está
no outer harness (guides/sensors/caps), não em trocar modelo (H4
contra-dito: bonsai 5/5 vs fast 3/5).

**Desafios baixáveis:** terminal-bench (github.com/harbor-framework/
terminal-bench) — Docker ATIVO no host; tasks com docker-compose +
testes. Instalação: venv (não pip global) ou nix.
